# -*- coding: utf-8 -*-
"""
07_descargar_gml.py
-------------------
Baja del Catastro el GML de parcelas de los municipios que le digas y lo deja
descomprimido en datos_crudos/gml/, que es donde lo busca el script 04.

De donde sale: el Catastro publica sus datos INSPIRE en un catalogo ATOM (un
indice en XML, como el RSS de un blog). El indice general apunta a un indice
por provincia, y ese apunta al .zip de cada municipio. Este script recorre esa
cadena en vez de llevar las URLs a pelo, porque las URLs cambian y el catalogo
no.

Uso:
  python scripts/07_descargar_gml.py 43163 43087 43110
  python scripts/07_descargar_gml.py            (usa MUNICIPIOS_POR_DEFECTO)
"""

import io
import os
import re
import sys
import zipfile

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)
DIR_GML = os.path.join(RAIZ, "datos_crudos", "gml")

# Los 7 municipios de la zona de trabajo, con su codigo DEL CATASTRO:
#   43163 Valls          43110 El Pla de Santa Maria   43087 Montblanc
#   43060 Figuerola del Camp                           43126 La Riba
#   43036 Cabra del Camp                               43174 Vilaverd
MUNICIPIOS_POR_DEFECTO = ["43163", "43110", "43087", "43060",
                          "43126", "43036", "43174"]

ATOM_RAIZ = "https://www.catastro.hacienda.gob.es/INSPIRE/CadastralParcels/ES.SDGC.CP.atom.xml"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "*/*",
}


def url_zip_del_municipio(codigo):
    """Devuelve la URL del .zip de ese municipio, o None si no aparece.

    'codigo' son las 5 cifras que usa el Catastro: provincia (2) + municipio (3).
    Ojo: el municipio es el codigo DEL CATASTRO, que no es el del INE. Para
    Valls, INE=161 pero Catastro=163, y el que vale aqui es el 163.
    """
    provincia = codigo[:2]

    # Paso 1: del indice general sacamos el indice de la provincia.
    r = requests.get(ATOM_RAIZ, headers=HEADERS, timeout=60)
    r.raise_for_status()
    m = re.search(r'href="([^"]*/{}/ES\.SDGC\.CP\.atom_{}\.xml)"'.format(provincia, provincia), r.text)
    if not m:
        return None
    url_prov = m.group(1).replace("http://", "https://")

    # Paso 2: del indice de la provincia sacamos el zip del municipio.
    r = requests.get(url_prov, headers=HEADERS, timeout=60)
    r.raise_for_status()
    m = re.search(r'href="([^"]*A\.ES\.SDGC\.CP\.{}\.zip)"'.format(codigo), r.text)
    return m.group(1) if m else None


def descargar_y_descomprimir(codigo):
    url = url_zip_del_municipio(codigo)
    if not url:
        print("  {}: NO aparece en el catalogo del Catastro. Revisa el codigo.".format(codigo))
        return False

    destino = os.path.join(DIR_GML, "A.ES.SDGC.CP.{}.cadastralparcel.gml".format(codigo))
    if os.path.exists(destino):
        print("  {}: ya lo tienes, no lo vuelvo a bajar.".format(codigo))
        return True

    print("  {}: bajando {}".format(codigo, url))
    r = requests.get(url, headers=HEADERS, timeout=300)
    r.raise_for_status()

    # Guardamos tambien el .zip original: si algun dia hay que rehacer esto,
    # mejor tener el fichero tal cual lo dio el Catastro que volver a pedirlo.
    zip_local = os.path.join(RAIZ, "datos_crudos", "A.ES.SDGC.CP.{}.zip".format(codigo))
    with open(zip_local, "wb") as fh:
        fh.write(r.content)

    # ZipFile trabaja sobre un fichero; BytesIO le hace creer que los bytes
    # que tenemos en memoria son uno, y asi no hay que reabrir el de disco.
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        nombres = [n for n in z.namelist() if n.endswith(".cadastralparcel.gml")]
        if not nombres:
            print("  {}: el zip no trae fichero de parcelas.".format(codigo))
            return False
        with z.open(nombres[0]) as origen, open(destino, "wb") as fh:
            fh.write(origen.read())

    print("  {}: OK -> {} ({:.1f} MB)".format(
        codigo, os.path.basename(destino), os.path.getsize(destino) / 1048576))
    return True


def main():
    codigos = sys.argv[1:] or MUNICIPIOS_POR_DEFECTO
    os.makedirs(DIR_GML, exist_ok=True)
    print("Municipios a descargar:", ", ".join(codigos))
    ok = sum(1 for c in codigos if descargar_y_descomprimir(c))
    print("\nDescargados correctamente: {}/{}".format(ok, len(codigos)))
    print("Ahora vuelve a lanzar:  python scripts/04_parcelas_en_poligono.py")


if __name__ == "__main__":
    main()
