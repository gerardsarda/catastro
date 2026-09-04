# -*- coding: utf-8 -*-
"""
catastro_api.py
---------------
Cliente comun para hablar con el Catastro. Lo usan los scripts 05 y 06.

Esta aqui para no repetir tres veces la misma logica de peticiones, cache y
manejo de errores, y sobre todo para tener UN solo sitio donde esta escrito
como se interpreta la respuesta del Catastro. Si manana cambian el formato,
se toca aqui y ya.

Regla de la casa: este modulo devuelve lo que dice el Catastro o devuelve
None. Nunca rellena huecos por su cuenta.
"""

import json
import os
import time

import requests

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)

URL_DNPRC = ("https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/"
             "COVCCallejero.svc/json/Consulta_DNPRC")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "*/*",
}

# Pausa entre peticiones reales. El servicio es publico y gratuito: si lo
# machacamos nos cortan, y con razon.
PAUSA_S = 0.35

CACHE_PATH = os.path.join(RAIZ, "datos_crudos", "cache_dnprc.json")
_cache = None


def _abrir_cache():
    """Carga la cache de disco la primera vez que hace falta.

    Guardamos la respuesta CRUDA de cada referencia. Asi, si manana mejoramos
    la forma de interpretarla, no hay que volver a pedir nada: se reprocesa
    lo que ya tenemos.
    """
    global _cache
    if _cache is None:
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH, "r", encoding="utf-8") as fh:
                _cache = json.load(fh)
        else:
            _cache = {}
    return _cache


def guardar_cache():
    c = _abrir_cache()
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump(c, fh, ensure_ascii=False)


def cuantas_cacheadas():
    return len(_abrir_cache())


def consulta_dnprc_cruda(refcat):
    """Devuelve el JSON tal cual lo manda el Catastro para esa referencia.

    Pasamos Provincia y Municipio vacios a proposito: la referencia catastral
    de 14 caracteres ya lleva dentro el municipio, asi que el servicio la
    resuelve sola y nos ahorramos tener que saber como escribe el Catastro el
    nombre de cada pueblo (que no siempre es el nombre oficial).
    """
    c = _abrir_cache()
    if refcat in c:
        return c[refcat]

    r = requests.get(URL_DNPRC, headers=HEADERS, timeout=30,
                     params={"Provincia": "", "Municipio": "", "RefCat": refcat})
    r.raise_for_status()
    # El servidor declara charset=utf-8 y cumple. requests lo decodifica bien.
    d = r.json()
    c[refcat] = d
    time.sleep(PAUSA_S)
    return d


def _primer_bi(res):
    """Saca el bloque de datos del inmueble, sea cual sea la forma de respuesta.

    El Catastro contesta de DOS maneras distintas segun la parcela:

      a) 'bico'  -> la parcela es un unico inmueble (el caso normal en rustica).
                    Los datos estan en bico.bi y bico.finca.

      b) 'lrcdnp'-> la parcela tiene VARIOS inmuebles (division horizontal: un
                    edificio de pisos, una nave con varias unidades...). Aqui
                    no hay un 'bi' unico, sino una LISTA en lrcdnp.rcdnp.

    Si alguien asume solo la forma (a), el script peta con KeyError en cuanto
    aparece un edificio. Aqui devolvemos (dt, bi, finca), con bi y finca a None
    cuando la parcela es de las de lista.
    """
    res = res.get("consulta_dnprcResult", res)

    if "bico" in res:
        bico = res["bico"]
        bi = bico.get("bi", {})
        return bi.get("dt", {}), bi, bico.get("finca", {})

    if "lrcdnp" in res:
        lista = res["lrcdnp"].get("rcdnp", [])
        if lista:
            # Todos los inmuebles de la lista comparten parcela, asi que los
            # datos de situacion (municipio, poligono, paraje) son los mismos.
            # Cogemos los del primero. Lo que NO cogemos es superficie ni uso:
            # eso es de cada inmueble, no de la parcela.
            return lista[0].get("dt", {}), None, None
    return {}, None, None


def datos_de_parcela(refcat):
    """Devuelve un dict con los datos del Catastro para una referencia.

    Todo campo que el Catastro no de queda a None. No se rellena nada a mano.
    """
    res = consulta_dnprc_cruda(refcat)
    dt, bi, finca = _primer_bi(res)
    if not dt:
        return None

    loine = dt.get("loine", {})
    # Codigo de 5 cifras que usan los ficheros GML: provincia INE + municipio
    # Catastro a 3 digitos. OJO: loine.cm (municipio INE) y cmc (municipio
    # Catastro) son numeros DISTINTOS para el mismo pueblo (Valls: 161 y 163).
    # El de los GML y el de los enlaces de cartografia es cmc.
    cod_muni = None
    if loine.get("cp") and dt.get("cmc"):
        cod_muni = "{}{}".format(loine["cp"], str(dt["cmc"]).zfill(3))

    # Datos de situacion rustica: poligono, parcela y paraje.
    lorus = dt.get("locs", {}).get("lors", {}).get("lorus", {})
    cpp = lorus.get("cpp", {})
    paraje = lorus.get("npa")
    if paraje in ("NC", ""):
        paraje = None  # 'NC' = no consta. Es un hueco, no un nombre.

    # Cultivos (subparcelas). Una parcela puede tener varios: 3.000 m2 de
    # almendro y 5.000 de erial, por ejemplo. Los devolvemos todos.
    cultivos = []
    if bi:
        for sp in res.get("consulta_dnprcResult", res).get("bico", {}).get("lspr", []) or []:
            d = sp.get("dspr", {})
            if d.get("dcc"):
                cultivos.append({
                    "cultivo": d.get("dcc"),
                    "codigo": d.get("ccc"),
                    "intensidad_productiva": d.get("ip"),
                    "superficie_m2": int(d["ssp"]) if str(d.get("ssp", "")).isdigit() else None,
                })

    sup = None
    if finca:
        ss = finca.get("dff", {}).get("ss")
        if str(ss).isdigit():
            sup = int(ss)

    return {
        "referencia_cadastral": refcat,
        "provincia": dt.get("np"),
        "municipio": dt.get("nm"),
        "codigo_municipio_gml": cod_muni,
        "paraje": paraje,
        "poligono": cpp.get("cpo"),
        "parcela": cpp.get("cpa"),
        "uso": (bi or {}).get("debi", {}).get("luso"),
        "superficie_catastro_m2": sup,
        "cultivos": cultivos,
        "descripcion_catastro": (bi or {}).get("ldt") or (finca or {}).get("ldt"),
        "url_cartografia": (finca or {}).get("infgraf", {}).get("igraf"),
        # Si es True, la parcela tiene varios inmuebles y el Catastro no da
        # un uso ni una superficie unicos para ella. Hay que mirarla a mano.
        "varios_inmuebles": bi is None,
    }
