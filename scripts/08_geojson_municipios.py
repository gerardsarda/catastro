# -*- coding: utf-8 -*-
"""
08_geojson_municipios.py
------------------------
Vuelca TODAS las parcelas de los GML que hay en datos_crudos/gml/ a un unico
GeoJSON, sin filtrar por ningun coto.

Para que sirve: hasta ahora el unico GeoJSON que se generaba era el de las
parcelas de UN coto concreto (lo escribe el script 04). Este es la capa base:
el mapa cadastral completo de los municipios descargados, para poder mirarlo
en QGIS o en https://geojson.io, dibujar el poligono encima y comprobar a ojo
que finca toca cual. El poligono del coto no interviene aqui para nada.

Que lleva cada parcela (nada inventado, todo sale del GML):
  refcat          referencia catastral
  municipio       codigo de municipio DEL CATASTRO (5 cifras, del nombre del GML)
  tipo            rustica / urbana
  superficie_m2   la OFICIAL del Catastro (areaValue). Es la que cuenta.
  superficie_ha   la misma, en hectareas
  area_dibujo_m2  la que sale de medir la geometria (para contrastar)
  n_trozos        recintos separados con la misma referencia catastral
  url_cartografia enlace a la ficha cartografica de la Sede

Uso:
  python scripts/08_geojson_municipios.py                 (un solo fichero)
  python scripts/08_geojson_municipios.py --por-municipio (uno por municipio)
  python scripts/08_geojson_municipios.py --solo-rusticas
"""

import argparse
import importlib.util
import json
import os
import sys

from pyproj import Transformer

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

DIR_SALIDAS = os.path.join(RAIZ, "salidas")
SALIDA = os.path.join(DIR_SALIDAS, "parcelas_todos_los_municipios.geojson")

# Decimales de las coordenadas de salida. 6 decimales de grado son ~11 cm en
# latitud: mas que suficiente para una parcela, y con 7 el fichero engorda un
# 15% sin ganar nada.
DECIMALES = 6


def anillos_a_wgs84(poli, t_inv):
    anillos = [list(poli.exterior.coords)] + [list(r.coords) for r in poli.interiors]
    return [[[round(v, DECIMALES) for v in t_inv.transform(x, y)] for (x, y) in a]
            for a in anillos]


def geometria_geojson(geom, t_inv):
    """GeoJSON solo entiende Polygon y MultiPolygon; shapely puede dar ambos."""
    if geom.geom_type == "Polygon":
        return {"type": "Polygon", "coordinates": anillos_a_wgs84(geom, t_inv)}
    return {"type": "MultiPolygon",
            "coordinates": [anillos_a_wgs84(p, t_inv) for p in geom.geoms]}


def feature(p, t_inv):
    # La superficie que cuenta es la oficial del Catastro. Si el GML no la
    # trae (pasa en muy pocas), caemos en la del dibujo, que es la misma
    # cifra con decimas de diferencia.
    superficie = p["area_catastro_m2"] or round(p["geom"].area)
    c = p["geom"].centroid
    lon, lat = t_inv.transform(c.x, c.y)
    return {
        "type": "Feature",
        "properties": {
            "refcat": p["refcat"],
            "municipio": p["cod_muni"],
            "tipo": "rustica" if s04.es_rustica(p["refcat"]) else "urbana",
            "superficie_m2": superficie,
            "superficie_ha": round(superficie / 10000, 4),
            "area_dibujo_m2": round(p["geom"].area),
            "n_trozos": p["n_trozos"],
            "centroide_lat": round(lat, 6),
            "centroide_lon": round(lon, 6),
            "url_cartografia": ("https://www1.sedecatastro.gob.es/Cartografia/mapa.aspx"
                                "?del={}&mun={}&refcat={}".format(
                                    p["cod_muni"][:2], int(p["cod_muni"][2:]), p["refcat"])),
        },
        "geometry": geometria_geojson(p["geom"], t_inv),
    }


def ha(m2):
    """1234567 m2 -> '123,5' ha, con el punto de miles y la coma decimal.

    Se hace en dos pasos porque format() da el formato ingles (123,456.7) y
    aqui hace falta el de casa (123.456,7): primero se marcan los separadores
    con un caracter que no puede salir, y luego se cambian por los buenos.
    """
    return "{:,.1f}".format(m2 / 10000).replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def escribir(ruta, features):
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features},
                  fh, ensure_ascii=False, separators=(",", ":"))
    print("  {}  ->  {} parcelas, {:.1f} MB".format(
        os.path.basename(ruta), len(features), os.path.getsize(ruta) / 1048576))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--por-municipio", action="store_true",
                    help="un fichero por municipio en vez de uno solo")
    ap.add_argument("--solo-rusticas", action="store_true",
                    help="excluye las parcelas urbanas")
    args = ap.parse_args()

    parcelas = s04.cargar_parcelas()
    if args.solo_rusticas:
        antes = len(parcelas)
        parcelas = [p for p in parcelas if s04.es_rustica(p["refcat"])]
        print("Filtro --solo-rusticas: {} de {} parcelas.".format(len(parcelas), antes))

    t_inv = Transformer.from_crs(s04.CRS_GML, s04.CRS_GPS, always_xy=True)
    os.makedirs(DIR_SALIDAS, exist_ok=True)

    print("\nEscribiendo GeoJSON (EPSG:4326, lat/lon):")
    if args.por_municipio:
        por_muni = {}
        for p in parcelas:
            por_muni.setdefault(p["cod_muni"], []).append(p)
        for cod in sorted(por_muni):
            escribir(os.path.join(DIR_SALIDAS, "parcelas_{}.geojson".format(cod)),
                     [feature(p, t_inv) for p in por_muni[cod]])
    else:
        escribir(SALIDA, [feature(p, t_inv) for p in parcelas])

    # Un resumen por municipio para poder cuadrar cifras de un vistazo.
    print("\nPor municipio:")
    resumen = {}
    for p in parcelas:
        r = resumen.setdefault(p["cod_muni"], {"n": 0, "m2": 0})
        r["n"] += 1
        r["m2"] += p["area_catastro_m2"] or round(p["geom"].area)
    for cod in sorted(resumen):
        r = resumen[cod]
        print("  {}  {:>6} parcelas  {:>12} ha".format(cod, r["n"], ha(r["m2"])))
    total_m2 = sum(r["m2"] for r in resumen.values())
    print("  {:>5}  {:>6} parcelas  {:>12} ha".format(
        "TOTAL", sum(r["n"] for r in resumen.values()), ha(total_m2)))


if __name__ == "__main__":
    main()
