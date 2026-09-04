# -*- coding: utf-8 -*-
"""
01_test_catastro.py
-------------------
Objetivo UNICO de este script: comprobar si desde esta maquina podemos
hablar con la API publica del Catastro y ver la respuesta CRUDA.

No parsea nada, no genera CSV, no toca el PDF. Solo pregunta y ensena
lo que le devuelven. Es un test de viabilidad.
"""

import sys
import requests

# En Windows la consola a veces no sabe imprimir acentos ni simbolos raros.
# Esta linea fuerza a que la salida se escriba en UTF-8 y no reviente.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---------------------------------------------------------------------------
# 1) DATOS DE LA PRUEBA
# ---------------------------------------------------------------------------
# Una "referencia catastral" (RC) es el DNI de una parcela: 14 caracteres.
# 43060A00600107 se descompone asi:
#   43     -> provincia (Tarragona)
#   060    -> municipio dentro de la provincia
#   A      -> indica que es rustica
#   006    -> poligono
#   00107  -> parcela
RC = "43060A00600107"
PROVINCIA = "TARRAGONA"
MUNICIPIO = "FIGUEROLA DEL CAMP"


# ---------------------------------------------------------------------------
# 2) CABECERAS HTTP
# ---------------------------------------------------------------------------
# Una peticion HTTP lleva "cabeceras": metadatos sobre quien pregunta.
# Por defecto requests se identifica como "python-requests/2.34.2", y algunas
# webs publicas bloquean eso. Nos identificamos como un navegador real para
# descartar de entrada un bloqueo por bot-detection (tu punto 4a).
HEADERS_NAVEGADOR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "es-ES,es;q=0.9",
}


def mostrar_respuesta(titulo, respuesta):
    """Imprime de forma legible que ha devuelto el servidor.

    'respuesta' es el objeto Response que devuelve requests. Lo interesante:
      .status_code -> numero: 200 = OK, 403 = prohibido, 404 = no existe, 500 = error del servidor
      .headers     -> cabeceras que manda el servidor (nos dicen si es XML o JSON)
      .text        -> el cuerpo de la respuesta como texto plano (lo CRUDO)
    """
    print("\n" + "=" * 78)
    print(titulo)
    print("=" * 78)
    print("URL final :", respuesta.url)
    print("Status    :", respuesta.status_code, respuesta.reason)
    print("Content-Type:", respuesta.headers.get("Content-Type"))
    print("Longitud  :", len(respuesta.text), "caracteres")
    print("-" * 78)
    # Mostramos como mucho 4000 caracteres para no inundar la pantalla.
    print(respuesta.text[:4000])
    if len(respuesta.text) > 4000:
        print("\n... [recortado, hay {} caracteres mas]".format(len(respuesta.text) - 4000))


# ---------------------------------------------------------------------------
# PRUEBA A: variante REST clasica (.asmx) -> devuelve XML
# ---------------------------------------------------------------------------
def prueba_rest_xml():
    url = ("http://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/"
           "OVCCallejero.asmx/Consulta_DNPRC")

    # Los parametros van en la URL (?Provincia=...&Municipio=...&RC=...).
    # requests los construye y los codifica solo a partir de este diccionario.
    params = {
        "Provincia": PROVINCIA,
        "Municipio": MUNICIPIO,
        "RC": RC,
    }

    # timeout=30 -> si el servidor no contesta en 30 segundos, abortamos.
    # Sin timeout el script podria quedarse colgado para siempre.
    respuesta = requests.get(url, params=params, headers=HEADERS_NAVEGADOR, timeout=30)
    mostrar_respuesta("PRUEBA A - REST .asmx (XML) con Provincia y Municipio", respuesta)
    return respuesta


# ---------------------------------------------------------------------------
# PRUEBA B: la misma llamada pero SIN provincia ni municipio
# ---------------------------------------------------------------------------
# La RC de 14 posiciones ya lleva dentro la provincia y el municipio, asi que
# en teoria el servicio deberia resolverla sin ayuda. Si esto funciona nos
# ahorramos tener que saber el nombre exacto del municipio segun Catastro
# (que no siempre coincide con el nombre oficial del ayuntamiento).
def prueba_rest_xml_sin_municipio():
    url = ("http://ovc.catastro.meh.es/ovcservweb/OVCSWLocalizacionRC/"
           "OVCCallejero.asmx/Consulta_DNPRC")
    params = {"Provincia": "", "Municipio": "", "RC": RC}
    respuesta = requests.get(url, params=params, headers=HEADERS_NAVEGADOR, timeout=30)
    mostrar_respuesta("PRUEBA B - REST .asmx (XML) sin Provincia ni Municipio", respuesta)
    return respuesta


# ---------------------------------------------------------------------------
# PRUEBA C: variante JSON moderna (WCF)
# ---------------------------------------------------------------------------
def prueba_json():
    url = ("https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/"
           "COVCCallejero.svc/json/Consulta_DNPRC")
    params = {"Provincia": PROVINCIA, "Municipio": MUNICIPIO, "RefCat": RC}  # ojo: WCF usa RefCat, no RC
    respuesta = requests.get(url, params=params, headers=HEADERS_NAVEGADOR, timeout=30)
    mostrar_respuesta("PRUEBA C - WCF (JSON) con Provincia y Municipio", respuesta)
    return respuesta


# ---------------------------------------------------------------------------
# PRUEBA D: JSON sin provincia ni municipio
# ---------------------------------------------------------------------------
def prueba_json_sin_municipio():
    url = ("https://ovc.catastro.meh.es/OVCServWeb/OVCWcfCallejero/"
           "COVCCallejero.svc/json/Consulta_DNPRC")
    params = {"Provincia": "", "Municipio": "", "RefCat": RC}  # ojo: WCF usa RefCat
    respuesta = requests.get(url, params=params, headers=HEADERS_NAVEGADOR, timeout=30)
    mostrar_respuesta("PRUEBA D - WCF (JSON) sin Provincia ni Municipio", respuesta)
    return respuesta


# ---------------------------------------------------------------------------
# EJECUCION
# ---------------------------------------------------------------------------
# Este 'if' significa: "solo ejecuta esto si lanzo el archivo directamente,
# no si alguien lo importa como libreria". Es una convencion estandar.
if __name__ == "__main__":
    pruebas = [
        ("A", prueba_rest_xml),
        ("B", prueba_rest_xml_sin_municipio),
        ("C", prueba_json),
        ("D", prueba_json_sin_municipio),
    ]

    resumen = []
    for nombre, funcion in pruebas:
        try:
            r = funcion()
            resumen.append((nombre, r.status_code, len(r.text)))
        except Exception as e:
            # Si falla la RED (DNS, timeout, SSL...), requests lanza una excepcion
            # y el script moriria. La capturamos para poder seguir con las demas.
            print("\n" + "=" * 78)
            print("PRUEBA {} - FALLO DE CONEXION".format(nombre))
            print("=" * 78)
            print(type(e).__name__, ":", e)
            resumen.append((nombre, "ERROR", type(e).__name__))

    print("\n\n" + "#" * 78)
    print("RESUMEN")
    print("#" * 78)
    for nombre, estado, extra in resumen:
        print("Prueba {}: status={}  ({})".format(nombre, estado, extra))
