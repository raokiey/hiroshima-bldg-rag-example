"""Shared DuckDB connection helpers and data-file paths for the pipeline and API.

This module exists because both `src/pipeline/*` (batch scripts that build
`plateau_rag.duckdb`) and `src/app/*` (the FastAPI server that queries it) need the
same connection/path logic. Keeping it here avoids the runtime package depending on
pipeline-only modules.

All paths below default to the Hiroshima sample dataset shipped in `data/`, but can
be overridden per-invocation (pipeline scripts add `argparse` flags for these) or
globally via the `PLATEAU_*` environment variables listed next to each constant —
this is what lets the same code index a different city's PLATEAU export without
edits. The five `data/related/` GeoJSON files follow PLATEAU's standard
`{city-code}_{city-name}_city_{year}_{dataset}.geojson` naming convention, so
swapping cities only requires changing `CITY_PREFIX` rather than five separate
paths.
"""

import os
from pathlib import Path

import duckdb
from dotenv import load_dotenv

# Loaded here (rather than left to callers) because the PLATEAU_* path
# constants below are resolved at import time, and this module is often the
# first thing imported (e.g. src/app/main.py imports it before src/app/retrieval.py,
# which is where .env loading used to happen).
load_dotenv()

# `db.py` lives at src/common/db.py, so the repo root is two levels up.
ROOT = Path(__file__).parent.parent.parent
DATA_DIR = ROOT / "data"

GPKG_PATH = Path(os.getenv("PLATEAU_GPKG_PATH", DATA_DIR / "hiroshima_sample.gpkg"))
MAXLOD_GPKG_PATH = Path(
    os.getenv("PLATEAU_MAXLOD_GPKG_PATH", DATA_DIR / "hiroshima_sample_maxlod.gpkg")
)
LANDUSE_GPKG_PATH = Path(
    os.getenv("PLATEAU_LANDUSE_GPKG_PATH", DATA_DIR / "hiroshima_landuse.gpkg")
)
URF_GPKG_PATH = Path(os.getenv("PLATEAU_URF_GPKG_PATH", DATA_DIR / "hiroshima_urf.gpkg"))

RELATED_DATA_DIR = Path(os.getenv("PLATEAU_RELATED_DATA_DIR", DATA_DIR / "related"))
CITY_PREFIX = os.getenv("PLATEAU_CITY_PREFIX", "34100_hiroshima-shi_city_2022")


def related_path(dataset: str) -> Path:
    """Build a `data/related/` GeoJSON path from `CITY_PREFIX` + a dataset name.

    Args:
        dataset: The PLATEAU related-dataset suffix, e.g. `"shelter"`, `"station"`.

    Returns:
        `RELATED_DATA_DIR / f"{CITY_PREFIX}_{dataset}.geojson"`.
    """
    return RELATED_DATA_DIR / f"{CITY_PREFIX}_{dataset}.geojson"


SHELTER_PATH = related_path("shelter")
STATION_PATH = related_path("station")
EMROUTE_PATH = related_path("emergency_route")
PARK_PATH = related_path("park")
LANDMARK_PATH = related_path("landmark")

RAG_DB_PATH = Path(os.getenv("PLATEAU_DB_PATH", ROOT / "output" / "plateau_rag.duckdb"))


def connect_rag(db_path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open a connection to the persisted RAG database.

    Loads the `spatial` and `vss` extensions and enables experimental HNSW index
    persistence, which DuckDB 1.5.0 requires for the on-disk vector index used by
    `building_chunks` to survive across connections.

    Args:
        db_path: DuckDB file to connect to. Defaults to `RAG_DB_PATH` (itself
            overridable via the `PLATEAU_DB_PATH` environment variable).

    Returns:
        An open DuckDB connection with spatial/vector search extensions loaded.
    """
    path = db_path if db_path is not None else RAG_DB_PATH
    path.parent.mkdir(exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("INSTALL vss; LOAD vss;")
    con.execute("SET hnsw_enable_experimental_persistence = true;")
    return con


def wgs84_to_epsg6671(
    con: duckdb.DuckDBPyConnection, lon: float, lat: float
) -> tuple[float, float]:
    """Convert a WGS84 (EPSG:4326) coordinate to EPSG:6671 (Japan Plane Rectangular).

    Args:
        con: An open DuckDB connection with the `spatial` extension loaded.
        lon: Longitude in WGS84 degrees.
        lat: Latitude in WGS84 degrees.

    Returns:
        A tuple `(x, y)` in EPSG:6671 meters.
    """
    # EPSG:4326's axis order is (lat, lon), so always_xy=true is required to force
    # the (lon, lat) = (X, Y) order our POINT() string assumes.
    row = con.execute(
        """
        SELECT
            ST_X(ST_Transform(
                ST_GeomFromText('POINT(' || $lon || ' ' || $lat || ')'),
                'EPSG:4326',
                'EPSG:6671',
                always_xy := true
            )) AS x,
            ST_Y(ST_Transform(
                ST_GeomFromText('POINT(' || $lon || ' ' || $lat || ')'),
                'EPSG:4326',
                'EPSG:6671',
                always_xy := true
            )) AS y
        """,
        {"lon": lon, "lat": lat},
    ).fetchone()
    x, y = float(row[0]), float(row[1])
    return x, y
