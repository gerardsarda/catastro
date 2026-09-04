# -*- coding: utf-8 -*-
"""
app.py
------
Interficie web (Streamlit) per generar els contractes de cessio de drets de
caca. Fa els mateixos passos que la cadena de scripts 04 -> 06 -> 03, pero
amb el poligon del vedat dibuixat a ma sobre un mapa en comptes d'escrit al
codi.

    streamlit run app.py

No reimplementa res: importa els scripts existents i els crida. Si es canvia
un script, l'app canvia amb ell.
"""

import copy
import glob
import importlib.util
import io
import json
import os
import sys
import zipfile

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# RUTES I CARREGA DELS SCRIPTS EXISTENTS
# ---------------------------------------------------------------------------
RAIZ = os.path.dirname(os.path.abspath(__file__))
DIR_SCRIPTS = os.path.join(RAIZ, "scripts")
DIR_FICHAS = os.path.join(RAIZ, "datos", "fichas")
RUTA_COMUNES = os.path.join(RAIZ, "datos", "dades_comunes.json")
DIR_GML = os.path.join(RAIZ, "datos_crudos", "gml")

# scripts/06 fa "import catastro_api", aixi que la carpeta ha de ser al path.
if DIR_SCRIPTS not in sys.path:
    sys.path.insert(0, DIR_SCRIPTS)


def _carregar_modul(nom, fitxer):
    """Importa un script el nom del qual comenca per xifres (03_, 04_...).

    Python no deixa fer "import 04_parcelas_en_poligono", pero si carregar-lo
    per ruta. Es exactament el que fa el script 06 amb el 04.
    """
    spec = importlib.util.spec_from_file_location(nom, os.path.join(DIR_SCRIPTS, fitxer))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


s03 = _carregar_modul("s03", "03_generar_contracte.py")
s04 = _carregar_modul("s04", "04_parcelas_en_poligono.py")
s06 = _carregar_modul("s06", "06_generar_fichas.py")
import catastro_api as ca  # noqa: E402

from pyproj import Transformer  # noqa: E402
from shapely import STRtree  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import SimpleDocTemplate  # noqa: E402

import folium  # noqa: E402
from folium.plugins import Draw  # noqa: E402
from streamlit_folium import st_folium  # noqa: E402


# ---------------------------------------------------------------------------
# CONSTANTS DE LA INTERFICIE
# ---------------------------------------------------------------------------
CENTRE_MAPA = (41.28, 1.25)   # Valls i rodalia
ZOOM_INICIAL = 12

# Maxim de parcel-les que es dibuixen al mapa de resultats. Amb milers de
# poligons el navegador es queda clavat; la taula, en canvi, les te totes.
MAX_POLIGONS_MAPA = 500

# Parcel-les per pagina al Pas 3. Amb centenars de formularis oberts alhora
# la pagina es fa inusable.
PER_PAGINA = 40

# Totes les parcel-les entren igual (toquen el poligon), aixi que totes es
# pinten del mateix color. Ja no hi ha estats.
COLOR_PARCELLA = "#1a9850"

TIPUS_DOCUMENT = ["", "DNI", "NIE", "NIF", "Passaport"]

# Tolerancia (m2) per no avisar de sortides del poligon que nomes son soroll
# de precisio a la vora dels municipis.
TOLERANCIA_FORA_M2 = 1000.0


# ---------------------------------------------------------------------------
# CARREGA DE DADES (amb memoria cau: el GML son desenes de milers de parcel-les)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def carregar_parcelles():
    """Totes les parcel-les dels GML de datos_crudos/gml/, amb geometria."""
    return s04.cargar_parcelas()


@st.cache_resource(show_spinner=False)
def cobertura_gml(_parcelles):
    """Fins on arriben els GML carregats, com una taca sense forats interiors.

    La unio de les parcel-les NO es una taca massissa: els rius, les carreteres
    i les vies del tren son domini public i no tenen parcel-la cadastral, aixi
    que hi deixen centenars de forats. Amb el contorn de prova son 309 trossos
    i 32 ha, que no volen dir que falti cap municipi.

    Per aixo la cobertura es reconstrueix quedant-nos NOMES amb el contorn
    exterior de cada tros de la unio: els forats de dins desapareixen i el
    limit de fora es queda igual. Aixi l'avis nomes salta quan el poligon surt
    de veritat de la zona descarregada."""
    unio = unary_union([p["geom"] for p in _parcelles])
    trossos = [unio] if unio.geom_type == "Polygon" else list(unio.geoms)
    return unary_union([Polygon(t.exterior) for t in trossos])


@st.cache_resource(show_spinner=False)
def index_espacial(_parcelles):
    """Index espacial per calcular els limits (nord/sud/est/oest) d'una finca."""
    return STRtree([p["geom"] for p in _parcelles])


@st.cache_resource(show_spinner=False)
def transformadors():
    """(lat/lon -> UTM, UTM -> lat/lon). Els mateixos CRS que el script 04."""
    return (Transformer.from_crs(s04.CRS_GPS, s04.CRS_GML, always_xy=True),
            Transformer.from_crs(s04.CRS_GML, s04.CRS_GPS, always_xy=True))


def municipis_disponibles():
    """Codis de municipi dels GML que hi ha a datos_crudos/gml/."""
    return sorted(
        s04.codigo_municipio_de_fichero(r)
        for r in glob.glob(os.path.join(DIR_GML, "*.cadastralparcel.gml"))
    )


def carregar_comunes():
    """Llegeix datos/dades_comunes.json. Si no hi es, torna l'esquelet buit."""
    if os.path.exists(RUTA_COMUNES):
        with open(RUTA_COMUNES, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {
        "cessionaria": {"_font": "MANUAL"},
        "coto": {"_font": "MANUAL"},
        "condicions": {"_font": "MANUAL"},
    }


def desar_comunes(dades):
    os.makedirs(os.path.dirname(RUTA_COMUNES), exist_ok=True)
    with open(RUTA_COMUNES, "w", encoding="utf-8") as fh:
        json.dump(dades, fh, ensure_ascii=False, indent=2)


def valor(dades, bloc, clau):
    return (dades.get(bloc) or {}).get(clau, "") or ""


def plural(n, singular, plural_):
    """'1 contracte' / '4 contractes'. Concordanca, que aixo va en catala."""
    return "{} {}".format(n, singular if n == 1 else plural_)


# ---------------------------------------------------------------------------
# ESTAT DE LA SESSIO
# ---------------------------------------------------------------------------
def inicialitza_estat():
    per_defecte = {
        "poligon_latlon": None,     # [(lat, lon), ...] del poligon dibuixat
        "files": None,              # resultat del creuament (llista de dicts)
        "geojson_parcelles": None,  # per pintar-les al mapa de resultats
        "avis_cobertura": None,     # text de l'avis de municipis que falten
        "resum": None,              # xifres del creuament
        "cedents": {},              # refcat -> dades del cedent + inclusio
        "zip_contractes": None,     # bytes del ZIP generat
        "incidencies": [],          # parcel-les saltades a la generacio
        "pagina_pas3": 0,
        "_nav_to": None,            # index del tab al qual saltar
    }
    for clau, val in per_defecte.items():
        st.session_state.setdefault(clau, val)


def _nav(idx_desti):
    """Desa el tab de destí i recarrega; el JS el clica al proper render."""
    st.session_state["_nav_to"] = idx_desti
    st.rerun()


def _botons_nav(idx_actual, n_tabs=4):
    """Botons Anterior / Següent al peu de cada pestanya."""
    st.divider()
    cols = st.columns([1, 5, 1])
    if idx_actual > 0:
        if cols[0].button("← Anterior", key=f"nav_ant_{idx_actual}",
                          use_container_width=True):
            _nav(idx_actual - 1)
    if idx_actual < n_tabs - 1:
        if cols[2].button("Següent →", key=f"nav_seg_{idx_actual}",
                          use_container_width=True, type="primary"):
            _nav(idx_actual + 1)


# ---------------------------------------------------------------------------
# PAS 2 - CREUAMENT DEL POLIGON AMB LES PARCEL-LES
# ---------------------------------------------------------------------------
def poligon_del_dibuix(dibuix):
    """Treu [(lat, lon), ...] del GeoJSON que retorna el plugin Draw."""
    if not dibuix:
        return None
    geom = dibuix.get("geometry") or {}
    if geom.get("type") != "Polygon":
        return None
    anell = (geom.get("coordinates") or [[]])[0]
    if len(anell) < 4:
        return None
    # Draw tanca l'anell repetint el primer punt; el poligon no el necessita.
    punts = [(float(lat), float(lon)) for lon, lat in anell[:-1]]
    return punts or None


def anells_a_latlon(poli, t_inv):
    """Anells d'un poligon UTM -> coordenades [lon, lat] per a GeoJSON."""
    anells = [list(poli.exterior.coords)] + [list(r.coords) for r in poli.interiors]
    return [[list(t_inv.transform(x, y)) for (x, y) in a] for a in anells]


def geometria_geojson(geom, t_inv):
    if geom.geom_type == "Polygon":
        return {"type": "Polygon", "coordinates": anells_a_latlon(geom, t_inv)}
    return {"type": "MultiPolygon",
            "coordinates": [anells_a_latlon(p, t_inv) for p in geom.geoms]}


def contorn_latlon(coto, t_inv):
    """Contorn exterior del poligon del vedat, en [(lat, lon), ...]."""
    poli = coto if coto.geom_type == "Polygon" else max(coto.geoms, key=lambda g: g.area)
    return [list(t_inv.transform(x, y))[::-1] for (x, y) in poli.exterior.coords]


def creuar(punts_latlon):
    """Mateix calcul que el main() del script 04, pero amb el poligon dibuixat.

    LA REGLA: si la geometria de la parcel-la toca el poligon dibuixat, encara
    que sigui nomes per un vertex, la finca entra SENCERA, amb la seva
    superficie cadastral completa. No es reparteixen metres ni hi ha estats
    "parcial": els drets de caca es cedeixen per finca.

    Retorna (files, geojson, avis_cobertura, resum). Cap dada nova: nomes el
    creuament de la geometria del Cadastre amb el poligon de l'usuari.
    """
    # construir_poligono_coto() llegeix la llista del modul: li posem la del
    # dibuix i reutilitzem la seva conversio i la seva reparacio de poligons.
    s04.POLIGONO_COTO = punts_latlon
    coto = s04.construir_poligono_coto()

    parcelles = carregar_parcelles()
    _, t_inv = transformadors()

    # Fins on arriben els GML descarregats. Si el poligon en surt, falten
    # municipis i el resultat seria incomplet sense avisar-ne.
    cobertura = cobertura_gml(parcelles)
    fora = coto.difference(cobertura)
    avis = None
    if fora.area > TOLERANCIA_FORA_M2:
        avis = ("El polígon dibuixat surt de la zona coberta pels GML. "
                "Descarrega el GML dels municipis que falten i torna-ho a intentar. "
                "(Queden fora {:.1f} ha, un {:.1f} % del polígon.)".format(
                    fora.area / 10000, fora.area / coto.area * 100 if coto.area else 0))

    files, geoms = [], {}
    for p in parcelles:
        g = p["geom"]
        # intersects() tambe es cert quan nomes es toquen per la vora o per un
        # sol punt. Es exactament el criteri que volem.
        if not g.intersects(coto):
            continue

        # Superficie que se li imputa a la finca: la OFICIAL del Cadastre
        # (areaValue del GML). Nomes si el GML no la porta fem servir la del
        # dibuix, que es la mateixa xifra amb decimes de diferencia.
        area_computada = p["area_catastro_m2"] or round(g.area)

        c = g.centroid
        lon, lat = t_inv.transform(c.x, c.y)

        # Claus en castella a proposit: son les que espera construir_ficha()
        # del script 06, que llegeix les files del CSV del script 04.
        files.append({
            "refcat": p["refcat"],
            "cod_muni": p["cod_muni"],
            "tipo": "rustica" if s04.es_rustica(p["refcat"]) else "urbana",
            "area_catastro_m2": p["area_catastro_m2"] or 0,
            "area_geometria_m2": round(g.area),
            "area_computada_m2": area_computada,
            "n_trozos": p["n_trozos"],
            "centroide_lat": round(lat, 6),
            "centroide_lon": round(lon, 6),
            "url_cartografia": ("https://www1.sedecatastro.gob.es/Cartografia/mapa.aspx"
                                "?del={}&mun={}&refcat={}".format(
                                    p["cod_muni"][:2], int(p["cod_muni"][2:]), p["refcat"])),
        })
        geoms[p["refcat"]] = g

    # Totes entren igual: n'hi ha prou d'ordenar de mes gran a mes petita.
    files.sort(key=lambda f: -f["area_computada_m2"])

    # Nomes es converteixen a lat/lon les que es pintaran: passar milers de
    # poligons de coordenades es lent i el navegador tampoc no els aguanta.
    geojson = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "properties": {"refcat": f["refcat"], "municipi": f["cod_muni"],
                        "ha": round(f["area_computada_m2"] / 10000, 4)},
         "geometry": geometria_geojson(geoms[f["refcat"]], t_inv)}
        for f in files[:MAX_POLIGONS_MAPA]
    ]}

    n_rustiques = sum(1 for f in files if f["tipo"] == "rustica")
    resum = {
        "total": len(files),
        "rustiques": n_rustiques,
        "urbanes": len(files) - n_rustiques,
        "ha_vedat": coto.area / 10000,
        # Suma de superficies cadastrals SENCERES: es mes gran que l'area del
        # poligon dibuixat, perque les finques de la vora hi entren senceres.
        "ha_total": sum(f["area_computada_m2"] for f in files) / 10000,
        "contorn": contorn_latlon(coto, t_inv),
    }
    return files, geojson, avis, resum


# ---------------------------------------------------------------------------
# PAS 4 - FITXA I PDF
# ---------------------------------------------------------------------------
def ruta_ficha(refcat):
    return os.path.join(DIR_FICHAS, "finca_{}.json".format(refcat))


def obtenir_ficha(fila, comunes):
    """Torna la fitxa de la parcel-la: del disc si hi es, o del Cadastre.

    Si cal demanar-la, es fa exactament igual que al script 06 (API DNPRC +
    limits calculats de la geometria), aixi la fitxa surt identica.
    """
    desti = ruta_ficha(fila["refcat"])
    if os.path.exists(desti):
        with open(desti, "r", encoding="utf-8") as fh:
            return json.load(fh)

    dades_cat = ca.datos_de_parcela(fila["refcat"]) or {}
    parcelles = carregar_parcelles()
    p = next((x for x in parcelles if x["refcat"] == fila["refcat"]), None)
    if p is None:
        raise ValueError("la parcel·la no és a cap GML carregat")

    limits = s06.calcular_linderos(p["geom"], index_espacial(parcelles), parcelles)
    return s06.construir_ficha(fila, dades_cat, limits, comunes, s06.carregar_comarques())


def fusiona(ficha, cedent, comunes):
    """Posa el cedent del Pas 3 i les dades comunes del Pas 1 dins la fitxa."""
    d = copy.deepcopy(ficha)

    tipus = (cedent.get("tipus_document") or "").strip()
    numero = (cedent.get("numero_document") or "").strip()
    # El contracte diu "amb {tipus_document}": ha de sortir "amb DNI 12345678A".
    document = " ".join(x for x in (tipus, numero) if x)

    d["cedent"] = {
        "_font": "MANUAL (el Catastro no publica la titularitat)",
        "nom": (cedent.get("nom") or "").strip(),
        "tipus_document": document,
        "numero_document": numero,
        "adreca": (cedent.get("adreca") or "").strip(),
    }
    for clau in ("cessionaria", "coto", "condicions"):
        if clau in comunes:
            d[clau] = comunes[clau]
    return d


def pdf_en_memoria(ficha):
    """Construeix el PDF amb el generador del script 03, sense tocar disc."""
    rc = ficha["finca"]["referencia_cadastral"]
    memoria = io.BytesIO()
    doc = SimpleDocTemplate(
        memoria, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title="Contracte cessio drets de caca - {}".format(rc),
        author="Cessio de drets de caca",
    )
    doc.build(s03.construir(ficha))
    return memoria.getvalue()


# ---------------------------------------------------------------------------
# INTERFICIE
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Contractes de cessió de drets de caça",
                   page_icon="🦌", layout="wide")

# Streamlit escriu uns quants rètols propis en anglès que no es poden traduir
# des de l'API ("Press Enter to apply", els botons de la barra de la taula,
# "Deploy" i el menú). Com que tota l'aplicació ha de sortir en català, aquí
# s'amaguen. Si algun dia calgués tornar-los a veure, n'hi ha prou amb esborrar
# aquest bloc.
st.markdown("""
<style>
  [data-testid="InputInstructions"] { display: none !important; }
  [data-testid="stElementToolbar"]  { display: none !important; }
  [data-testid="stAppDeployButton"] { display: none !important; }
  [data-testid="stMainMenu"]        { display: none !important; }
</style>
""", unsafe_allow_html=True)

inicialitza_estat()

st.title("Contractes de cessió de drets de caça")
st.caption("Del polígon del vedat al contracte en PDF, una còpia per finca.")

pas1, pas2, pas3, pas4 = st.tabs([
    "1 · Dades de la cessionària",
    "2 · Selecció de l'àrea",
    "3 · Dades del cedent",
    "4 · Generació de PDFs",
])


# ------------------------------- PAS 1 -------------------------------------
with pas1:
    st.subheader("Dades comunes a tots els contractes")
    st.write("Són iguals per a totes les finques: es revisen una vegada i valen "
             "per a tots els contractes. Es desen a `datos/dades_comunes.json`.")

    comunes = carregar_comunes()

    with st.form("form_comunes"):
        st.markdown("#### Cessionària (associació de caçadors)")
        c1, c2 = st.columns(2)
        with c1:
            nom = st.text_input("Nom de l'associació",
                                value=valor(comunes, "cessionaria", "nom"),
                                placeholder="Societat de Caçadors de …")
            nif = st.text_input("NIF", value=valor(comunes, "cessionaria", "nif"),
                                placeholder="G00000000")
            adreca = st.text_input("Adreça (domicili social)",
                                   value=valor(comunes, "cessionaria", "adreca"),
                                   placeholder="Carrer, número, població, CP")
            registre = st.text_input("Registre on està inscrita",
                                     value=valor(comunes, "cessionaria", "registre"),
                                     placeholder="Registre d'Associacions de la Generalitat")
        with c2:
            num_registre = st.text_input("Número de registre",
                                         value=valor(comunes, "cessionaria", "num_registre"))
            representant = st.text_input("Nom del/de la representant",
                                         value=valor(comunes, "cessionaria", "representant"))
            dni_representant = st.text_input(
                "Document del/de la representant",
                value=valor(comunes, "cessionaria", "dni_representant"),
                placeholder="DNI 00000000X")
            carrec = st.text_input("Càrrec",
                                   value=valor(comunes, "cessionaria", "carrec"),
                                   placeholder="President/a")

        st.markdown("#### Vedat")
        nom_coto = st.text_input("Nom del vedat",
                                 value=valor(comunes, "coto", "nom_coto"),
                                 placeholder="T-00000")

        st.markdown("#### Condicions del contracte")
        c3, c4 = st.columns(2)
        with c3:
            poblacio = st.text_input("Població on se signa",
                                     value=valor(comunes, "condicions", "poblacio"))
            data = st.text_input("Data del contracte",
                                 value=valor(comunes, "condicions", "data"),
                                 placeholder="1 de setembre de 2026")
            durada_anys = st.text_input("Durada",
                                        value=valor(comunes, "condicions", "durada_anys"),
                                        placeholder="cinc (5) anys")
            temporada_inici = st.text_input("Temporada d'inici",
                                            value=valor(comunes, "condicions", "temporada_inici"),
                                            placeholder="2026-2027")
            temporada_fi = st.text_input("Temporada de fi",
                                         value=valor(comunes, "condicions", "temporada_fi"),
                                         placeholder="2030-2031")
        with c4:
            preavis = st.text_input("Preavís de no-renovació",
                                    value=valor(comunes, "condicions", "preavis"),
                                    placeholder="dos (2) mesos")
            contraprestacio = st.text_input("Contraprestació",
                                            value=valor(comunes, "condicions", "contraprestacio"),
                                            placeholder="a títol gratuït")
            forma_pagament = st.text_input("Forma de pagament",
                                           value=valor(comunes, "condicions", "forma_pagament"),
                                           placeholder="anualment, dins el mes de gener")
            mitja_pagament = st.text_input("Mitjà de pagament",
                                           value=valor(comunes, "condicions", "mitja_pagament"),
                                           placeholder="transferència bancària")
            partit_judicial = st.text_input("Partit judicial",
                                            value=valor(comunes, "condicions", "partit_judicial"),
                                            placeholder="Valls")

        desat = st.form_submit_button("Desa les dades", type="primary")

    if desat:
        dades = copy.deepcopy(comunes)
        dades.setdefault("cessionaria", {})
        dades.setdefault("coto", {})
        dades.setdefault("condicions", {})
        dades["cessionaria"].update({
            "nom": nom, "nif": nif, "adreca": adreca, "registre": registre,
            "num_registre": num_registre, "representant": representant,
            "dni_representant": dni_representant, "carrec": carrec,
        })
        dades["coto"].update({"nom_coto": nom_coto})
        dades["condicions"].update({
            "poblacio": poblacio, "data": data, "durada_anys": durada_anys,
            "temporada_inici": temporada_inici, "temporada_fi": temporada_fi,
            "preavis": preavis, "contraprestacio": contraprestacio,
            "forma_pagament": forma_pagament, "mitja_pagament": mitja_pagament,
            "partit_judicial": partit_judicial,
        })
        desar_comunes(dades)
        st.success("Dades desades a `datos/dades_comunes.json`.")

        buits = [k for k, v in dades["cessionaria"].items()
                 if not k.startswith("_") and not v]
        buits += [k for k, v in dades["condicions"].items()
                  if not k.startswith("_") and not v]
        if not dades["coto"].get("nom_coto"):
            buits.append("nom_coto")
        if buits:
            st.warning("Hi ha {} buits. Al PDF hi sortirà una línia de punts en "
                       "lloc del valor: {}".format(
                           plural(len(buits), "camp", "camps"), ", ".join(buits)))

    _botons_nav(0)


# ------------------------------- PAS 2 -------------------------------------
with pas2:
    st.subheader("Dibuixa el polígon del vedat")

    munis = municipis_disponibles()
    if not munis:
        st.error("No hi ha cap fitxer GML a `datos_crudos/gml/`. Executa "
                 "`python scripts/07_descargar_gml.py <codis de municipi>` "
                 "abans de continuar.")
    else:
        st.write("Municipis disponibles (GML descarregats): **{}**".format(", ".join(munis)))
        st.write("Fes servir l'eina de polígon del mapa (icones de l'esquerra) per "
                 "traçar el contorn del vedat. Quan el tanquis, prem **Calcula les "
                 "parcel·les**.")

        mapa = folium.Map(location=CENTRE_MAPA, zoom_start=ZOOM_INICIAL,
                          tiles="OpenStreetMap", control_scale=True)
        Draw(
            export=False,
            draw_options={"polyline": False, "rectangle": True, "circle": False,
                          "marker": False, "circlemarker": False,
                          "polygon": {"allowIntersection": False}},
            edit_options={"edit": True},
        ).add_to(mapa)

        sortida = st_folium(mapa, height=520, width=None, key="mapa_dibuix",
                            returned_objects=["last_active_drawing", "all_drawings"])

        dibuix = (sortida or {}).get("last_active_drawing")
        if dibuix is None:
            tots = (sortida or {}).get("all_drawings") or []
            dibuix = tots[-1] if tots else None

        punts = poligon_del_dibuix(dibuix)
        if punts:
            st.session_state["poligon_latlon"] = punts

        actual = st.session_state["poligon_latlon"]
        if actual:
            st.success("Polígon de {} desat.".format(
                plural(len(actual), "vèrtex", "vèrtexs")))
        else:
            st.info("Encara no hi ha cap polígon dibuixat.")

        c1, c2 = st.columns([1, 3])
        calcular = c1.button("Calcula les parcel·les", type="primary",
                             disabled=not actual)
        if c2.button("Esborra el polígon", disabled=not actual):
            for clau in ("poligon_latlon", "files", "geojson_parcelles",
                         "avis_cobertura", "resum", "zip_contractes"):
                st.session_state[clau] = None
            # Tambe els widgets del Pas 3: si no, en tornar a calcular
            # reapareixerien els noms i les caselles de la seleccio anterior.
            for clau in [k for k in st.session_state
                         if k.split("_")[0] in ("nom", "adreca", "tipusdoc",
                                                "numdoc", "inclou")]:
                del st.session_state[clau]
            st.session_state["cedents"] = {}
            st.session_state["incidencies"] = []
            st.rerun()

        if calcular and actual:
            error = None
            try:
                with st.spinner("Llegint els GML i creuant la geometria… "
                                "(la primera vegada triga una estona)"):
                    files, geojson, avis, resum = creuar(actual)
            except SystemExit as e:
                error = "No s'ha pogut fer el càlcul: {}".format(e)
            except Exception as e:
                error = "Error en el càlcul: {}: {}".format(type(e).__name__, e)

            if error:
                st.error(error)
            else:
                st.session_state["files"] = files
                st.session_state["geojson_parcelles"] = geojson
                st.session_state["avis_cobertura"] = avis
                st.session_state["resum"] = resum
                st.session_state["zip_contractes"] = None
                st.session_state["incidencies"] = []
                st.session_state["pagina_pas3"] = 0
                # Totes entren marcades: si toquen el poligon, hi son. Qui
                # en vulgui treure alguna ho fa a ma al Pas 3. S'escriu tambe
                # a l'estat del widget perque una casella ja dibuixada en un
                # calcul anterior no es quedi com estava.
                cedents = st.session_state["cedents"]
                for f in files:
                    c = cedents.setdefault(f["refcat"], {
                        "nom": "", "tipus_document": "",
                        "numero_document": "", "adreca": "",
                    })
                    c["inclou"] = True
                    st.session_state["inclou_{}".format(f["refcat"])] = c["inclou"]
                st.rerun()

    # --- Resultats ---------------------------------------------------------
    if st.session_state["avis_cobertura"]:
        st.warning(st.session_state["avis_cobertura"])

    files = st.session_state["files"]
    if files:
        r = st.session_state["resum"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Finques", r["total"])
        m2.metric("Rústiques / urbanes",
                  "{} / {}".format(r["rustiques"], r["urbanes"]))
        m3.metric("Superfície cedida", "{:.1f} ha".format(r["ha_total"]))
        m4.metric("Àrea del polígon", "{:.1f} ha".format(r["ha_vedat"]))
        st.caption("Tota finca que toqui el polígon hi entra **sencera**, amb la "
                   "seva superfície cadastral completa. Per això la superfície "
                   "cedida és més gran que l'àrea del polígon dibuixat.")

        st.markdown("#### Finques trobades")
        taula = pd.DataFrame([{
            "refcat": f["refcat"],
            "municipi": f["cod_muni"],
            "tipus": "rústica" if f["tipo"] == "rustica" else "urbana",
            "superficie_m2": f["area_computada_m2"],
            "superficie_ha": round(f["area_computada_m2"] / 10000, 4),
        } for f in files])
        st.dataframe(taula, use_container_width=True, hide_index=True, height=380)

        st.download_button(
            "Descarrega la taula (.csv)",
            data=taula.to_csv(index=False, sep=";").encode("utf-8-sig"),
            file_name="parcelles_dins_el_vedat.csv", mime="text/csv")

        st.markdown("#### Les finques sobre el mapa")
        st.caption("En blau, el polígon dibuixat. En verd, les finques que el "
                   "toquen: totes entren senceres.")
        if r["total"] > MAX_POLIGONS_MAPA:
            st.info("Al mapa s'hi dibuixen les {} primeres parcel·les de {}. La "
                    "taula i la generació de contractes les tenen totes."
                    .format(MAX_POLIGONS_MAPA, r["total"]))

        centre = (files[0]["centroide_lat"], files[0]["centroide_lon"])
        mapa_res = folium.Map(location=centre, zoom_start=13, tiles="OpenStreetMap",
                              control_scale=True)
        folium.PolyLine(r["contorn"], color="#2b6cb0", weight=3, opacity=0.9,
                        tooltip="Polígon del vedat").add_to(mapa_res)
        folium.GeoJson(
            st.session_state["geojson_parcelles"],
            style_function=lambda x: {
                "fillColor": COLOR_PARCELLA, "color": COLOR_PARCELLA,
                "weight": 1, "fillOpacity": 0.45,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["refcat", "municipi", "ha"],
                aliases=["Referència:", "Municipi:", "Superfície (ha):"]),
        ).add_to(mapa_res)
        st_folium(mapa_res, height=520, width=None, key="mapa_resultats",
                  returned_objects=[])

    _botons_nav(1)


# ------------------------------- PAS 3 -------------------------------------
with pas3:
    st.subheader("Dades del cedent (propietari/ària) per finca")
    files = st.session_state["files"]

    if not files:
        st.info("Primer cal calcular les parcel·les al **Pas 2**.")
    else:
        st.write("El Cadastre no publica la titularitat: aquestes dades s'han "
                 "d'omplir a mà. El que quedi buit sortirà al PDF com una línia "
                 "de punts.")
        st.caption("Cada camp es desa en sortir-ne (prem la tecla de tabulació, "
                   "fes clic a fora o prem Retorn). La casella de l'esquerra de "
                   "cada finca diu si entra a la generació de contractes.")

        cedents = st.session_state["cedents"]

        def _desa_camp(refcat, camp, clau_widget):
            cedents.setdefault(refcat, {})[camp] = st.session_state[clau_widget]

        c1, c2, c3 = st.columns([2, 2, 1])
        municipis = sorted({f["cod_muni"] for f in files})
        tria_muni = c1.multiselect("Filtra per municipi", municipis,
                                   default=municipis,
                                   placeholder="Tria un o més municipis")
        nomes_rustiques = c2.checkbox("Només finques rústiques", value=False)
        nomes_pendents = c3.checkbox("Només sense nom", value=False)

        visibles = [f for f in files if f["cod_muni"] in tria_muni]
        if nomes_rustiques:
            visibles = [f for f in visibles if f["tipo"] == "rustica"]
        if nomes_pendents:
            visibles = [f for f in visibles
                        if not (cedents.get(f["refcat"], {}).get("nom") or "").strip()]

        def _marca_totes(quines, valor_inclou):
            """Marca o desmarca la inclusio de tot un bloc de finques.

            Cal tocar TAMBE l'estat del widget (clau "inclou_<refcat>"): un cop
            una casella s'ha dibuixat, Streamlit li guarda el valor per clau i
            ja no fa cas del "value=" de la crida. Sense aixo, els botons de
            marcar-ho tot canviarien les dades pero no les caselles.
            """
            for fila in quines:
                cedents.setdefault(fila["refcat"], {})["inclou"] = valor_inclou
                st.session_state["inclou_{}".format(fila["refcat"])] = valor_inclou

        b1, b2, _ = st.columns([1, 1, 3])
        if b1.button("Inclou-les totes (visibles)"):
            _marca_totes(visibles, True)
            st.rerun()
        if b2.button("Exclou-les totes (visibles)"):
            _marca_totes(visibles, False)
            st.rerun()

        total_pag = max(1, (len(visibles) + PER_PAGINA - 1) // PER_PAGINA)
        pagina = st.session_state["pagina_pas3"]
        if pagina >= total_pag:
            pagina = 0
        if total_pag > 1:
            pagina = st.number_input(
                "Pàgina (de {}, {} finques per pàgina)".format(total_pag, PER_PAGINA),
                min_value=1, max_value=total_pag, value=pagina + 1, step=1) - 1
        st.session_state["pagina_pas3"] = pagina

        tros = visibles[pagina * PER_PAGINA:(pagina + 1) * PER_PAGINA]
        st.caption("Es mostren {} de {}.".format(
            len(tros), plural(len(visibles), "finca", "finques")))

        for f in tros:
            rc = f["refcat"]
            dades = cedents.setdefault(rc, {
                "nom": "", "tipus_document": "", "numero_document": "", "adreca": "",
                "inclou": True,
            })

            # Si ja existeix la fitxa al disc, en prenem el cedent com a punt de
            # partida: aixi no es perd el que ja s'havia omplert en una altra
            # sessio o amb els scripts.
            if not dades.get("_carregada"):
                cami = ruta_ficha(rc)
                if os.path.exists(cami):
                    try:
                        with open(cami, "r", encoding="utf-8") as fh:
                            previ = json.load(fh).get("cedent") or {}
                    except (ValueError, OSError):
                        previ = {}
                    # Al disc el document va junt ("DNI 12345678A"): el partim
                    # per tornar a omplir el desplegable i el numero.
                    doc = (previ.get("tipus_document") or "").strip()
                    numero = (previ.get("numero_document") or "").strip()
                    tipus = ""
                    for t in TIPUS_DOCUMENT[1:]:
                        if doc.upper().startswith(t.upper()):
                            tipus = t
                            numero = numero or doc[len(t):].strip()
                            break
                    if not tipus and doc and not numero:
                        numero = doc
                    dades["nom"] = dades["nom"] or (previ.get("nom") or "")
                    dades["tipus_document"] = dades["tipus_document"] or tipus
                    dades["numero_document"] = dades["numero_document"] or numero
                    dades["adreca"] = dades["adreca"] or (previ.get("adreca") or "")
                dades["_carregada"] = True

            # Els camps es sembren UNA vegada a l'estat i despres mana el
            # widget: passar-li "value=" a cada passada barallaria dues fonts
            # de veritat i, un cop dibuixat, Streamlit ja no fa cas del value.
            # El que escriu l'usuari torna a "cedents" via _desa_camp, que es
            # el que sobreviu al canvi de pagina i alimenta el Pas 4.
            claus = {camp: "{}_{}".format(prefix, rc) for camp, prefix in (
                ("nom", "nom"), ("adreca", "adreca"),
                ("tipus_document", "tipusdoc"), ("numero_document", "numdoc"),
                ("inclou", "inclou"))}
            for camp, k in claus.items():
                if k not in st.session_state:
                    st.session_state[k] = (bool(dades.get("inclou"))
                                           if camp == "inclou"
                                           else dades.get(camp, "") or "")
            if st.session_state[claus["tipus_document"]] not in TIPUS_DOCUMENT:
                st.session_state[claus["tipus_document"]] = ""

            # La casella va FORA del desplegable: si anes a dins i el titol
            # canviés en marcar-la, Streamlit tornaria a crear el desplegable
            # i es tancaria a cada clic.
            col_marca, col_finca = st.columns([0.05, 0.95],
                                              vertical_alignment="center")
            col_marca.checkbox("Inclou en la generació", key=claus["inclou"],
                               label_visibility="collapsed",
                               help="Inclou aquesta finca en la generació de contractes",
                               on_change=_desa_camp,
                               args=(rc, "inclou", claus["inclou"]))

            titol = "{}  ·  municipi {}  ·  {}  ·  {:,} m²".format(
                rc, f["cod_muni"],
                "rústica" if f["tipo"] == "rustica" else "urbana",
                f["area_computada_m2"]).replace(",", ".")
            with col_finca.expander(titol, expanded=False):
                col_a, col_b = st.columns([3, 2])
                with col_a:
                    st.text_input("Nom i cognoms del/de la cedent",
                                  key=claus["nom"],
                                  placeholder="Nom del propietari/ària",
                                  on_change=_desa_camp,
                                  args=(rc, "nom", claus["nom"]))
                    st.text_input("Adreça a efectes de notificacions",
                                  key=claus["adreca"],
                                  placeholder="Carrer, número, població, CP",
                                  on_change=_desa_camp,
                                  args=(rc, "adreca", claus["adreca"]))
                with col_b:
                    st.selectbox(
                        "Tipus de document", TIPUS_DOCUMENT,
                        key=claus["tipus_document"],
                        format_func=lambda t: t or "— sense especificar —",
                        on_change=_desa_camp,
                        args=(rc, "tipus_document", claus["tipus_document"]))
                    st.text_input("Número de document",
                                  key=claus["numero_document"],
                                  placeholder="00000000X",
                                  on_change=_desa_camp,
                                  args=(rc, "numero_document", claus["numero_document"]))

                st.caption("Cadastre: [fitxa cartogràfica]({})".format(f["url_cartografia"]))

        n_sel = sum(1 for f in files if cedents.get(f["refcat"], {}).get("inclou"))
        st.info("Seleccionades per generar: **{}** de {}.".format(
            n_sel, plural(len(files), "parcel·la", "parcel·les")))

    _botons_nav(2)


# ------------------------------- PAS 4 -------------------------------------
with pas4:
    st.subheader("Generació dels contractes")
    files = st.session_state["files"]

    if not files:
        st.info("Primer cal calcular les parcel·les al **Pas 2**.")
    else:
        cedents = st.session_state["cedents"]
        seleccionades = [f for f in files if cedents.get(f["refcat"], {}).get("inclou")]
        comunes = carregar_comunes()

        sense_nom = [f["refcat"] for f in seleccionades
                     if not (cedents.get(f["refcat"], {}).get("nom") or "").strip()]
        if sense_nom:
            st.warning("Hi ha {} sense nom de cedent. Al PDF hi sortirà una "
                       "línia de punts.".format(plural(
                           len(sense_nom), "finca seleccionada",
                           "finques seleccionades")))
        if not valor(comunes, "coto", "nom_coto"):
            st.warning("El nom del vedat és buit al **Pas 1**.")

        st.caption("Les fitxes que no existeixin a `datos/fichas/` es demanaran al "
                   "Cadastre (API Consulta_DNPRC). Pot trigar: hi ha una pausa "
                   "entre peticions per no saturar el servei.")

        generar = st.button(
            "Genera els contractes ({})".format(
                plural(len(seleccionades), "seleccionada", "seleccionades")),
            type="primary", disabled=not seleccionades)

        if generar:
            barra = st.progress(0.0)
            estat = st.empty()
            incidencies, fets = [], 0
            memoria = io.BytesIO()

            with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as z:
                for i, f in enumerate(seleccionades, 1):
                    rc = f["refcat"]
                    estat.write("Generant contracte {} de {}… ({})".format(
                        i, len(seleccionades), rc))
                    try:
                        ficha = obtenir_ficha(f, comunes)
                        ficha = fusiona(ficha, cedents.get(rc, {}), comunes)
                        z.writestr("contracte_cessio_caca_{}.pdf".format(rc),
                                   pdf_en_memoria(ficha))
                        fets += 1
                    except Exception as e:
                        incidencies.append((rc, "{}: {}".format(type(e).__name__, e)))
                    barra.progress(i / len(seleccionades))

            try:
                ca.guardar_cache()   # les respostes noves del Cadastre, desades
            except Exception:
                pass

            estat.write("Fet: {} {}.".format(
                plural(fets, "contracte", "contractes"),
                "generat" if fets == 1 else "generats"))
            st.session_state["zip_contractes"] = memoria.getvalue() if fets else None
            st.session_state["incidencies"] = incidencies
            st.session_state["fets"] = fets

        for rc, motiu in st.session_state["incidencies"]:
            st.warning("La parcel·la {} s'ha saltat: no s'ha pogut obtenir la fitxa "
                       "ni del disc ni del Cadastre. ({})".format(rc, motiu))

        if st.session_state["zip_contractes"]:
            st.success("{} a punt.".format(plural(
                st.session_state.get("fets", 0), "contracte", "contractes")))
            st.download_button(
                "Descarrega tots els contractes (.zip)",
                data=st.session_state["zip_contractes"],
                file_name="contractes_cessio_caca.zip",
                mime="application/zip", type="primary")

    _botons_nav(3)


# ---------------------------------------------------------------------------
# NAVEGACIÓ ENTRE PESTANYES VIA JS
# ---------------------------------------------------------------------------
if st.session_state.get("_nav_to") is not None:
    idx = st.session_state["_nav_to"]
    st.session_state["_nav_to"] = None
    st.markdown(f"""
<script>
(function() {{
    var tabs = window.parent.document.querySelectorAll('[data-testid="stTab"]');
    if (tabs && tabs.length > {idx}) {{ tabs[{idx}].click(); }}
}})();
</script>
""", unsafe_allow_html=True)
