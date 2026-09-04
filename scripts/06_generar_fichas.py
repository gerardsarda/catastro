# -*- coding: utf-8 -*-
"""
06_generar_fichas.py
--------------------
Genera UNA ficha JSON por parcela, que es lo que pide el cliente. Cada ficha
es la entrada del script 03, que la convierte en el PDF del contrato.

De donde sale cada cosa:

  FONT: CATASTRO (GML)      -> superficie y geometria, ya en local.
  FONT: CATASTRO (DNPRC)    -> municipio, paraje, poligono, parcela, uso y
                               cultivos. Se pide por API, una vez por parcela,
                               y se cachea.
  FONT: CALCULAT            -> los LINDEROS. El Catastro no los da en texto,
                               pero si tenemos la geometria de todas las
                               parcelas del municipio podemos mirar cuales
                               tocan a esta y por que lado. Eso si se puede.
  FONT: MANUAL              -> lo que no esta en ninguna fuente publica:
                               el propietario, y los datos del contrato.
                               Se quedan VACIOS. No se rellenan a ojo.

Lo que NO se puede sacar y hay que asumir: el NOMBRE del propietario. El
Catastro no lo publica (Ley del Catastro, art. 51: los datos protegidos solo
se dan al titular o a quien acredite interes legitimo). Por eso los linderos
salen identificados por referencia catastral y no por nombre.

Uso:
  python scripts/06_generar_fichas.py --limite 5          (prueba)
  python scripts/06_generar_fichas.py --solo-rusticas     (las de verdad)
  python scripts/06_generar_fichas.py                     (todas)
"""

import argparse
import csv
import importlib.util
import json
import math
import os
import sys

from shapely import STRtree

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)

_spec = importlib.util.spec_from_file_location(
    "s04", os.path.join(AQUI, "04_parcelas_en_poligono.py"))
s04 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s04)

import catastro_api as ca

CSV_SELECCION = os.path.join(RAIZ, "salidas", "parcelas_dentro_del_coto.csv")
DIR_FICHAS = os.path.join(RAIZ, "datos", "fichas")
COMUNES = os.path.join(RAIZ, "datos", "dades_comunes.json")
VOCABULARIO = os.path.join(RAIZ, "datos", "vocabulari_catastro.json")
COMARQUES = os.path.join(RAIZ, "datos", "comarques.json")


def carregar_comarques():
    """Codi Catastro municipi -> comarca. El Cadastre no dona la comarca."""
    with open(COMARQUES, encoding="utf-8") as fh:
        d = json.load(fh)
    return {k: v["comarca"] for k, v in d.items() if k != "_comentari"}

# Dos parcelas se consideran vecinas si sus bordes estan a menos de esto.
# No usamos "que se toquen exactamente" porque la cartografia catastral tiene
# decimas de metro de holgura entre poligonos vecinos y con tolerancia cero
# casi ninguna parcela tendria linderos.
TOLERANCIA_VECINO_M = 0.5

# Un vecino que comparte 20 cm de borde no es un lindero, es un roce en una
# esquina. Pedimos un minimo de linde compartida para que cuente.
MIN_LINDE_M = 1.0


# ---------------------------------------------------------------------------
# LINDEROS
# ---------------------------------------------------------------------------
def orientacion(dx, dy):
    """Convierte un vector en un punto cardinal: 'nord', 'sud', 'est' u 'oest'.

    atan2 devuelve el angulo del vector en radianes. Lo pasamos a grados
    medidos desde el Norte y en sentido horario (que es como se leen los
    rumbos), y partimos la rosa en cuatro cuadrantes de 90 grados.

    Trabajamos en UTM, donde +y es el norte de la cuadricula. No es
    exactamente el norte geografico (hay una desviacion de decimas de grado),
    pero para decir "linda al norte con" sobra.
    """
    grados = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    if grados < 45 or grados >= 315:
        return "nord"
    if grados < 135:
        return "est"
    if grados < 225:
        return "sud"
    return "oest"


def calcular_linderos(geom, arbol, todas):
    """Devuelve {'nord': [refcat, ...], 'sud': [...], 'est': [...], 'oest': [...]}.

    Como funciona:
      1) El indice espacial (STRtree) nos da rapidamente las parcelas cuyo
         rectangulo envolvente esta cerca. Sin indice habria que comparar cada
         parcela con las 29.000 restantes: inviable.
      2) De esas candidatas nos quedamos con las que comparten borde de verdad
         (mas de MIN_LINDE_M metros).
      3) La direccion se calcula del centro de ESTA parcela al centro del
         tramo de borde compartido. Ese es el lado por el que linda.
    """
    linderos = {"nord": [], "sud": [], "est": [], "oest": []}

    zona = geom.buffer(TOLERANCIA_VECINO_M)
    for idx in arbol.query(zona):
        vecina = todas[idx]
        if vecina["geom"].equals(geom):
            continue
        # El borde compartido: lo que queda del vecino dentro de nuestra
        # franja de tolerancia, intersecado con nuestro propio contorno.
        compartido = vecina["geom"].buffer(TOLERANCIA_VECINO_M).intersection(geom.exterior)
        if compartido.is_empty or compartido.length < MIN_LINDE_M:
            continue
        c = geom.centroid
        m = compartido.centroid
        linderos[orientacion(m.x - c.x, m.y - c.y)].append(vecina["refcat"])

    return linderos


# ---------------------------------------------------------------------------
# FICHA
# ---------------------------------------------------------------------------
def cargar_comunes():
    """Datos iguales para todos los contratos (cesionaria, coto, condiciones).

    Estan en un solo fichero a proposito: se revisan UNA vez y valen para las
    3.500 fichas. Si no existe, se crea vacio para que se vea que falta.
    """
    if os.path.exists(COMUNES):
        with open(COMUNES, "r", encoding="utf-8") as fh:
            return json.load(fh)
    print("AVISO: no existe {}. Las fichas saldran sin los datos comunes."
          .format(os.path.relpath(COMUNES, RAIZ)))
    return {}


def construir_ficha(fila, datos_cat, linderos, comunes, comarques):
    """Monta el dict de la ficha. Lo que no se sabe va a cadena vacia."""
    cultivos = datos_cat.get("cultivos") or []

    # Una parcela puede tener 8 subparcelas y que 4 sean 'IMPRODUCTIVO'. Para
    # el resumen queremos la lista de tipos DISTINTOS, en el orden en que
    # aparecen; el detalle con las superficies de cada una va aparte.
    vistos, tipos = set(), []
    for c in cultivos:
        if c["cultivo"] not in vistos:
            vistos.add(c["cultivo"])
            tipos.append(c["cultivo"])

    # Superficie de la finca. La primera fuente es el DNPRC; cuando no la da
    # (pasa en urbanas) usamos la del GML, que es igual de oficial: es el
    # areaValue del propio Catastro, ya calculado en la fila del script 04.
    # Sin esto el contrato saldria con 0 m2 teniendo el dato a mano.
    superficie = datos_cat.get("superficie_catastro_m2") or int(fila["area_computada_m2"])

    ficha = {
        "_comentari": ("Generada per 06_generar_fichas.py. Els camps FONT:CATASTRO i "
                       "FONT:CALCULAT venen de dades oficials. Els FONT:MANUAL estan "
                       "buits a proposit: no hi ha cap font publica que els doni."),

        "finca": {
            "_font": "CATASTRO (GML INSPIRE + Consulta_DNPRC)",
            "referencia_cadastral": fila["refcat"],
            # El paraje del Catastro es lo mas parecido a un "nombre de finca"
            # que existe en una fuente oficial. Si el Catastro pone 'NC' (no
            # consta), aqui queda vacio. No nos lo inventamos.
            "nom_finca": datos_cat.get("paraje") or "",
            "terme_municipal": datos_cat.get("municipio") or "",
            "comarca": comarques.get(fila.get("cod_muni", ""), ""),
            "provincia": datos_cat.get("provincia") or "",
            "poligon": datos_cat.get("poligono") or "",
            "parcela": datos_cat.get("parcela") or "",
            "us_catastro": datos_cat.get("uso") or "",
            "conreus_catastro": tipos,
            "detall_conreus": cultivos,
            "superficie_m2": superficie,
            "superficie_ha": "{:.4f}".format(superficie / 10000).replace(".", ","),
            "descripcio_catastro": datos_cat.get("descripcion_catastro") or "",
            "enllac_cartografia": datos_cat.get("url_cartografia") or fila.get("url_cartografia", ""),
        },

        # La finca toca el poligon del vedat, i per tant hi entra SENCERA: la
        # superficie que compta es la catastral completa, la mateixa que surt
        # al bloc "finca". No es reparteix res ni hi ha percentatges: els
        # drets de caca es cedeixen per finca, no per metres quadrats.
        "situacio_dins_el_coto": {
            "_font": "CALCULAT (la geometria de la finca toca el poligon del vedat)",
            "inclosa_sencera": True,
            "superficie_computada_m2": int(fila["area_computada_m2"]),
            "centroide_lat": float(fila["centroide_lat"]),
            "centroide_lon": float(fila["centroide_lon"]),
        },

        "limits": {
            "_font": ("CALCULAT (parcel-les veines segons la geometria del Catastro). "
                      "S'identifiquen per referencia cadastral: el nom del propietari "
                      "no es public."),
            "nord": linderos["nord"],
            "sud": linderos["sud"],
            "est": linderos["est"],
            "oest": linderos["oest"],
        },

        "cedent": {
            "_font": "MANUAL (el Catastro no publica la titularitat)",
            "nom": "",
            "tipus_document": "",
            "adreca": "",
        },
    }

    # Los bloques comunes (cesionaria, coto, condiciones) se copian tal cual
    # del fichero de datos comunes.
    for clau in ("cessionaria", "coto", "condicions"):
        if clau in comunes:
            ficha[clau] = comunes[clau]

    return ficha


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=0, help="procesa solo N parcelas (para probar)")
    ap.add_argument("--solo-rusticas", action="store_true", help="excluye las urbanas")
    args = ap.parse_args()

    if not os.path.exists(CSV_SELECCION):
        raise SystemExit("Falta {}. Ejecuta antes el script 04.".format(CSV_SELECCION))

    with open(CSV_SELECCION, "r", encoding="utf-8-sig") as fh:
        filas = list(csv.DictReader(fh, delimiter=";"))

    if args.solo_rusticas:
        filas = [f for f in filas if f["tipo"] == "rustica"]
    if args.limite:
        filas = filas[:args.limite]

    print("Fichas a generar:", len(filas))

    # Indice espacial sobre TODAS las parcelas, no solo las del coto: un
    # lindero puede ser una parcela de fuera.
    todas = s04.cargar_parcelas()
    arbol = STRtree([p["geom"] for p in todas])
    print("Indice espacial construido sobre {} parcelas.".format(len(todas)))

    comunes = cargar_comunes()
    comarques = carregar_comarques()
    os.makedirs(DIR_FICHAS, exist_ok=True)

    por_refcat = {p["refcat"]: p for p in todas}
    vocabulario = {"usos": {}, "conreus": {}}
    fallos = []
    hechas = 0

    for i, fila in enumerate(filas, 1):
        rc = fila["refcat"]
        p = por_refcat.get(rc)
        if p is None:
            fallos.append((rc, "no esta en el GML"))
            continue

        try:
            datos_cat = ca.datos_de_parcela(rc)
        except Exception as e:
            fallos.append((rc, "DNPRC " + type(e).__name__))
            datos_cat = None
        if datos_cat is None:
            datos_cat = {}

        linderos = calcular_linderos(p["geom"], arbol, todas)
        ficha = construir_ficha(fila, datos_cat, linderos, comunes, comarques)

        # Vamos juntando el vocabulario del Catastro para poder traducirlo
        # despues de una sola vez (ver mas abajo).
        if datos_cat.get("uso"):
            vocabulario["usos"].setdefault(datos_cat["uso"], "")
        for c in datos_cat.get("cultivos") or []:
            vocabulario["conreus"].setdefault(c["cultivo"], "")

        destino = os.path.join(DIR_FICHAS, "finca_{}.json".format(rc))
        with open(destino, "w", encoding="utf-8") as fh:
            json.dump(ficha, fh, ensure_ascii=False, indent=2)
        hechas += 1

        if i % 50 == 0:
            print("  ... {}/{}   (cache DNPRC: {})".format(i, len(filas), ca.cuantas_cacheadas()))
            ca.guardar_cache()

    ca.guardar_cache()

    # El Catastro contesta en castellano ('ALMENDRO REGADIO', 'Agrario') y el
    # contrato va en catalan. Traducirlo a ojo parcela a parcela es pedir un
    # error; y que lo haga el script por su cuenta seria inventarse texto que
    # acaba en un contrato firmado. Asi que dejamos aqui la lista de terminos
    # DISTINTOS que han salido -son pocos- para que se traduzcan una sola vez
    # y con criterio. El script 03 usara la traduccion si existe.
    if os.path.exists(VOCABULARIO):
        with open(VOCABULARIO, "r", encoding="utf-8") as fh:
            previo = json.load(fh)
        for bloque in ("usos", "conreus"):
            for k, v in (previo.get(bloque) or {}).items():
                if v:
                    vocabulario[bloque][k] = v  # respetamos lo ya traducido
    with open(VOCABULARIO, "w", encoding="utf-8") as fh:
        json.dump(vocabulario, fh, ensure_ascii=False, indent=2, sort_keys=True)

    print("\n" + "=" * 70)
    print("Fichas escritas : {} en {}".format(hechas, os.path.relpath(DIR_FICHAS, RAIZ)))
    pendientes = sum(1 for v in vocabulario["conreus"].values() if not v) + \
                 sum(1 for v in vocabulario["usos"].values() if not v)
    print("Vocabulario     : {} termes ({} sense traduir) en {}".format(
        len(vocabulario["usos"]) + len(vocabulario["conreus"]), pendientes,
        os.path.relpath(VOCABULARIO, RAIZ)))
    if fallos:
        print("Incidencias     : {}".format(len(fallos)))
        for rc, motivo in fallos[:10]:
            print("   {}  {}".format(rc, motivo))


if __name__ == "__main__":
    main()
