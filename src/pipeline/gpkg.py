"""GeoPackage spatial queries: buildings/roads within a radius, with risk data.

Converts a WGS84 input point to EPSG:6671 (meters), filters buildings/roads with
`ST_DWithin`, and aggregates risk attributes into the shape `enrichment.py`
(the next pipeline stage) expects.
"""

import argparse
import duckdb
import pyarrow as pa
from pathlib import Path
from src.common.db import GPKG_PATH, wgs84_to_epsg6671

# --- Valid EPSG:6671 range for Hiroshima (Japan Plane Rectangular CS zone 3) ---
# Central meridian 132°10'E means Hiroshima's X is positive (~+20,000 to +40,000 m).
# Measured from the sample GPKG: X in [26031, 28381], Y in [-178471, -177405].
HIROSHIMA_X_MIN = 0.0        # East-west (m)
HIROSHIMA_X_MAX = 60_000.0
HIROSHIMA_Y_MIN = -230_000.0  # North-south (m)
HIROSHIMA_Y_MAX = -150_000.0


# ============================================================
# Coordinate transform utilities
# ============================================================

def connect() -> duckdb.DuckDBPyConnection:
    """Open an in-memory DuckDB connection with the `spatial` extension loaded.

    Returns:
        A DuckDB connection ready to query the GeoPackage via `st_read()`.
    """
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    return con

# wgs84_to_epsg6671() moved to src/common/db.py since runtime
# modules (src/app/*) need it too, not just this pipeline script.


def validate_epsg6671_range(x: float, y: float) -> bool:
    """Check that a converted coordinate falls within Hiroshima's valid range.

    Args:
        x: EPSG:6671 X (meters).
        y: EPSG:6671 Y (meters).

    Returns:
        True if in range.

    Raises:
        ValueError: If the coordinate is outside Hiroshima's expected bounds —
            usually a sign that the wrong CRS or axis order was used upstream.
    """
    in_range = (
        HIROSHIMA_X_MIN <= x <= HIROSHIMA_X_MAX
        and HIROSHIMA_Y_MIN <= y <= HIROSHIMA_Y_MAX
    )
    if not in_range:
        raise ValueError(
            f"EPSG:6671 座標が広島市の妥当範囲外: x={x:.1f}, y={y:.1f}  "
            f"（期待範囲: X=[{HIROSHIMA_X_MIN}, {HIROSHIMA_X_MAX}], "
            f"Y=[{HIROSHIMA_Y_MIN}, {HIROSHIMA_Y_MAX}]）"
        )
    return True


# ============================================================
# Building radius search
# ============================================================

def search_buildings_within(
    con: duckdb.DuckDBPyConnection,
    lon: float,
    lat: float,
    radius_m: float,
) -> pa.Table:
    """Find buildings within `radius_m` meters of a WGS84 point.

    Args:
        con: An open DuckDB connection with the `spatial` extension loaded.
        lon: Query point longitude (WGS84).
        lat: Query point latitude (WGS84).
        radius_m: Search radius in meters.

    Returns:
        A pyarrow.Table (zero-copy from DuckDB) with a `dist_m` column, sorted
        by ascending distance.
    """
    x, y = wgs84_to_epsg6671(con, lon, lat)
    validate_epsg6671_range(x, y)

    result = con.execute(
        f"""
        SELECT
            b.id,
            b.geometry,
            b.usage,
            b.measuredHeight,
            b.storeysAboveGround,
            ST_Distance(b.geometry, ST_Point($x, $y)) AS dist_m
        FROM st_read('{GPKG_PATH}', layer='bldg:Building') b
        WHERE ST_DWithin(b.geometry, ST_Point($x, $y), $radius_m)
        ORDER BY dist_m
        """,
        {"x": x, "y": y, "radius_m": radius_m},
    ).arrow().read_all()

    return result


# ============================================================
# Radius search with risk attributes joined in
# ============================================================

def search_buildings_with_risk(
    con: duckdb.DuckDBPyConnection,
    lon: float,
    lat: float,
    radius_m: float,
) -> pa.Table:
    """Find buildings within radius, joined with risk and structure attributes.

    Each risk table is aggregated with a CTE before joining — a plain JOIN
    would fan out one building row per risk record when a building has
    multiple entries in the same risk table.

    Args:
        con: An open DuckDB connection with the `spatial` extension loaded.
        lon: Query point longitude (WGS84).
        lat: Query point latitude (WGS84).
        radius_m: Search radius in meters.

    Returns:
        A pyarrow.Table with building + flood/tsunami risk + structure columns.
    """
    x, y = wgs84_to_epsg6671(con, lon, lat)
    validate_epsg6671_range(x, y)

    result = con.execute(
        f"""
        WITH ht AS (
            -- Aggregate storm surge risk per building.
            SELECT
                parentId,
                MAX(depth)                             AS ht_depth_max,
                MAX(rank)                              AS ht_rank_worst,
                STRING_AGG(DISTINCT description, '|') AS ht_descriptions
            FROM st_read('{GPKG_PATH}', layer='uro:HighTideRiskAttribute')
            GROUP BY parentId
        ),
        rv AS (
            -- Aggregate river flooding risk per building.
            SELECT
                parentId,
                MAX(depth)                             AS rv_depth_max,
                MAX(rank)                              AS rv_rank_worst,
                STRING_AGG(DISTINCT description, '|') AS rv_descriptions
            FROM st_read('{GPKG_PATH}', layer='uro:RiverFloodingRiskAttribute')
            GROUP BY parentId
        ),
        ts AS (
            -- Aggregate tsunami risk per building.
            SELECT
                parentId,
                MAX(depth) AS ts_depth_max,
                MAX(rank)  AS ts_rank_worst
            FROM st_read('{GPKG_PATH}', layer='uro:TsunamiRiskAttribute')
            GROUP BY parentId
        ),
        det AS (
            -- Aggregate building structure/fire-resistance detail per building.
            SELECT
                parentId,
                MAX(buildingStructureType)  AS structure_type,
                MAX(fireproofStructureType) AS fire_proof
            FROM st_read('{GPKG_PATH}', layer='uro:BuildingDetailAttribute')
            GROUP BY parentId
        )
        SELECT
            b.id,
            b.geometry,
            b.usage,
            b.measuredHeight,
            b.storeysAboveGround,
            ht.ht_depth_max,
            ht.ht_rank_worst,
            ht.ht_descriptions,
            rv.rv_depth_max,
            rv.rv_rank_worst,
            rv.rv_descriptions,
            ts.ts_depth_max,
            ts.ts_rank_worst,
            det.structure_type,
            det.fire_proof,
            ST_Distance(b.geometry, ST_Point($x, $y)) AS dist_m
        FROM st_read('{GPKG_PATH}', layer='bldg:Building') b
        LEFT JOIN ht  ON b.id = ht.parentId
        LEFT JOIN rv  ON b.id = rv.parentId
        LEFT JOIN ts  ON b.id = ts.parentId
        LEFT JOIN det ON b.id = det.parentId
        WHERE ST_DWithin(b.geometry, ST_Point($x, $y), $radius_m)
        ORDER BY dist_m
        """,
        {"x": x, "y": y, "radius_m": radius_m},
    ).arrow().read_all()

    return result


# ============================================================
# Road proximity search
# ============================================================

def search_roads_near(
    con: duckdb.DuckDBPyConnection,
    x: float,
    y: float,
    radius_m: float,
) -> pa.Table:
    """Find roads within `radius_m` meters of an already-converted point.

    Args:
        con: An open DuckDB connection with the `spatial` extension loaded.
        x: Query point X in EPSG:6671 meters (already converted, unlike the
            building search functions — callers typically already have this
            from a prior `wgs84_to_epsg6671()` call).
        y: Query point Y in EPSG:6671 meters.
        radius_m: Search radius in meters.

    Returns:
        A pyarrow.Table with a `traffic_area_json` column holding the raw
        VARCHAR `trafficArea` field (kept as JSON text, not parsed here).
    """
    # `width` is not a column of tran:Road itself — it lives in the separate
    # uro:RoadStructureAttribute extension layer, joined via parentId (same
    # pattern as enrichment.py's nearest_road CTE). parentId is 1:1 with
    # tran:Road.id here, so the LEFT JOIN can't duplicate rows.
    result = con.execute(
        f"""
        SELECT
            r.id,
            r.geometry,
            r.function,
            rs.width,
            r.trafficArea      AS traffic_area_json,
            ST_Distance(r.geometry, ST_Point($x, $y)) AS dist_m
        FROM st_read('{GPKG_PATH}', layer='tran:Road') r
        LEFT JOIN st_read('{GPKG_PATH}', layer='uro:RoadStructureAttribute') rs
               ON r.id = rs.parentId
        WHERE ST_DWithin(r.geometry, ST_Point($x, $y), $radius_m)
        ORDER BY dist_m
        """,
        {"x": x, "y": y, "radius_m": radius_m},
    ).arrow().read_all()

    return result


# ============================================================
# Combined entry point
# ============================================================

def build_spatial_context(
    con: duckdb.DuckDBPyConnection,
    lon: float,
    lat: float,
    radius_m: float = 500.0,
) -> dict:
    """Build the building/road search bundle handed off to `enrichment.py`.

    Args:
        con: An open DuckDB connection with the `spatial` extension loaded.
        lon: Query point longitude (WGS84).
        lat: Query point latitude (WGS84).
        radius_m: Search radius in meters.

    Returns:
        A dict with `query_point` (lon/lat/x_epsg6671/y_epsg6671/radius_m),
        `buildings` (pyarrow.Table), `roads` (pyarrow.Table), and `metadata`
        (building_count/road_count/risk_coverage per hazard type).
    """
    x, y = wgs84_to_epsg6671(con, lon, lat)
    validate_epsg6671_range(x, y)

    buildings = search_buildings_with_risk(con, lon, lat, radius_m)
    roads = search_roads_near(con, x, y, radius_m)

    # Count non-NULL risk values as a rough coverage indicator.
    bldg_dict = buildings.to_pydict()
    ht_cov = sum(1 for v in bldg_dict.get("ht_depth_max", []) if v is not None)
    rv_cov = sum(1 for v in bldg_dict.get("rv_depth_max", []) if v is not None)
    ts_cov = sum(1 for v in bldg_dict.get("ts_depth_max", []) if v is not None)

    return {
        "query_point": {
            "lon": lon,
            "lat": lat,
            "x_epsg6671": x,
            "y_epsg6671": y,
            "radius_m": radius_m,
        },
        "buildings": buildings,
        "roads": roads,
        "metadata": {
            "building_count": len(buildings),
            "road_count": len(roads),
            "risk_coverage": {
                "high_tide": ht_cov,
                "river": rv_cov,
                "tsunami": ts_cov,
            },
        },
    }


# ============================================================
# Entry point (manual verification)
# ============================================================

def run_spatial_demo() -> dict:
    """Run every spatial-query verification and return the final spatial context.

    Returns:
        The `build_spatial_context()` result for the test point.
    """
    con = connect()

    # --- 座標変換確認 ---
    print("\n" + "=" * 60)
    print("座標変換ユーティリティ確認")
    print("=" * 60)
    # Test conversion using Hiroshima Castle (132.459, 34.385).
    test_lon, test_lat = 132.459, 34.385
    x, y = wgs84_to_epsg6671(con, test_lon, test_lat)
    print(f"  入力: lon={test_lon}, lat={test_lat}")
    print(f"  変換後: x={x:.2f}, y={y:.2f} (EPSG:6671)")
    validate_epsg6671_range(x, y)
    print(f"  [OK] 妥当範囲内")

    # --- 建物範囲検索確認 ---
    print("\n" + "=" * 60)
    print("建物範囲検索確認")
    print("=" * 60)
    bldg_500 = search_buildings_within(con, test_lon, test_lat, 500.0)
    bldg_1000 = search_buildings_within(con, test_lon, test_lat, 1000.0)
    print(f"  半径 500m: {len(bldg_500):,} 件")
    print(f"  半径 1000m: {len(bldg_1000):,} 件")
    print(f"  カラム: {bldg_500.schema.names}")

    # --- リスク属性込み検索確認 ---
    print("\n" + "=" * 60)
    print("リスク属性込み建物検索確認")
    print("=" * 60)
    bldg_risk = search_buildings_with_risk(con, test_lon, test_lat, 500.0)
    print(f"  件数: {len(bldg_risk):,}")
    print(f"  カラム: {bldg_risk.schema.names}")
    d = bldg_risk.to_pydict()
    ht_nn = sum(1 for v in d.get("ht_depth_max", []) if v is not None)
    rv_nn = sum(1 for v in d.get("rv_depth_max", []) if v is not None)
    ts_nn = sum(1 for v in d.get("ts_depth_max", []) if v is not None)
    print(f"  高潮リスク付き建物: {ht_nn} 件")
    print(f"  洪水リスク付き建物: {rv_nn} 件")
    print(f"  津波リスク付き建物: {ts_nn} 件")

    # --- 道路近接検索確認 ---
    print("\n" + "=" * 60)
    print("道路近接検索確認")
    print("=" * 60)
    roads = search_roads_near(con, x, y, 500.0)
    print(f"  半径 500m 道路件数: {len(roads):,}")
    print(f"  カラム: {roads.schema.names}")

    # --- 統合関数確認 ---
    print("\n" + "=" * 60)
    print("build_spatial_context 確認")
    print("=" * 60)
    ctx = build_spatial_context(con, test_lon, test_lat, 500.0)
    print(f"  query_point: {ctx['query_point']}")
    print(f"  metadata: {ctx['metadata']}")

    con.close()
    return ctx


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test coordinate transform and spatial search against a GeoPackage."
    )
    parser.add_argument(
        "--gpkg-path",
        type=Path,
        default=GPKG_PATH,
        help=f"Path to the building GeoPackage (default: {GPKG_PATH}).",
    )
    args = parser.parse_args()
    GPKG_PATH = args.gpkg_path

    run_spatial_demo()
