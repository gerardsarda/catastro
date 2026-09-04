# Muestra de 5 fichas para el cliente — cómo ejecutar

## Situación actual

- Las **5 fichas JSON** ya están generadas en `datos/fichas/`:
  - `finca_43060A01100034.json`
  - `finca_43060A01400009.json`
  - `finca_43163A00100005.json`
  - `finca_43163A00100032.json`
  - `finca_43163A00200037.json`
- El **contorno del coto** ya está fijado en `scripts/04_parcelas_en_poligono.py` (6 vértices, 3.567 ha).
- Los **GML del Catastro** de los municipios que toca el coto ya están descargados en `datos_crudos/gml/`.
- La **caché** de la API del Catastro (`datos_crudos/cache_dnprc.json`) ya tiene la respuesta de estas 5 parcelas — no vuelve a pedir nada.
- Solo hay 1 PDF hecho (el piloto). **Faltan los 5 PDFs de la muestra**.

## Antes de ejecutar — revisar dos cosas

1. **`datos/dades_comunes.json`** — cesionaria, coto y condiciones (duración, precio, etc.). Iguales para las 5 fichas. Abrir el archivo y comprobar que los valores son los reales (ahora vienen copiados del piloto).
2. **`datos/vocabulari_catastro.json`** — traducciones castellano → catalán de los términos que devuelve el Catastro (usos, cultivos…). Si alguno está sin traducir, el contrato lo pondrá en castellano tal cual. Rellenar los que falten.

## Comando único para generar los 5 PDFs

Desde la raíz del proyecto (`C:\Users\gerar\OneDrive - URV\Documentos\3. CONSULTORIA\catastro`), en PowerShell:

```bash
Get-ChildItem datos/fichas/*.json | ForEach-Object { python scripts/03_generar_contracte.py $_.FullName }
```

Esto ejecuta el script 03 una vez por cada JSON de la carpeta. Los PDFs salen en `salidas/` con el nombre `contracte_cessio_caca_<referencia>.pdf`.

## Resultado esperado

En `salidas/` aparecerán:

- `contracte_cessio_caca_43060A01100034.pdf`
- `contracte_cessio_caca_43060A01400009.pdf`
- `contracte_cessio_caca_43163A00100005.pdf`
- `contracte_cessio_caca_43163A00100032.pdf`
- `contracte_cessio_caca_43163A00200037.pdf`

Esos son los 5 archivos que se entregan al cliente.

## Si algo va mal

- **Falta un JSON o quiero regenerarlo:** volver a lanzar `python scripts/06_generar_fichas.py`. Como la caché ya tiene las respuestas, es cuestión de segundos.
- **El cliente cambia el contorno del coto:** editar la lista `POLIGONO_COTO` en `scripts/04_parcelas_en_poligono.py` y reejecutar la secuencia entera: `04 → 05 → 07 → 04 → 06 → 03`.
- **Un término sale en castellano en el PDF:** añadir la traducción en `datos/vocabulari_catastro.json` y reejecutar `03` (no hace falta rehacer las fichas).
- **Falta el nombre del propietario:** no se puede automatizar. La Ley del Cadastre (art. 51) no permite descargarlo. Se rellena a mano en el PDF (o se pide al cliente).

## Lo que NO cubre la muestra

- **Comarca:** el Catastro no la da. Si el cliente la pide, hay que ponerla a mano.
- **Propietario:** por lo mismo de arriba, va en blanco (`________________`).
- Todo lo demás (referencia catastral, superficie, municipio, polígono, parcela, paratge, uso, cultivos, límites N/S/E/O) sale directo de los datos.
