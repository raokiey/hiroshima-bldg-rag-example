# Hiroshima Building RAG

*[日本語版 README はこちら / Japanese README here](README_ja.md)*

A geospatial semantic RAG (Retrieval-Augmented Generation) prototype that combines
PLATEAU LOD2 building data for Hiroshima City with disaster-risk attributes
(storm surge / flood / tsunami), and answers natural-language questions such as
*"Which buildings have low storm surge risk and are close to a train station?"*
by combining spatial operations, vector search, and LLM reasoning.

It ships with a chat-style Web UI (with a live map) as well as a CLI.

---

## Overview

- **Input:** a natural-language question, optionally with a location + radius
  (e.g. "near Hiroshima Castle, within 500m").
- **Output:** a short list of recommended buildings with a natural-language
  explanation, plus a map highlighting them.
- **Data:** a sample of 2,958 LOD2 buildings from Hiroshima's Project PLATEAU
  3D city model, enriched with disaster-risk attributes and surrounding
  context (nearest station, nearest shelter, nearby parks, etc.).

---

## How it works

```
[natural-language query] + [optional: lon/lat + radius]
        │
        ▼
  ① Query embedding (RURI v3 310m, local inference; Gemini embeddings optional)
        │
        ▼
  ② DuckDB HNSW vector search + ST_DWithin spatial filter (optional)
        │
        ▼
  ③ LLM answer generation (Gemini 3.5 Flash Lite)
        │
        ▼
  [recommended buildings + reasoning text] → REST API (FastAPI)
        → chat UI + MapLibre GL JS map
```

Each building is pre-processed offline into a "profile card" (structure, disaster
risk ranks, distance to nearest station/shelter/park, etc.), embedded, and stored
in DuckDB with an HNSW vector index. At query time, the query is routed to a
structured (SQL-only), semantic (vector-only), or hybrid (SQL-filtered +
vector-ranked, merged with BM25 full-text search via RRF) search path depending
on what it asks for.

---

## Setup

### Python environment (pixi)

Install [pixi](https://prefix.dev/docs/pixi/overview):

```bash
# Windows (PowerShell)
winget install prefix-dev.pixi

# macOS / Linux
curl -fsSL https://pixi.sh/install.sh | bash
```

```bash
git clone https://github.com/raokiey/hiroshima-bldg-rag-example.git
cd hiroshima-bldg-rag-example
pixi install
```

### API key

```bash
cp .env.example .env
```

Edit `.env` and set your key (get one from
[Google AI Studio](https://aistudio.google.com/apikey)):

```
GEMINI_API_KEY=your_gemini_api_key
```

### Frontend (Node.js, only needed for the Web UI)

Requires [Node.js 18+](https://nodejs.org/).

```bash
cd frontend
npm install
cd ..
```

---

## How to run

### Data preparation

The Hiroshima sample data under `data/` is bundled with the repo, so you can go
straight to the CLI commands below.

To use a different city's PLATEAU export, convert its CityGML to GeoPackage with
the [PLATEAU GIS Converter](https://github.com/Project-PLATEAU/PLATEAU-GIS-Converter),
then point the pipeline at it with either of these (no need to overwrite the
files under `data/`):

- **CLI flags** (one-off runs):
  ```bash
  pixi run enrich --gpkg-path path/to/other_city.gpkg --city-prefix 12345_other-city_city_2023
  ```
- **Environment variables** (`.env`, also picked up by the Web UI): set
  `PLATEAU_GPKG_PATH` etc. — see the commented-out examples in `.env.example`.

The five `data/related/` GeoJSON files (shelters, stations, emergency routes,
parks, landmarks) follow PLATEAU's standard
`{city-code}_{city-name}_city_{year}_{dataset}.geojson` naming convention, so
`--city-prefix` (or `PLATEAU_CITY_PREFIX`) alone switches all five at once.

### CLI

| Command | What it does | Time |
|---------|---------------|------|
| `pixi run investigate` | Inspect the GeoPackage's table structure and JOIN keys | seconds |
| `pixi run spatial` | Test coordinate transform + spatial search | seconds |
| `pixi run enrich` | Build building profile cards and store their embeddings | **first run only, tens of minutes** (API calls) |
| `pixi run search` | Run a demo query from the CLI (natural language → LLM answer) | ~30s |

`pixi run enrich` only needs to run once — if `output/plateau_rag.duckdb` already
exists, the data is already built. To try your own query:

```bash
pixi run search "buildings with low storm surge risk and fire-resistant construction"
```

### Web UI

**Terminal 1 — FastAPI backend (API)**

```bash
pixi run api
# → http://localhost:8000
```

**Terminal 2 — Vite frontend (Web UI dev server)**

```bash
pixi run app
# → http://localhost:5173
```

Open `http://localhost:5173` in your browser. The backend (port 8000) must be
running first.

For a production build served directly by FastAPI (single origin, no separate
dev server):

```bash
pixi run build
# → outputs to frontend/src/static/, then `pixi run api` alone serves everything
```

---

## Data used

| Dataset | File | Content |
|---------|------|---------|
| Buildings + risk attributes | `data/hiroshima_sample.gpkg` | A sample of 2,958 LOD2 buildings, storm surge / flood / tsunami risk |
| Land use | `data/hiroshima_landuse.gpkg` | PLATEAU land-use zones |
| Urban planning | `data/hiroshima_urf.gpkg` | Use districts, etc. |
| Code lists | `data/codelists/` | XML mapping attribute codes to Japanese labels |
| Shelters | `data/related/shelter.geojson` | Designated evacuation shelters in Hiroshima |
| Stations | `data/related/station.geojson` | Stations and rail lines in Hiroshima |
| Emergency routes | `data/related/emergency_route.geojson` | Hiroshima's emergency transport road network |
| Parks | `data/related/park.geojson` | Parks in Hiroshima |
| Landmarks | `data/related/landmark.geojson` | Major landmarks in Hiroshima |

All datasets are derived from **"3D City Model (Project PLATEAU) Hiroshima
City (FY2022)"**, provided by the City Bureau, Ministry of Land,
Infrastructure, Transport and Tourism (MLIT), Japan, under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/):
[https://www.geospatial.jp/ckan/dataset/plateau-34100-hiroshima-shi-2022](https://www.geospatial.jp/ckan/dataset/plateau-34100-hiroshima-shi-2022)

Basemap tiles in the Web UI are © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.

---

## License

- **Code:** [MIT License](LICENSE).
- **Data:** derived from *"3D City Model (Project PLATEAU) Hiroshima City
  (FY2022)"* (MLIT City Bureau), licensed under
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — see
  [Data used](#data-used) above for attribution and the source link. The CC BY
  4.0 terms apply to that data independently of the MIT license on the code.
