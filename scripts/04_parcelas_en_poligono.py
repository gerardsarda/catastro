# -*- coding: utf-8 -*-
"""
04_parcelas_en_poligono.py
--------------------------
Responde a LA pregunta del punto 2: "¿que parcelas caen dentro del coto?"

La idea es sencilla:
  1) Tenemos el contorno del coto como una lista de puntos lat/lon (los que
     salen de Google Maps).
  2) Tenemos, en local, el GML INSPIRE del municipio: 1.909 parcelas CON su
     geometria completa. Esto NO hay que pedirselo a ninguna API.
  3) Cruzamos las dos cosas: para cada parcela miramos si su poligono TOCA el
     poligono del coto.

LA REGLA: si una parcela toca el poligono, aunque sea por un solo vertice,
entra ENTERA, con su superficie completa del Catastro. No se reparten
superficies ni se clasifica nada como "parcial": los derechos de caza se
ceden por finca, no por metros cuadrados.

No se inventa ni un dato: todo lo que sale aqui esta o en el GML del Catastro
o se calcula geometricamente a partir de el.

Uso:  python scripts/04_parcelas_en_poligono.py
"""

import csv
import glob
import json
import os
import re
import sys

from lxml import etree
from pyproj import Transformer
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---------------------------------------------------------------------------
# 1) EL CONTORNO DEL COTO
# ---------------------------------------------------------------------------
# Puntos tal cual salen de Google Maps: (latitud, longitud), en ese orden.
# IMPORTANTE: el orden de la lista es el orden en que se recorre el perimetro.
# Si dos puntos estan cambiados de sitio el poligono se cruza a si mismo y el
# calculo no vale. El script lo detecta y avisa (ver validacion mas abajo).
POLIGONO_COTO = [
    (41.304222, 1.239796),
    (41.323820, 1.191388),
    (41.345087, 1.215764),
    (41.374850, 1.270180),
    (41.358102, 1.290951),
    (41.318405, 1.276532),
]

# No hay umbrales. Tocar el poligono es la unica condicion: shapely lo
# resuelve con intersects(), que tambien es True cuando solo se comparte un
# vertice o un tramo de borde (contacto sin superficie en comun).


# ---------------------------------------------------------------------------
# 2) RUTAS
# ---------------------------------------------------------------------------
AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
# Directorio con los GML descomprimidos. El script coge TODOS los ficheros
# "*.cadastralparcel.gml" que encuentre, asi que para ampliar el coto a otro
# municipio basta con dejar ahi su .gml y volver a ejecutar. No hay que tocar
# codigo. El script 05 dice que municipios faltan.
DIR_GML = os.path.join(RAIZ, "datos_crudos", "gml")
SALIDA_CSV = os.path.join(RAIZ, "salidas", "parcelas_dentro_del_coto.csv")

# Espacios de nombres XML. Un GML usa prefijos (cp:, gml:) que en realidad son
# atajos de estas URLs. lxml necesita el diccionario para poder buscar.
NS = {
    "cp": "http://inspire.ec.europa.eu/schemas/cp/4.0",
    "gml": "http://www.opengis.net/gml/3.2",
    "wfs": "http://www.opengis.net/wfs/2.0",
}

# El GML del Catastro para Tarragona viene en EPSG:25831 = ETRS89 / UTM 31N.
# Son metros, no grados. Por eso podemos sumar superficies directamente.
CRS_GML = "EPSG:25831"
CRS_GPS = "EPSG:4326"  # lat/lon de toda la vida (lo que da Google Maps)


# ---------------------------------------------------------------------------
# 3) PASAR EL COTO DE LAT/LON A METROS
# ---------------------------------------------------------------------------
def construir_poligono_coto():
    """Convierte la lista de lat/lon en un poligono en coordenadas UTM (metros).

    always_xy=True le dice a pyproj: "yo te paso (x, y) = (lon, lat)".
    Sin eso, EPSG:4326 espera (lat, lon) y sale todo del reves. Es el error
    numero uno cuando se trabaja con proyecciones.
    """
    t = Transformer.from_crs(CRS_GPS, CRS_GML, always_xy=True)
    puntos_utm = [t.transform(lon, lat) for (lat, lon) in POLIGONO_COTO]
    poli = Polygon(puntos_utm)

    if not poli.is_valid:
        print("AVISO: el poligono del coto NO es valido (se cruza a si mismo).")
        print("       Revisa el ORDEN de los puntos. Intento repararlo...")
        # buffer(0) es el truco estandar para arreglar poligonos que se cruzan.
        poli = poli.buffer(0)
        if not poli.is_valid:
            raise SystemExit("No se ha podido reparar el poligono. Revisa los puntos.")

    return poli


# ---------------------------------------------------------------------------
# 4) LEER LAS PARCELAS DEL GML
# ---------------------------------------------------------------------------
def leer_poslist(texto):
    """'351843.5 4579312.8 351843.2 4579313.9' -> [(351843.5, 4579312.8), ...]

    En GML las coordenadas van todas seguidas en un solo string, separadas por
    espacios: x1 y1 x2 y2 x3 y3... Hay que trocearlas de dos en dos.
    """
    n = [float(v) for v in texto.split()]
    return list(zip(n[0::2], n[1::2]))


def geometria_de_parcela(nodo):
    """Saca la geometria de un <cp:CadastralParcel> como poligono de shapely.

    Una parcela puede ser:
      - un solo recinto (lo normal),
      - varios recintos separados (una finca en dos trozos),
      - un recinto con agujeros (p.ej. una balsa o un camino que la atraviesa).
    Por eso recorremos TODOS los <gml:PolygonPatch> y dentro de cada uno
    distinguimos el contorno exterior (<gml:exterior>) de los agujeros
    (<gml:interior>).
    """
    trozos = []
    for patch in nodo.iterfind(".//gml:PolygonPatch", NS):
        ext = patch.find("./gml:exterior//gml:posList", NS)
        if ext is None:
            continue
        exterior = leer_poslist(ext.text)
        if len(exterior) < 4:
            continue  # un poligono necesita minimo 3 vertices + el de cierre
        agujeros = [
            leer_poslist(pl.text)
            for pl in patch.iterfind("./gml:interior//gml:posList", NS)
        ]
        agujeros = [a for a in agujeros if len(a) >= 4]
        p = Polygon(exterior, agujeros)
        if not p.is_valid:
            p = p.buffer(0)  # mismo truco de reparacion
        if not p.is_empty:
            trozos.append(p)

    if not trozos:
        return None
    if len(trozos) == 1:
        return trozos[0]
    return unary_union(trozos)


def es_rustica(refcat):
    """43060A00600107 -> rustica.  000200100CF57G -> urbana.

    Las rusticas tienen el formato: 5 digitos (provincia+municipio), una letra
    de seccion, 3 de poligono y 5 de parcela.
    """
    return bool(re.match(r"^\d{5}[A-Z]\d{8}$", refcat or ""))


def codigo_municipio_de_fichero(ruta):
    """A.ES.SDGC.CP.43060.cadastralparcel.gml -> '43060'.

    Lo sacamos del NOMBRE del fichero y no de la referencia catastral porque
    en las parcelas urbanas los primeros digitos de la referencia no son el
    municipio (son la cuadricula cartografica). El fichero, en cambio, es de
    un municipio y solo uno.
    """
    m = re.search(r"\.(\d{5})\.cadastralparcel\.gml$", os.path.basename(ruta))
    return m.group(1) if m else "?????"


def cargar_parcelas():
    """Devuelve una lista de dicts, UNO POR REFERENCIA CATASTRAL.

    Ojo con esto, que es una trampa del formato: una parcela partida en varios
    trozos no aparece como un registro con varios recintos, sino como VARIOS
    registros <cp:CadastralParcel> con la MISMA referencia catastral, cada uno
    con su trozo y su propia superficie. En el fichero de 43060 pasa con 4
    referencias (10 registros -> 4 parcelas reales).

    Si no se agrupan, esas parcelas generarian fichas duplicadas y la
    superficie saldria contada varias veces. Asi que agrupamos por refcat:
    unimos las geometrias y sumamos las superficies.
    """
    ficheros = sorted(glob.glob(os.path.join(DIR_GML, "*.cadastralparcel.gml")))
    if not ficheros:
        raise SystemExit(
            "No hay ningun GML en {}. "
            "Descomprime ahi los .zip de datos_crudos/ (o ejecuta el script 07).".format(DIR_GML))

    registros = 0
    por_refcat = {}
    for ruta in ficheros:
        cod_muni = codigo_municipio_de_fichero(ruta)
        raiz = etree.parse(ruta).getroot()
        n_antes = registros
        for nodo in raiz.iterfind(".//cp:CadastralParcel", NS):
            refcat = (nodo.findtext("cp:nationalCadastralReference", namespaces=NS) or "").strip()
            area_txt = nodo.findtext("cp:areaValue", namespaces=NS)
            geom = geometria_de_parcela(nodo)
            if geom is None:
                continue
            registros += 1
            d = por_refcat.setdefault(refcat, {"refcat": refcat, "area_catastro_m2": 0,
                                               "cod_muni": cod_muni,
                                               "trozos": [], "n_trozos": 0})
        # areaValue = superficie oficial que declara el Catastro, en m2.
        # geom.area = superficie que sale de medir el dibujo. Suelen coincidir
        # casi exactamente, pero NO son el mismo dato: guardamos las dos y no
        # las mezclamos.
            if area_txt and area_txt.isdigit():
                d["area_catastro_m2"] += int(area_txt)
            d["trozos"].append(geom)
            d["n_trozos"] += 1
        print("  {}  municipio {}  ->  {} registros".format(
            os.path.basename(ruta), cod_muni, registros - n_antes))

    parcelas = []
    for d in por_refcat.values():
        d["geom"] = d["trozos"][0] if len(d["trozos"]) == 1 else unary_union(d["trozos"])
        del d["trozos"]
        parcelas.append(d)

    print("Registros leidos en total     :", registros)
    print("Parcelas reales (refcat unica):", len(parcelas))
    multi = [p["refcat"] for p in parcelas if p["n_trozos"] > 1]
    if multi:
        # Solo enseñamos una muestra: en 4 municipios son casi 800 y llenarian
        # la pantalla. La lista completa va en el CSV, columna n_trozos.
        muestra = ", ".join(multi[:6])
        resto = " (+{} mas)".format(len(multi) - 6) if len(multi) > 6 else ""
        print("Parcelas en varios trozos     : {} -> {}{}".format(len(multi), muestra, resto))
    return parcelas


# ---------------------------------------------------------------------------
# 4bis) EXPORTAR A GEOJSON PARA VERIFICAR A OJO
# ---------------------------------------------------------------------------
def _anillos_a_wgs84(poli, t_inv):
    """Pasa los anillos de un poligono de UTM a lat/lon en formato GeoJSON."""
    anillos = [list(poli.exterior.coords)] + [list(r.coords) for r in poli.interiors]
    return [[list(t_inv.transform(x, y)) for (x, y) in anillo] for anillo in anillos]


def _a_geometria_geojson(geom, t_inv):
    """GeoJSON solo entiende Polygon y MultiPolygon; shapely puede darnos ambos."""
    if geom.geom_type == "Polygon":
        return {"type": "Polygon", "coordinates": _anillos_a_wgs84(geom, t_inv)}
    return {"type": "MultiPolygon",
            "coordinates": [_anillos_a_wgs84(p, t_inv) for p in geom.geoms]}


def escribir_geojson(coto, parcelas, filas, t_inv):
    """Escribe dos ficheros: el contorno del coto y las parcelas seleccionadas."""
    ruta_coto = os.path.join(RAIZ, "salidas", "coto.geojson")
    with open(ruta_coto, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": [
            {"type": "Feature",
             "properties": {"nombre": "contorno del coto", "hectareas": round(coto.area / 10000, 1)},
             "geometry": _a_geometria_geojson(coto, t_inv)}
        ]}, fh, ensure_ascii=False)

    # Indice refcat -> geometria, para no volver a recorrer la lista por cada fila.
    geoms = {p["refcat"]: p["geom"] for p in parcelas}
    ruta_parc = os.path.join(RAIZ, "salidas", "parcelas_dentro_del_coto.geojson")
    with open(ruta_parc, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": [
            {"type": "Feature",
             "properties": {k: v for k, v in f.items() if k != "url_cartografia"},
             "geometry": _a_geometria_geojson(geoms[f["refcat"]], t_inv)}
            for f in filas
        ]}, fh, ensure_ascii=False)

    print("\nGeoJSON para verificar en https://geojson.io :")
    print("  ", ruta_coto)
    print("  ", ruta_parc)


# ---------------------------------------------------------------------------
# 5) EL CRUCE
# ---------------------------------------------------------------------------
def main():
    coto = construir_poligono_coto()
    print("Superficie del poligono del coto: {:,.1f} ha".format(coto.area / 10000).replace(",", "."))

    parcelas = cargar_parcelas()

    # Extension del municipio segun el propio GML. Sirve para comprobar si el
    # coto se sale del municipio (y por tanto si faltan mas ficheros GML).
    municipio = unary_union([p["geom"] for p in parcelas])
    print("Superficie cubierta por el GML del municipio: {:,.1f} ha"
          .format(municipio.area / 10000).replace(",", "."))

    fuera = coto.difference(municipio)
    pct_fuera = (fuera.area / coto.area) * 100 if coto.area else 0
    print("Parte del coto que NO cubre este GML: {:.1f} %  ({:,.1f} ha)"
          .format(pct_fuera, fuera.area / 10000).replace(",", "."))

    # Para pasar el centroide de vuelta a lat/lon (para los enlaces y Maps).
    t_inv = Transformer.from_crs(CRS_GML, CRS_GPS, always_xy=True)

    filas = []
    for p in parcelas:
        g = p["geom"]
        # intersects() incluye el contacto por el borde o por un solo punto.
        # Es justo lo que queremos: si se tocan, la parcela entra.
        if not g.intersects(coto):
            continue

        # Superficie que se le imputa a la finca: la OFICIAL del Catastro
        # (areaValue del GML). Solo si el GML no la trae usamos la del dibujo,
        # que es la misma cifra con decimas de diferencia.
        area_computada = p["area_catastro_m2"] or round(g.area)

        c = g.centroid
        lon, lat = t_inv.transform(c.x, c.y)

        filas.append({
            "refcat": p["refcat"],
            "cod_muni": p["cod_muni"],
            "tipo": "rustica" if es_rustica(p["refcat"]) else "urbana",
            "area_catastro_m2": p["area_catastro_m2"] if p["area_catastro_m2"] is not None else "",
            "area_geometria_m2": round(g.area),
            "area_computada_m2": area_computada,
            "n_trozos": p["n_trozos"],
            "centroide_lat": round(lat, 6),
            "centroide_lon": round(lon, 6),
            # del = provincia, mun = codigo de municipio SEGUN CATASTRO (no el
            # del INE). Los dos salen del codigo de 5 cifras del fichero GML.
            "url_cartografia": ("https://www1.sedecatastro.gob.es/Cartografia/mapa.aspx"
                                "?del={}&mun={}&refcat={}".format(
                                    p["cod_muni"][:2], int(p["cod_muni"][2:]), p["refcat"])),
        })

    # Todas entran igual, asi que basta ordenar de mayor a menor superficie.
    filas.sort(key=lambda f: -f["area_computada_m2"])

    os.makedirs(os.path.dirname(SALIDA_CSV), exist_ok=True)
    campos = ["refcat", "cod_muni", "tipo", "area_catastro_m2", "area_geometria_m2",
              "area_computada_m2", "n_trozos", "centroide_lat", "centroide_lon",
              "url_cartografia"]
    # utf-8-sig = UTF-8 con BOM. Es lo que necesita Excel en Windows para no
    # destrozar los acentos al abrir el CSV de doble clic.
    with open(SALIDA_CSV, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=campos, delimiter=";")
        w.writeheader()
        w.writerows(filas)

    # --- GeoJSON para poder MIRARLO en un mapa ---
    # Esto no es adorno: es la unica forma de comprobar a ojo que el poligono
    # que hemos dibujado es el coto de verdad y no un triangulo raro. Se
    # arrastra el fichero a https://geojson.io y se ve al momento.
    escribir_geojson(coto, parcelas, filas, t_inv)

    # --- Resumen por pantalla ---
    n_rus = sum(1 for f in filas if f["tipo"] == "rustica")
    sup = sum(f["area_computada_m2"] for f in filas)

    print("\n" + "=" * 70)
    print("RESULTADO")
    print("=" * 70)
    print("Parcelas que tocan el coto : {}  (todas entran enteras)".format(len(filas)))
    print("  - rusticas / urbanas     : {} / {}".format(n_rus, len(filas) - n_rus))
    print("Superficie total cedida    : {:,.2f} ha".format(sup / 10000).replace(",", "."))
    print("  (suma de la superficie catastral de cada finca; es mayor que el area")
    print("   del poligono porque las del borde entran enteras)")
    print("\nCSV escrito en:", SALIDA_CSV)


if __name__ == "__main__":
    main()
