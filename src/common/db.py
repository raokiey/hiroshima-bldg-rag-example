"""Shared DuckDB connection helpers used by both the offline pipeline and the runtime API.

This module exists because both `src/pipeline/*` (batch scripts that build
`plateau_rag.duckdb`) and `src/app/*` (the FastAPI server that queries it) need the
same connection/path logic. Keeping it here avoids the runtime package depending on
pipeline-only modules.
"""

from pathlib import Path

import duckdb

# `db.py` lives at src/common/db.py, so the repo root is two levels up.
ROOT = Path(__file__).parent.parent.parent
RAG_DB_PATH = ROOT / "output" / "plateau_rag.duckdb"


def connect_rag() -> duckdb.DuckDBPyConnection:
    """Open a connection to the persisted RAG database.

    Loads the `spatial` and `vss` extensions and enables experimental HNSW index
    persistence, which DuckDB 1.5.0 requires for the on-disk vector index used by
    `building_chunks` to survive across connections.

    Returns:
        An open DuckDB connection with spatial/vector search extensions loaded.
    """
    RAG_DB_PATH.parent.mkdir(exist_ok=True)
    con = duckdb.connect(str(RAG_DB_PATH))
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
