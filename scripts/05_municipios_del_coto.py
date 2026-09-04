# -*- coding: utf-8 -*-
"""
05_municipios_del_coto.py
-------------------------
El script 04 ha descubierto que una buena parte del coto cae FUERA del
municipio 43060, o sea que con el GML que tenemos no basta.

Este script averigua QUE municipios son. No lo deduce ni se lo inventa:
siembra la zona no cubierta de puntos y le pregunta al Catastro, punto por
punto, "que hay aqui". El servicio Consulta_RCCOOR devuelve la referencia
catastral y el municipio de cada coordenada.

Con la lista de municipios ya se pueden bajar los GML que faltan desde:
  https://www.catastro.hacienda.gob.es/INSPIRE/CadastralParcels/ES.SDGC.CP.atom.xml

Uso:  python scripts/05_municipios_del_coto.py
"""

import importlib.util
import json
import os
import re
import sys
import time
from collections import Counter

import requests
from lxml import etree
from shapely.geometry import Point
from shapely.ops import unary_union

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)

# El script 04 se llama "04_..." y Python no deja hacer "import 04_..." porque
# un nombre no puede empezar por numero. importlib carga el fichero a mano y
# asi reaprovechamos sus funciones sin copiarlas.
_spec = importlib.util.spec_from_file_location(
    "s04", os.path.join(AQUI, "04_parcelas_en_poligono.py"))
s04 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s04)

import catastro_api as ca  # cliente comun del Catastro (mismo directorio)


# ---------------------------------------------------------------------------
# CONFIGURACION DEL MUESTREO
# ---------------------------------------------------------------------------
# Distancia entre puntos de la rejilla, en metros. 500 m es suficiente para
# detectar cualquier municipio que aporte algo de superficie al coto, sin
# lanzar miles de peticiones. Bajalo si sospechas que falta alguno pequeno.
PASO_M = 500

# Pausa entre peticiones. El servicio del Catastro es publico y gratuito;
# machacarlo a saco es la forma mas rapida de que te corten. Vamos despacio.
PAUSA_S = 0.35

URL_RCCOOR = ("https://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/"
              "OVCCoordenadas.asmx/Consulta_RCCOOR")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "*/*",
}

NS_C = {"c": "http://www.catastro.meh.es/"}


# Cache en disco: clave "lat,lon" -> [refcat, descripcion].
# Cada peticion al Catastro tarda y consume su ancho de banda, y la respuesta
# para una coordenada no cambia de un dia para otro. Guardandola, la segunda
# vez que ejecutas el script es instantanea y gratis.
CACHE_PATH = os.path.join(RAIZ, "datos_crudos", "cache_rccoor.json")
_cache = {}


def cargar_cache():
    global _cache
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as fh:
            _cache = json.load(fh)
    print("Respuestas ya cacheadas:", len(_cache))


def guardar_cache():
    with open(CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(_cache, fh, ensure_ascii=False, indent=1)


def consultar_punto(lat, lon):
    """Pregunta al Catastro que parcela hay en esa coordenada.

    Devuelve (refcat, descripcion) o (None, motivo) si ahi no hay nada
    (por ejemplo si el punto cae en el mar, en un rio o fuera de territorio
    con catastro propio).
    """
    clave = "{:.6f},{:.6f}".format(lat, lon)
    if clave in _cache:
        r = _cache[clave]
        return r[0], r[1]

    params = {"SRS": "EPSG:4326", "Coordenada_X": "{:.6f}".format(lon),
              "Coordenada_Y": "{:.6f}".format(lat)}
    r = requests.get(URL_RCCOOR, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()

    # El servidor manda XML. lxml necesita los BYTES, no el texto ya decodificado:
    # si le pasamos r.text, se pelea con la declaracion de encoding del propio XML.
    raiz = etree.fromstring(r.content)

    # cuerr > 0 significa que el propio Catastro reporta un error controlado
    # (normalmente "no hay parcela en esa coordenada").
    err = raiz.findtext(".//c:control/c:cuerr", namespaces=NS_C)
    if err and err != "0":
        motivo = (raiz.findtext(".//c:err/c:des", namespaces=NS_C) or "sin parcela").strip()
        _cache[clave] = [None, motivo]
        return None, motivo

    pc1 = raiz.findtext(".//c:pc/c:pc1", namespaces=NS_C) or ""
    pc2 = raiz.findtext(".//c:pc/c:pc2", namespaces=NS_C) or ""
    ldt = (raiz.findtext(".//c:ldt", namespaces=NS_C) or "").strip()
    if not pc1:
        _cache[clave] = [None, "sin parcela"]
        return None, "sin parcela"
    _cache[clave] = [pc1 + pc2, ldt]
    return pc1 + pc2, ldt


def municipio_de_refcat(refcat):
    """Devuelve (codigo5, nombre) del municipio de una referencia catastral.

    Aqui NO vale sacar el codigo de los primeros digitos de la referencia:
    eso solo funciona en las rusticas (43060A00600107 -> 43060). En las
    urbanas los primeros digitos son la cuadricula cartografica y dan un
    codigo falso. Tampoco vale leer el municipio del texto 'ldt', porque en
    las urbanas va pegado a la direccion ('CL BLANQUERS 71 VALLS') y no hay
    forma fiable de saber donde acaba la calle y empieza el pueblo.

    Se lo pedimos estructurado al Catastro a traves de catastro_api, que ya
    sabe leer las dos formas de respuesta que devuelve el servicio.
    """
    d = ca.datos_de_parcela(refcat)
    if not d or not d["codigo_municipio_gml"]:
        return None
    return d["codigo_municipio_gml"], d["municipio"]


def main():
    cargar_cache()
    coto = s04.construir_poligono_coto()
    parcelas = s04.cargar_parcelas()
    cubierto = unary_union([p["geom"] for p in parcelas])

    # La zona que nos falta = el coto menos lo que ya cubre el GML que tenemos.
    fuera = coto.difference(cubierto)
    print("\nZona sin cubrir: {:,.1f} ha".format(fuera.area / 10000).replace(",", "."))

    # Rejilla de puntos dentro de esa zona.
    minx, miny, maxx, maxy = fuera.bounds
    puntos = []
    y = miny + PASO_M / 2
    while y < maxy:
        x = minx + PASO_M / 2
        while x < maxx:
            p = Point(x, y)
            if fuera.contains(p):
                puntos.append(p)
            x += PASO_M
        y += PASO_M

    print("Puntos a consultar: {} (rejilla de {} m)".format(len(puntos), PASO_M))
    if not puntos:
        print("No hay zona sin cubrir. Nada que consultar.")
        return

    from pyproj import Transformer
    t_inv = Transformer.from_crs(s04.CRS_GML, s04.CRS_GPS, always_xy=True)

    municipios = Counter()
    nombres = {}
    fallos = Counter()

    for i, p in enumerate(puntos, 1):
        lon, lat = t_inv.transform(p.x, p.y)
        clave = "{:.6f},{:.6f}".format(lat, lon)
        venia_de_cache = clave in _cache
        try:
            refcat, desc = consultar_punto(lat, lon)
        except Exception as e:
            fallos[type(e).__name__] += 1
            time.sleep(PAUSA_S)
            continue

        if refcat is None:
            fallos[desc] += 1
        else:
            try:
                res = municipio_de_refcat(refcat)
            except Exception as e:
                fallos["DNPRC " + type(e).__name__] += 1
                res = None
            cod, nom = res if res else ("?????", "(no resuelto)")
            municipios[cod] += 1
            nombres.setdefault(cod, nom)

        if i % 25 == 0:
            print("  ... {}/{}".format(i, len(puntos)))
        # Solo esperamos si de verdad hemos molestado al servidor.
        if not venia_de_cache:
            time.sleep(PAUSA_S)

    guardar_cache()
    ca.guardar_cache()

    print("\n" + "=" * 70)
    print("MUNICIPIOS QUE APORTAN SUPERFICIE AL COTO (fuera de 43060)")
    print("=" * 70)
    total = sum(municipios.values())
    for muni, n in municipios.most_common():
        # Regla de tres sobre la rejilla: si 68 de 84 puntos caen en Valls,
        # Valls aporta aproximadamente 68/84 de la superficie no cubierta.
        # Es una ESTIMACION del muestreo, no una medicion. La cifra buena
        # saldra al cruzar el GML de cada municipio (script 04).
        ha_aprox = fuera.area / 10000 * n / total
        print("  {:<7} {:<40} {:>4} pts  (~{:,.0f} ha estimadas)"
              .format(muni, nombres.get(muni, "?"), n, ha_aprox).replace(",", "."))

    if fallos:
        print("\nPuntos sin respuesta util:")
        for motivo, n in fallos.most_common():
            print("  {:>4}  {}".format(n, motivo))

    print("\nDescarga el GML de cada uno de estos municipios en:")
    print("  https://www.catastro.hacienda.gob.es/INSPIRE/CadastralParcels/ES.SDGC.CP.atom.xml")
    print("y deja los .gml en datos_crudos/gml/")


if __name__ == "__main__":
    main()
