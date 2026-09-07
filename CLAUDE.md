# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **contract generation pipeline** for hunting area leases (cessió de drets de caça) in Catalonia. It takes cadastral data from Spain's Cadastre, identifies land parcels that intersect with a hunting area boundary (vedat), and generates a PDF contract for each parcel.

**Key principle (LA REGLA):** If a parcel's geometry *touches* the vedat polygon—even by a single vertex—the entire parcel is included with its complete cadastral area. No parcels are split or marked "partial"; rights are granted per parcel, not per square meter. This means the total area ceded is always larger than the vedat's drawn area.

## Quick Start

### Installation
```bash
pip install -r requirements.txt
```

### Run the Streamlit Web Interface
```bash
streamlit run app.py
```
Opens an interactive 4-step interface to draw a vedat polygon on a map and generate contracts.

### Run Individual Pipeline Scripts
```bash
# Find parcels within the vedat polygon
python scripts/04_parcelas_en_poligono.py

# Generate JSON parcel sheets (fichas)
python scripts/06_generar_fichas.py

# Generate a single parcel's PDF contract
python scripts/03_generar_contracte.py

# Download cadastral GML files for municipalities (by Cadastre code, not INE)
python scripts/07_descargar_gml.py 43163 43110 43087 43060 43126 43036 43174
```

## Architecture

### Three Execution Paths

1. **Batch pipeline** (scripts in sequence)
   - Script 04 → 05 → 07 → 04 (again) → 06 → 03
   - Outputs: CSV, GeoJSON, JSON fichas, PDFs to `salidas/`
   
2. **Streamlit UI** (`app.py`)
   - Wraps scripts 04, 06, 03 in an interactive 4-tab interface
   - Lets users draw the vedat on a map instead of editing coordinates
   - No reimplementation: it loads and calls the existing scripts
   
3. **Standalone script**
   - Each numbered script is self-contained and can run independently

### Data Directories

- **`datos_crudos/`** – Raw cadastral data
  - `gml/` – Cadastre INSPIRE GML files (parcel boundaries + area data)
  - `cache_dnprc.json` – Cached API responses (deletes to refresh)
  
- **`datos/`** – Processed/static data
  - `fichas/` – Generated JSON for each parcel
  - `dades_comunes.json` – Common contract data (cessionario, vedat name, terms)
  - `vocabulari_catastro.json` – Spanish→Catalan translation dictionary for cadastral terms
  - `comarques.json` – Municipality to comarca (region) mapping
  
- **`salidas/`** – Output files
  - `.pdf` contracts
  - `.csv` and `.geojson` for verification in mapping tools

### Key Modules

| Module | Role |
|--------|------|
| `app.py` | Streamlit UI; imports and calls scripts 03, 04, 06 |
| `scripts/04_parcelas_en_poligono.py` | Spatial intersection: finds which GML parcels touch the vedat polygon; outputs CSV |
| `scripts/06_generar_fichas.py` | Creates per-parcel JSON sheets; queries Cadastre API for details; calculates boundaries |
| `scripts/03_generar_contracte.py` | ReportLab PDF generator; takes JSON ficha → PDF contract |
| `catastro_api.py` | Wrapper for Cadastre's Consulta_DNPRC API |

## Important Concepts

### Coordinate Systems
- **GPS (lat/lon):** Used in Google Maps, Streamlit UI, GeoJSON output
- **UTM (x/y):** Used in GML files and all geometric calculations
- **CRS constants** in script 04: `CRS_GPS` (EPSG:4326), `CRS_GML` (EPSG:25831)
- `pyproj.Transformer` converts between them

### Cadastral References & Municipality Codes
- **Cadastral reference (refcat):** 20-character code identifying a parcel
  - Format: `PP MM SS DDDDDDD CC VV` (province, municipality, section, parcel, digit check, version)
  - **Rústicas** (rural): first 5 chars are the municipality Cadastre code
  - **Urbanas** (urban): first 5 chars are a *cartographic grid*, NOT the municipality; you must query the API
  
- **Municipality codes** are Cadastre codes, NOT INE codes (e.g., Valls is 163 for Cadastre, 161 for INE)
- Current coverage: 7 municipalities in Alt Camp (43060, 43087, 43110, 43126, 43163, 43036, 43174) = 35K+ parcels, 25K ha

### GML Quirks
- Multiple GML records with the same refcat = one parcel in multiple fragments; script 04 groups them
- Surface area from GML field `areaValue` is always used when present; geometry area is fallback
- Namespaces are XML URLs (e.g., `http://inspire.ec.europa.eu/schemas/cp/4.0`), not prefixes

## Data Flow

### Batch Mode (Script Chain)
```
POLIGONO_COTO (hardcoded lat/lon list in script 04)
    ↓
[04] Spatial intersection with GML → parcelas_dentro_del_coto.csv
    ↓
[05] List missing municipalities
    ↓
[07] Download their GML files
    ↓
[04] Re-run (now with complete data)
    ↓
[06] Query Cadastre API for each parcel → JSON fichas
    ↓
[03] Generate PDF from each ficha
```

### Streamlit Mode
```
User draws polygon on map
    ↓
[04] Spatial intersection (in-memory)
    ↓
Show results on map + table
    ↓
User fills in owner details per parcel (Paso 3)
    ↓
[06] Load/fetch ficha for each selected parcel
    ↓
[03] Generate PDF → download ZIP
```

## Manual Data Entry (Non-Automatable)

Two JSON files must be reviewed and edited by hand:

1. **`datos/dades_comunes.json`** 
   - Cessionario (hunter's association): name, NIF, address, registry details, representative
   - Vedat: name
   - Contract terms: date, duration, payment terms, jurisdiction, seasons
   - Same for all contracts; reviewed once; survives across runs

2. **`datos/vocabulari_catastro.json`**
   - Cadastre responds in Spanish (e.g., "ALMENDRO REGADÍO", "Agrario")
   - Script 06 harvests all *unique* terms and leaves translations empty
   - Translate once; script 03 uses these when rendering PDFs
   - Missing translations fall back to the Spanish original (safe default)

## API Integration

### Cadastre Consulta_DNPRC
- **What it provides:** municipality, paraje (place name), polygon #, parcel #, land use, crops
- **Called by:** script 06 and `app.py`
- **Rate-limited:** pauses between requests to avoid overload
- **Cached:** responses saved to `datos_crudos/cache_dnprc.json`; delete file to force refresh

### Caching
- Script 06 builds cache as it runs; `app.py` never forces refresh (uses disk cache)
- Cache survives across script runs and Streamlit reruns
- If Cadastre API changes or you need fresh data, delete `datos_crudos/cache_dnprc.json`

## Verification Checklist

Before generating contracts:

1. **Verify the vedat boundary** before calculating parcels
   - After script 04, upload `salidas/coto.geojson` and `salidas/parcelas_dentro_del_coto.geojson` to https://geojson.io
   - One misplaced vertex won't error; it just produces wrong results
   - Full municipality map: script 08 generates `salidas/parcelas_todos_los_municipios.geojson` (33 MB; use QGIS, not browser)

2. **Check `dades_comunes.json`** before Paso 3
   - Copy-pasted from a pilot; verify all cessionario and contract terms are correct
   - Empty fields render as dotted lines in the PDF

3. **Review translations** in `vocabulari_catastro.json` after script 06
   - Untranslated terms appear in Spanish in the PDF (acceptable; safer than guessing)
   - Translate once; terms are reused across many parcels

## Streamlit App Structure (app.py)

**Tab 1 – Cessionario data**
- Form to enter cessionario (association), vedat name, and contract terms
- Saved to `datos/dades_comunes.json`

**Tab 2 – Area selection**
- Map to draw vedat polygon
- On submit, runs script 04 → outputs CSV, GeoJSON, metrics
- Shows map of found parcels and summary table

**Tab 3 – Owner details**
- Per-parcel form for cedent (owner) name, address, document type/number
- Filterable by municipality; checkbox to include/exclude each parcel
- Loaded from disk ficha if it exists (preserves prior entries across sessions)

**Tab 4 – Contract generation**
- Runs script 06 (fetch or load fichas) + script 03 (PDF) for each selected parcel
- Progress bar; shows errors per parcel
- Downloads ZIP of all PDFs

**State management:**
- `st.session_state` persists across tabs and reruns
- `@st.cache_resource` for GML loading, spatial index, transformers (expensive)
- Folium maps use `st_folium()` plugin; tab navigation via injected JavaScript

## Dependencies

| Package | Purpose |
|---------|---------|
| `streamlit`, `streamlit-folium`, `folium` | Web UI and mapping |
| `shapely`, `pyproj`, `lxml` | Spatial geometry; coordinate transforms; XML/GML parsing |
| `pandas` | Tabular output (CSVs, DataFrames) |
| `reportlab` | PDF generation |
| `requests` | HTTP calls to Cadastre API |

## Testing & Verification

- No test suite; validation is manual and visual (GeoJSON on a map)
- Script 04 detects self-intersecting polygons and warns
- App warns if the drawn polygon extends beyond downloaded GML coverage
- Missing parcels are logged; API errors per-parcel are caught and reported per-parcel

## Next Steps for New Contributors

1. Download GML files for your municipalities using script 07
2. Hardcode or read the vedat polygon; run script 04 to find parcels
3. Verify results on https://geojson.io
4. Fill in `dades_comunes.json` with cessionario and contract data
5. Run script 06 to generate fichas (one API call per parcel; ~1–2 sec each)
6. Review `vocabulari_catastro.json`; translate as needed
7. Run script 03 or use the Streamlit app to generate PDFs
