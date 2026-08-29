"""Precomputes inter-building spatial context into `building_context_meta`.

Precomputes spatial relationships between buildings — south-side shading,
neighbor density, nearest facility by type — that a single building's own
attributes (see `geometry.py`'s `building_geom_meta`) can't express alone.

Uses no additional data sources: derives facility categories (school,
hospital, police, fire, post office) from the "種類" (type) field already
present in `data/related/34100_hiroshima-shi_city_2022_landmark.geojson`.
"""

import duckdb
import numpy as np
import pandas as pd
from pathlib import Path

from src.common.db import connect_rag
from src.pipeline.enrichment import GPKG_PATH, LANDMARK_PATH
from src.pipeline.gpkg import connect as connect_gpkg

# `context.py` lives at src/pipeline/context.py, so the repo root is three
# levels up.
ROOT = Path(__file__).parent.parent.parent

# Provisional threshold derived from Hiroshima's winter solstice solar
# elevation (~32.2°).
_WINTER_SUN_THRESHOLD_DEG = 30.0

# Major road definition. The original plan was to use
# uro:RoadStructureAttribute's width/numberOfLanes, but in this sample both
# columns are NULL for every row (0 of 846 non-NULL), making them unusable.
# Instead, treats tran:Road.function codes "2" (national highway) and "3"
# (prefectural road) — per codelists/Road_function.xml — as "major roads"
# (96 of 846 roads match; "1" = expressway doesn't appear in this sample).
_MAJOR_ROAD_FUNCTIONS = ("2", "3")

# landmark.geojson "種類" (type) -> internal category name mapping.
_FACILITY_CATEGORY_MAP = {
    "学校": "school",
    "病院": "hospital",
    "警察署": "police",
    "消防署": "fire",
    "郵便局": "post",
}


# ============================================================
# Table definition
# ============================================================

def create_context_meta_table(rag_con: duckdb.DuckDBPyConnection) -> None:
    """Create the `building_context_meta` table, dropping any existing one first.

    Args:
        rag_con: An open connection from `connect_rag()`.
    """
    rag_con.execute("DROP TABLE IF EXISTS building_context_meta;")
    rag_con.execute("""
    CREATE TABLE building_context_meta (
        id                         VARCHAR PRIMARY KEY,
        south_max_elev_angle_deg   DOUBLE,   -- Max elevation angle (deg) to a neighbor within the south sector (135-225°). 0.0 if no neighbors.
        winter_sunlit              BOOLEAN,  -- Whether sunlight reaches at winter solstice noon (treated as clear if elevation angle < 30°).
        prominence_m               DOUBLE,   -- This building's top elevation minus the tallest neighbor's (within 100m).
        wooden_density_ratio       DOUBLE,   -- Fraction of neighbors (within 100m) that are wood-frame construction (0-1). NULL if no neighbors.
        nearest_major_road_dist_m  DOUBLE,   -- Distance (m) to the nearest major road (tran:Road.function IN ('2','3')).
        nearest_school_name        VARCHAR,
        nearest_school_dist_m      DOUBLE,
        nearest_hospital_name      VARCHAR,
        nearest_hospital_dist_m    DOUBLE,
        nearest_police_name        VARCHAR,
        nearest_police_dist_m      DOUBLE,
        nearest_fire_name          VARCHAR,
        nearest_fire_dist_m        DOUBLE,
        nearest_post_name          VARCHAR,
        nearest_post_dist_m        DOUBLE
    );
    """)
    print("  テーブル building_context_meta 作成完了")


# ============================================================
# Neighbor pair extraction
# ============================================================

def fetch_neighbor_pairs(rag_con: duckdb.DuckDBPyConnection, radius_m: float = 100.0) -> pd.DataFrame:
    """Self-join building centroids to find all neighbor pairs within radius.

    Args:
        rag_con: An open connection from `connect_rag()`.
        radius_m: Maximum distance between a pair to be included.

    Returns:
        A DataFrame with `id`, `neighbor_id`, `dist_m`, `dx`, `dy` columns.
        `dx`/`dy` are the east-west/north-south differences (EPSG:6671: x=east,
        y=north); callers compute azimuth the same way as
        `geometry.wall_azimuth_deg()` (`atan2(dx, dy) % 360`, 0°=north,
        clockwise).
    """
    df = rag_con.execute(
        """
        SELECT ca.id AS id, cb.id AS neighbor_id,
               ST_Distance(ca.c, cb.c) AS dist_m,
               ST_X(cb.c) - ST_X(ca.c) AS dx,
               ST_Y(cb.c) - ST_Y(ca.c) AS dy
        FROM (SELECT id, ST_Centroid(geometry) AS c FROM building_chunks) ca
        JOIN (SELECT id, ST_Centroid(geometry) AS c FROM building_chunks) cb
          ON ca.id <> cb.id AND ST_DWithin(ca.c, cb.c, ?)
        """,
        [radius_m],
    ).df()
    return df


def _load_top_elevations(rag_con: duckdb.DuckDBPyConnection) -> dict:
    """Build an id -> top_elev_m (ground elevation + building height) map.

    Buildings with a NULL `building_height_m` or `ground_elev_m` are excluded.

    Args:
        rag_con: An open connection from `connect_rag()`.

    Returns:
        A dict mapping building id to its rooftop elevation.
    """
    df = rag_con.execute("""
        SELECT id, ground_elev_m, building_height_m
        FROM building_geom_meta
        WHERE building_height_m IS NOT NULL AND ground_elev_m IS NOT NULL
    """).df()
    df["top_elev_m"] = df["ground_elev_m"] + df["building_height_m"]
    return dict(zip(df["id"], df["top_elev_m"]))


# ============================================================
# South-side shading, prominence, wooden density
# ============================================================

def compute_south_shading(
    pairs_df: pd.DataFrame,
    top_elev_map: dict,
    ground_elev_map: dict,
) -> pd.DataFrame:
    """Compute the max elevation angle to a neighbor within the south sector.

    Elevation angle = atan2(neighbor's top elevation - self's ground
    elevation, horizontal distance), clipped to a minimum of 0.

    Args:
        pairs_df: Output of `fetch_neighbor_pairs()`.
        top_elev_map: id -> top elevation, from `_load_top_elevations()`.
        ground_elev_map: id -> ground elevation.

    Returns:
        A DataFrame with `id`, `south_max_elev_angle_deg`, `winter_sunlit`
        columns. IDs with zero south-side neighbors or missing elevation data
        are absent — callers should `fillna(0.0)` / `fillna(True)`.
    """
    df = pairs_df.copy()
    df["az"] = np.degrees(np.arctan2(df["dx"], df["dy"])) % 360.0
    south = df[(df["az"] >= 135.0) & (df["az"] < 225.0)].copy()

    south["neighbor_top"] = south["neighbor_id"].map(top_elev_map)
    south["self_ground"] = south["id"].map(ground_elev_map)
    south = south.dropna(subset=["neighbor_top", "self_ground"])

    south["elev_angle"] = np.degrees(np.arctan2(
        south["neighbor_top"] - south["self_ground"], south["dist_m"]
    )).clip(lower=0.0)

    result = south.groupby("id")["elev_angle"].max().rename("south_max_elev_angle_deg").reset_index()
    result["winter_sunlit"] = result["south_max_elev_angle_deg"] < _WINTER_SUN_THRESHOLD_DEG
    return result


def compute_prominence(pairs_df: pd.DataFrame, top_elev_map: dict) -> pd.DataFrame:
    """Compute this building's top elevation minus the tallest neighbor's (any direction).

    Args:
        pairs_df: Output of `fetch_neighbor_pairs()`.
        top_elev_map: id -> top elevation, from `_load_top_elevations()`.

    Returns:
        A DataFrame with `id`, `prominence_m` columns. Isolated buildings
        (zero neighbors) are absent — callers should fall back to the
        building's own `building_height_m`.
    """
    df = pairs_df.copy()
    df["neighbor_top"] = df["neighbor_id"].map(top_elev_map)
    df = df.dropna(subset=["neighbor_top"])

    agg = df.groupby("id")["neighbor_top"].max().rename("neighbor_max_top").reset_index()
    agg["self_top"] = agg["id"].map(top_elev_map)
    agg["prominence_m"] = agg["self_top"] - agg["neighbor_max_top"]
    return agg[["id", "prominence_m"]]


def compute_wooden_density(pairs_df: pd.DataFrame, structure_map: dict) -> pd.DataFrame:
    """Compute the fraction of nearby (within 100m) buildings that are wood-frame.

    Args:
        pairs_df: Output of `fetch_neighbor_pairs()`.
        structure_map: id -> structure type label.

    Returns:
        A DataFrame with `id`, `wooden_density_ratio` columns. IDs with zero
        neighbors are absent (equivalent to NULL).
    """
    df = pairs_df.copy()
    df["neighbor_wood"] = df["neighbor_id"].map(structure_map) == "木造・土蔵造"
    agg = df.groupby("id")["neighbor_wood"].mean().rename("wooden_density_ratio").reset_index()
    return agg


# ============================================================
# Major road distance and nearest facility by type
# ============================================================

def _is_major_road_function(function_raw) -> bool:
    """Check whether a road's `function` code is a major road.

    The `function` column is stored as a JSON-array string like '["2"]', so a
    plain SQL `IN` comparison won't match — this parses it in Python instead.
    """
    import json
    if function_raw is None:
        return False
    try:
        codes = json.loads(function_raw)
    except Exception:
        return False
    return any(str(c) in _MAJOR_ROAD_FUNCTIONS for c in codes)


def compute_major_road_dist(gpkg_con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Compute the nearest-major-road distance for every building.

    "Major road" means `tran:Road.function` contains '2' (national highway)
    or '3' (prefectural road). Since `function` is a JSON-array string, this
    filters it in Python first and passes the matching ids into a SQL `IN`
    clause (same CROSS JOIN + GROUP BY pattern as `enrichment.py`'s
    `nearest_road`).

    Args:
        gpkg_con: An in-memory DuckDB connection with the `spatial`
            extension loaded, for reading the raw GPKG.

    Returns:
        A DataFrame with `id`, `nearest_major_road_dist_m` columns. If no
        roads match the major-road criteria, every value is NULL (and a
        warning is printed) rather than raising.
    """
    gpkg = str(GPKG_PATH).replace("\\", "/")

    df_roads = gpkg_con.execute(
        f"SELECT id, function FROM st_read('{gpkg}', layer='tran:Road')"
    ).df()
    major_ids = df_roads.loc[df_roads["function"].apply(_is_major_road_function), "id"].tolist()

    if not major_ids:
        print(f"  [WARN] 幹線道路（function IN {_MAJOR_ROAD_FUNCTIONS}）が0件のため "
              "nearest_major_road_dist_m は全件NULLになります")
        ids = gpkg_con.execute(f"SELECT id FROM st_read('{gpkg}', layer='bldg:Building')").df()
        ids["nearest_major_road_dist_m"] = np.nan
        return ids[["id", "nearest_major_road_dist_m"]]

    placeholders = ", ".join(["?" for _ in major_ids])
    df = gpkg_con.execute(
        f"""
        SELECT b.id AS id,
               MIN(ST_Distance(b.centroid, r.geometry)) AS nearest_major_road_dist_m
        FROM (SELECT id, ST_Centroid(geometry) AS centroid FROM st_read('{gpkg}', layer='bldg:Building')) b
        CROSS JOIN (
            SELECT geometry FROM st_read('{gpkg}', layer='tran:Road') WHERE id IN ({placeholders})
        ) r
        GROUP BY b.id
        """,
        major_ids,
    ).df()
    print(f"  幹線道路（該当 {len(major_ids)} 本）までの最近傍距離を計算しました")
    return df


def compute_nearest_facility(
    gpkg_con: duckdb.DuckDBPyConnection,
    landmark_path: Path = LANDMARK_PATH,
    category_map: dict = _FACILITY_CATEGORY_MAP,
) -> dict[str, pd.DataFrame]:
    """Compute the nearest facility of each category (school/hospital/etc.).

    Filters `landmark.geojson` by its "種類" (type) column per category, then
    uses the same CROSS JOIN + ARG_MIN pattern (with WGS84->EPSG:6671
    conversion) as `enrichment.py`'s `nearest_shelter` and similar functions.

    Args:
        gpkg_con: An in-memory DuckDB connection with the `spatial`
            extension loaded.
        landmark_path: Path to the landmark GeoJSON.
        category_map: Japanese type label -> internal category name.

    Returns:
        A dict mapping category name to a DataFrame with `id`,
        `nearest_{cat}_name`, `nearest_{cat}_dist_m` columns.
    """
    gpkg = str(GPKG_PATH).replace("\\", "/")
    lm = str(landmark_path).replace("\\", "/")

    result: dict[str, pd.DataFrame] = {}
    for jp_type, cat in category_map.items():
        df = gpkg_con.execute(
            f"""
            SELECT b.id AS id,
                   MIN(ST_Distance(b.centroid, f.geom_6671))
                       AS nearest_{cat}_dist_m,
                   ARG_MIN(f.name, ST_Distance(b.centroid, f.geom_6671))
                       AS nearest_{cat}_name
            FROM (SELECT id, ST_Centroid(geometry) AS centroid FROM st_read('{gpkg}', layer='bldg:Building')) b
            CROSS JOIN (
                SELECT "名称" AS name,
                       ST_Transform(geom, 'EPSG:4326', 'EPSG:6671', always_xy := true) AS geom_6671
                FROM st_read('{lm}')
                WHERE "種類" = ?
            ) f
            GROUP BY b.id
            """,
            [jp_type],
        ).df()
        result[cat] = df
        print(f"  最近傍施設（{jp_type}）計算完了")
    return result


# ============================================================
# Combine and save
# ============================================================

def build_context_meta(
    rag_con: duckdb.DuckDBPyConnection,
    gpkg_con: duckdb.DuckDBPyConnection,
) -> pd.DataFrame:
    """Left-join every computed metric into one DataFrame, keyed by id.

    Args:
        rag_con: An open connection from `connect_rag()`.
        gpkg_con: An in-memory DuckDB connection with the `spatial`
            extension loaded, for reading the raw GPKG/GeoJSON sources.

    Returns:
        One row per building in `building_chunks`, with all context columns.
    """
    base_ids = rag_con.execute("SELECT id FROM building_chunks").df()

    print("  近傍ペア抽出中（半径100m）...")
    pairs = fetch_neighbor_pairs(rag_con, radius_m=100.0)
    print(f"  近傍ペア: {len(pairs):,} 組")

    top_elev_map = _load_top_elevations(rag_con)
    geom_df = rag_con.execute(
        "SELECT id, ground_elev_m, building_height_m FROM building_geom_meta"
    ).df()
    ground_elev_map = dict(zip(geom_df["id"], geom_df["ground_elev_m"]))
    height_map = dict(zip(geom_df["id"], geom_df["building_height_m"]))
    structure_df = rag_con.execute("SELECT id, structure_type FROM building_chunks").df()
    structure_map = dict(zip(structure_df["id"], structure_df["structure_type"]))

    print("  南側遮蔽を計算中...")
    shading = compute_south_shading(pairs, top_elev_map, ground_elev_map)
    print("  卓越性を計算中...")
    prominence = compute_prominence(pairs, top_elev_map)
    print("  木造密度を計算中...")
    wooden = compute_wooden_density(pairs, structure_map)
    print("  幹線道路距離を計算中...")
    major_road = compute_major_road_dist(gpkg_con)
    print("  施設種別最近傍を計算中...")
    facilities = compute_nearest_facility(gpkg_con)

    df = base_ids.merge(shading, on="id", how="left")
    df = df.merge(prominence, on="id", how="left")
    df = df.merge(wooden, on="id", how="left")
    df = df.merge(major_road, on="id", how="left")
    for cat_df in facilities.values():
        df = df.merge(cat_df, on="id", how="left")

    # Zero south-side neighbors -> no shading (elevation angle 0.0, sunlit).
    df["south_max_elev_angle_deg"] = df["south_max_elev_angle_deg"].fillna(0.0)
    df["winter_sunlit"] = df["winter_sunlit"].fillna(True)

    # Isolated buildings (zero neighbors) -> prominence_m falls back to the
    # building's own height.
    no_neighbor = df["prominence_m"].isna()
    df.loc[no_neighbor, "prominence_m"] = df.loc[no_neighbor, "id"].map(height_map)

    return df[[
        "id", "south_max_elev_angle_deg", "winter_sunlit", "prominence_m",
        "wooden_density_ratio", "nearest_major_road_dist_m",
        "nearest_school_name", "nearest_school_dist_m",
        "nearest_hospital_name", "nearest_hospital_dist_m",
        "nearest_police_name", "nearest_police_dist_m",
        "nearest_fire_name", "nearest_fire_dist_m",
        "nearest_post_name", "nearest_post_dist_m",
    ]]


def save_context_meta(rag_con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> None:
    """Bulk-insert into `building_context_meta` and print a summary.

    Args:
        rag_con: An open connection from `connect_rag()`.
        df: Output of `build_context_meta()`.
    """
    rag_con.register("_tmp_context", df)
    rag_con.execute("""
        INSERT INTO building_context_meta
        SELECT id, south_max_elev_angle_deg, winter_sunlit, prominence_m,
               wooden_density_ratio, nearest_major_road_dist_m,
               nearest_school_name, nearest_school_dist_m,
               nearest_hospital_name, nearest_hospital_dist_m,
               nearest_police_name, nearest_police_dist_m,
               nearest_fire_name, nearest_fire_dist_m,
               nearest_post_name, nearest_post_dist_m
        FROM _tmp_context
    """)
    rag_con.unregister("_tmp_context")

    cnt = rag_con.execute("SELECT COUNT(*) FROM building_context_meta").fetchone()[0]
    print(f"  [OK] building_context_meta 保存完了: {cnt} 件")

    stats = rag_con.execute("""
        SELECT
            AVG(CASE WHEN winter_sunlit THEN 1.0 ELSE 0.0 END) AS sunlit_rate,
            AVG(prominence_m) AS prominence_mean,
            COUNT(nearest_major_road_dist_m) AS n_major_road,
            COUNT(nearest_school_dist_m) AS n_school,
            COUNT(nearest_hospital_dist_m) AS n_hospital,
            COUNT(nearest_police_dist_m) AS n_police,
            COUNT(nearest_fire_dist_m) AS n_fire,
            COUNT(nearest_post_dist_m) AS n_post,
            COUNT(wooden_density_ratio) AS n_wooden_density
        FROM building_context_meta
    """).fetchone()

    print(f"\n  【統計サマリー】")
    print(f"  ・冬日照確保率（winter_sunlit=True）: {stats[0]*100:.1f}%")
    print(f"  ・卓越性（prominence_m）平均: {stats[1]:.1f}m")
    print(f"  ・nearest_major_road_dist_m 非NULL: {stats[2]} 件")
    print(f"  ・nearest_school_dist_m 非NULL: {stats[3]} 件")
    print(f"  ・nearest_hospital_dist_m 非NULL: {stats[4]} 件")
    print(f"  ・nearest_police_dist_m 非NULL: {stats[5]} 件")
    print(f"  ・nearest_fire_dist_m 非NULL: {stats[6]} 件")
    print(f"  ・nearest_post_dist_m 非NULL: {stats[7]} 件")
    print(f"  ・wooden_density_ratio 非NULL（近傍あり）: {stats[8]} 件")


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Phase 13 > Step 13-2: 建物間コンテキスト計算 開始")
    print("=" * 60)

    rag_con = connect_rag()
    gpkg_con = connect_gpkg()

    print("  building_context_meta テーブルを初期化中...")
    create_context_meta_table(rag_con)

    df = build_context_meta(rag_con, gpkg_con)
    save_context_meta(rag_con, df)

    gpkg_con.close()
    rag_con.close()
    print("\n[SUCCESS] Phase 13 Step 13-2 完了")
