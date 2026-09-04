# Contractes de cessió de drets de caça — pipeline

Del contorn del vedat (coordenades de Google Maps) a un contracte PDF per parcel·la.

## Els cinc passos

```
coordenades del vedat
        │
        ▼
[04] creua el contorn amb la geometria cadastral  ──►  salidas/parcelas_dentro_del_coto.csv
        │                                              salidas/*.geojson  (per verificar-ho en un mapa)
        ▼
[05] quins municipis toca el vedat                ──►  llista de codis GML que falten
        │
        ▼
[07] baixa els GML que falten del Catastro        ──►  datos_crudos/gml/*.gml
        │
        ▼
[06] una fitxa JSON per parcel·la                 ──►  datos/fichas/finca_<refcat>.json
        │                                              datos/vocabulari_catastro.json
        ▼
[03] el contracte en PDF                          ──►  salidas/contracte_cessio_caca_<refcat>.pdf

[08] totes les parcel·les dels municipis baixats  ──►  salidas/parcelas_todos_los_municipios.geojson
     (capa base, al marge de qualsevol vedat)
```

Ordre real d'execució: **04 → 05 → 07 → 04 (un altre cop) → 06 → 03**. El 04 es
torna a executar després del 07 perquè aleshores ja té tots els municipis.

```bash
python scripts/04_parcelas_en_poligono.py
```

## La regla: qui toca, entra sencera

Si la geometria d'una finca **toca** el polígon del vedat —encara que sigui
només per un vèrtex— la finca hi entra **sencera**, amb la seva **superfície
cadastral completa**. No es reparteixen metres quadrats ni hi ha finques
"parcials" ni "residuals": els drets de caça es cedeixen per finca, no per
superfície.

Conseqüència directa: la **superfície cedida sempre és més gran que l'àrea del
polígon dibuixat**, perquè les finques de la vora hi entren totes. Amb el
contorn de prova (3.567 ha) surten 3.531 finques i 3.904 ha.

## Els municipis descarregats

Els 7 de la zona de treball, amb el codi **del Catastro** (que no és el de
l'INE):

| Codi | Municipi | | Codi | Municipi |
|---|---|---|---|---|
| 43163 | Valls | | 43126 | La Riba |
| 43110 | El Pla de Santa Maria | | 43036 | Cabra del Camp |
| 43087 | Montblanc | | 43174 | Vilaverd |
| 43060 | Figuerola del Camp | | | |

En total 35.180 parcel·les i 24.952 ha de geometria cadastral, ja baixades a
`datos_crudos/gml/`. Per tornar-los a baixar o afegir-ne un altre:

```bash
python scripts/07_descargar_gml.py 43163 43110 43087 43060 43126 43036 43174
```

## On es canvia el contorn del vedat

A `scripts/04_parcelas_en_poligono.py`, la llista `POLIGONO_COTO`: parells
`(latitud, longitud)` tal com surten de Google Maps, **en l'ordre en què es
recorre el perímetre**. Si dos punts estan canviats de lloc el polígon es creua
a si mateix i el càlcul no val; el script ho detecta i avisa.

Contorn actual: 6 vèrtexs, 3.567 ha.

## D'on surt cada camp de la fitxa

| Camp | Font | Es pot automatitzar? |
|---|---|---|
| Referència cadastral, superfície, geometria | GML INSPIRE (local) | Sí |
| Municipi, província, polígon, parcel·la | API `Consulta_DNPRC` | Sí |
| Nom de la finca (paratge) | API `Consulta_DNPRC`, camp `npa` | Sí, quan el Catastro el té |
| Ús i conreus | API `Consulta_DNPRC` | Sí, **en castellà** |
| Límits (nord/sud/est/oest) | Calculat de la geometria | Sí, per referència cadastral |
| Situació dins el vedat (hi entra sencera) | Calculat | Sí |
| Comarca | — | **No**, el Catastro no la dona |
| **Nom del propietari** | — | **No** (Llei del Cadastre, art. 51) |
| Dades del contracte (durada, preu…) | `datos/dades_comunes.json` | Es revisa una vegada |

## Les dues coses que s'han de revisar a mà

1. **`datos/dades_comunes.json`** — cessionària, vedat i condicions. Són iguals
   per a tots els contractes: es revisen una vegada i valen per a totes les
   fitxes. Els valors actuals venen copiats de la fitxa pilot; **comprova que
   siguin els reals**.

2. **`datos/vocabulari_catastro.json`** — el Catastro contesta en castellà
   (`ALMENDRO REGADÍO`, `Agrario`) i el contracte va en català. El script 06
   recull tots els termes **diferents** que han sortit (són poques desenes, no
   milers) i els deixa aquí amb la traducció buida. Es tradueixen una vegada.
   Si un terme no està traduït surt el literal del Catastro: val més que surti
   en castellà que no pas inventar-se'l.

## Verificar el contorn abans de fer res

`salidas/coto.geojson` i `salidas/parcelas_dentro_del_coto.geojson` s'arrosseguen
a <https://geojson.io> i es veuen sobre el mapa a l'instant. Si el que es vol
veure és el mapa cadastral sencer dels 7 municipis (33 MB: millor QGIS que el
navegador), el genera el script 08 a
`salidas/parcelas_todos_los_municipios.geojson`. Val la pena fer-ho
sempre que es canviïn les coordenades: un vèrtex mal posat no dona cap error,
només un resultat equivocat.

## Coses que convé saber

- **La cache.** `datos_crudos/cache_dnprc.json` guarda la resposta crua de cada
  referència. La segona vegada que s'executa el 06 no torna a demanar res. Si es
  vol refrescar, s'esborra el fitxer.
- **Parcel·les en diversos trossos.** Al GML apareixen com a diversos registres
  amb la MATEIXA referència cadastral. El script els agrupa; si no ho fes,
  sortirien fitxes duplicades i superfície comptada dues vegades.
- **Referències urbanes.** Les 5 primeres xifres d'una referència urbana **no**
  són el municipi (són la quadrícula cartogràfica). Només val per a les
  rústiques. Per això el municipi es demana sempre a l'API.
- **Codi INE ≠ codi Catastro.** Valls és 161 per l'INE i 163 per al Catastro. El
  que fan servir els GML i els enllaços de cartografia és el del Catastro.
