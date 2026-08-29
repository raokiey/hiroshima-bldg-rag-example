"""Extracts 3D building metadata from LOD2 geometry into `building_geom_meta`.

Parses MULTIPOLYGON Z from `hiroshima_sample_maxlod.gpkg` to derive per-building
ground elevation, height, wall orientation ratios, and roof area.

Also derives roof shape (slope / flat-roof classification), footprint area,
approximate volume, and a slenderness index — the regular (non-maxlod)
`hiroshima_sample.gpkg` building geometry is a flat footprint polygon (constant
Z=0, single polygon), so `ST_Area` after `ST_Force2D` gives footprint area
directly.

Also classifies footprint shape (circular / rectangular / L-shaped / U-shaped /
cross / star) from circularity, convexity ratio, and concave vertex count.
"""

import re
import math
import duckdb
import numpy as np
import pandas as pd
from pathlib import Path

from src.common.db import connect_rag
from src.pipeline.enrichment import GPKG_PATH

# `geometry.py` lives at src/pipeline/geometry.py, so the repo root is three
# levels up.
ROOT         = Path(__file__).parent.parent.parent
MAXLOD_PATH  = ROOT / "data" / "hiroshima_sample_maxlod.gpkg"

# Flat-roof classification threshold (fraction of roof area that's flat).
# Provisional value, confirmed against the real data distribution.
_FLAT_ROOF_RATIO_THRESHOLD = 0.7
# Upper bound (degrees) on the slope angle still considered "flat" roof.
_FLAT_ROOF_SLOPE_DEG = 10.0

# Footprint shape classification threshold: circularity at or above this is
# classified "円形に近い" (near-circular).
# A provisional 0.75 was found on 2026-08-26 to misclassify plain rectangular
# buildings (5-vertex footprints, i.e. 4 corners) as near-circular, since a
# square's circularity is π/4≈0.785. Raised to 0.85 to only catch buildings
# with genuinely many vertices (curved outlines) — in the real data,
# circularity>=0.85 matches only 9 buildings, all with 9+ vertices, with no
# rectangular buildings misclassified.
_CIRCULAR_THRESHOLD = 0.85
# When concave_vertex_count is 3-4: classify as "十字型・複雑形状" (cross) if
# convexity_ratio is at or above this, otherwise "星形・複雑形状" (star).
_CROSS_CONVEXITY_MIN = 0.6

# Oval classification threshold (box_fill_ratio = footprint_area_m2 / bbox_area_m2).
# bbox_area_m2 is the area of ST_MinimumRotatedRectangle (minimum bounding
# rectangle). For a circle or ellipse, the area ratio to its bounding
# rectangle converges to the theoretical π/4≈0.785 regardless of aspect ratio
# (unlike circularity, this is insensitive to eccentricity). A rectangle has
# box_fill_ratio≈1.0, so this range distinguishes ovals from rectangles
# around that 0.785 center point. Provisional range confirmed against the
# real data distribution on 2026-08-28.
_OVAL_BOX_FILL_MIN = 0.70
_OVAL_BOX_FILL_MAX = 0.85
# High-vertex-count curved footprints (a smooth curve approximated by many
# short edges) can accumulate many spurious "concave" vertices from
# digitization noise, inflating concave_vertex_count (e.g. 11 of 40 vertices
# flagged concave on a building that's still convexity_ratio=0.957, i.e.
# essentially convex). Requiring concave_vertex_count==0 would misclassify
# such round buildings as "星形・複雑形状" etc., so when vertex count is high
# and the shape is nearly convex, apply the box_fill_ratio oval test
# regardless of concave_vertex_count. Threshold confirmed on 2026-08-28
# against 38 real candidates with vertex count >=15 and convexity_ratio >=0.90.
_OVAL_NOISY_MIN_VERTEX = 15
_OVAL_NOISY_CONVEXITY_MIN = 0.90


# ============================================================
# Step 9-1: building_geom_meta table definition
# ============================================================

def create_geom_meta_table(rag_con: duckdb.DuckDBPyConnection) -> None:
    """Create the `building_geom_meta` table, dropping any existing one first.

    Args:
        rag_con: An open connection from `connect_rag()`.
    """
    rag_con.execute("DROP TABLE IF EXISTS building_geom_meta;")
    rag_con.execute("""
    CREATE TABLE building_geom_meta (
        id                  VARCHAR PRIMARY KEY,
        ground_elev_m       DOUBLE,   -- Ground elevation (min Z, meters).
        building_height_m   DOUBLE,   -- Building height (max Z - ground elevation).
        roof_area_m2        DOUBLE,   -- Total roof area (m²).
        wall_area_total_m2  DOUBLE,   -- Total wall area (m²).
        wall_ratio_n        DOUBLE,   -- North-facing wall area ratio 0-1 (azimuth 315-45°).
        wall_ratio_e        DOUBLE,   -- East-facing wall area ratio 0-1 (azimuth 45-135°).
        wall_ratio_s        DOUBLE,   -- South-facing wall area ratio 0-1 (azimuth 135-225°).
        wall_ratio_w        DOUBLE,   -- West-facing wall area ratio 0-1 (azimuth 225-315°).
        face_count          INTEGER,  -- Total face count.
        -- Roof shape, footprint area, and approximate volume.
        roof_slope_mean_deg DOUBLE,   -- Area-weighted mean roof slope (degrees). NULL if no roof faces.
        flat_roof_ratio     DOUBLE,   -- Flat (slope<10°) fraction of roof area 0-1. NULL if no roof faces.
        roof_type_est       VARCHAR,  -- '陸屋根' (flat) | '勾配屋根' (sloped), estimated from flat_roof_ratio. NULL if no roof faces.
        footprint_area_m2   DOUBLE,   -- Footprint area (2D projection from hiroshima_sample.gpkg, m²).
        volume_m3           DOUBLE,   -- Approximate volume (footprint_area_m2 x building_height_m; an approximation since the geometry isn't a closed solid).
        slenderness         DOUBLE,   -- Slenderness index: building_height_m / sqrt(footprint_area_m2).
        -- Footprint shape indicators (circular/rectangular/L-shaped/cross/star classification).
        footprint_perimeter_m    DOUBLE,   -- Footprint perimeter (m).
        convex_hull_area_m2      DOUBLE,   -- Footprint's convex hull area (m²).
        footprint_vertex_count   INTEGER,  -- Vertex count of the footprint's outer ring.
        concave_vertex_count     INTEGER,  -- Number of concave (reflex) vertices.
        circularity              DOUBLE,   -- Circularity = 4π*area / perimeter² (1.0 = perfect circle).
        convexity_ratio          DOUBLE,   -- Convexity ratio = area / convex_hull_area (1.0 = convex shape).
        -- Bounding-rectangle area/fill ratio, used for oval classification.
        bbox_area_m2             DOUBLE,   -- Minimum rotated bounding rectangle area (m²).
        box_fill_ratio           DOUBLE,   -- Fill ratio = footprint_area_m2 / bbox_area_m2
                                            -- (converges to π/4≈0.785 for circles/ellipses regardless of eccentricity).
        shape_type_est           VARCHAR   -- Estimated shape classification (円形に近い/楕円形/矩形・単純形状/
                                            -- L字型/コの字型・T字型/十字型・複雑形状/星形・複雑形状).
                                            -- A heuristic based on concave vertex count; does not guarantee a
                                            -- strict distinction between L/T/cross shapes.
    );
    """)


# ============================================================
# Step 9-1: WKT parser and Newell's method normal-vector calculation
# ============================================================

# Matches each polygon (outer ring only) within a MULTIPOLYGON Z.
_RING_RE = re.compile(r"\(([^()]+)\)")


def parse_multipolygon_z(wkt: str) -> list[list[tuple[float, float, float]]]:
    """Parse MULTIPOLYGON Z WKT into a list of per-face vertex lists.

    Only the outer ring (first ring) of each polygon is used.

    Args:
        wkt: A MULTIPOLYGON Z WKT string.

    Returns:
        One `[(x, y, z), ...]` list per face (polygon).
    """
    polys = []
    for ring_match in _RING_RE.finditer(wkt):
        coords_str = ring_match.group(1).strip()
        pts = []
        for token in coords_str.split(","):
            parts = token.split()
            if len(parts) >= 3:
                pts.append((float(parts[0]), float(parts[1]), float(parts[2])))
        if len(pts) >= 3:
            polys.append(pts)
    return polys


def newell_normal(pts: list[tuple]) -> np.ndarray:
    """Compute a face's normal vector via Newell's method (unnormalized).

    The returned vector's magnitude / 2 equals the 3D polygon's area. Works
    correctly for closed polygons (first and last vertex identical).

    Args:
        pts: The face's vertices as `(x, y, z)` tuples.

    Returns:
        The raw (non-unit) normal vector.
    """
    n = len(pts)
    nx = ny = nz = 0.0
    for i in range(n - 1):  # Skip the last vertex — it duplicates the first.
        cur = pts[i]
        nxt = pts[(i + 1) % (n - 1)] if n > 1 else pts[0]
        nx += (cur[1] - nxt[1]) * (cur[2] + nxt[2])
        ny += (cur[2] - nxt[2]) * (cur[0] + nxt[0])
        nz += (cur[0] - nxt[0]) * (cur[1] + nxt[1])
    return np.array([nx, ny, nz], dtype=np.float64)


def polygon_area(normal_raw: np.ndarray) -> float:
    """Convert a raw normal vector to a 3D polygon's area (m²)."""
    return float(np.linalg.norm(normal_raw)) / 2.0


def classify_face(nz_norm: float, nx_norm: float, ny_norm: float) -> str:
    """Classify a face by its normal's Z component: 'roof' / 'bottom' / 'wall'."""
    if nz_norm > 0.8:
        return "roof"
    if nz_norm < -0.8:
        return "bottom"
    return "wall"


def wall_azimuth_deg(nx_norm: float, ny_norm: float) -> float:
    """Compute a wall face's horizontal azimuth (degrees, 0°=north, clockwise).

    EPSG:6671 (JGD2011) uses x=east, y=north, so azimuth = atan2(nx, ny).

    Args:
        nx_norm: X component of the unit normal vector.
        ny_norm: Y component of the unit normal vector.

    Returns:
        Azimuth in degrees, normalized to [0, 360).
    """
    az = math.degrees(math.atan2(nx_norm, ny_norm))
    return az % 360.0


def azimuth_to_direction(az: float) -> str:
    """Map an azimuth angle to a cardinal direction label ('N'/'E'/'S'/'W')."""
    if az < 45.0 or az >= 315.0:
        return "N"
    if az < 135.0:
        return "E"
    if az < 225.0:
        return "S"
    return "W"


def estimate_roof_type(flat_roof_ratio: float | None) -> str | None:
    """Classify roof type from its flat-area ratio.

    Args:
        flat_roof_ratio: Fraction of roof area that's flat (slope < threshold),
            or None if the building has no roof faces.

    Returns:
        '陸屋根' (flat roof), '勾配屋根' (sloped roof), or None.
    """
    if flat_roof_ratio is None:
        return None
    return "陸屋根" if flat_roof_ratio >= _FLAT_ROOF_RATIO_THRESHOLD else "勾配屋根"


def count_concave_vertices(footprint_wkt: str | None) -> int | None:
    """Count concave (reflex) vertices in a footprint's outer ring.

    The geometry type is MULTIPOLYGON, and DuckDB's spatial extension has no
    `ST_GeometryN` (so `ST_ExteriorRing` can't be applied directly), so this
    extracts the first ring (= outer ring, assuming no holes) via regex, same
    approach as `parse_multipolygon_z()`. For each vertex, computes the sign
    of the cross product of its two adjacent edge vectors (only the Z
    component matters in 2D); a vertex is concave when its sign disagrees
    with the polygon's overall winding direction (majority sign across all
    vertices). The ring's duplicate closing point (start == end) is dropped
    before processing.

    Args:
        footprint_wkt: A 2D MULTIPOLYGON WKT string, or None.

    Returns:
        The concave vertex count, or None if the WKT is missing/degenerate
        (fewer than 3 vertices).
    """
    if not footprint_wkt:
        return None
    m = re.search(r"\(([^()]+)\)", footprint_wkt)
    if not m:
        return None
    pts = []
    for token in m.group(1).strip().split(","):
        parts = token.split()
        if len(parts) >= 2:
            pts.append((float(parts[0]), float(parts[1])))
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]  # Drop the duplicate closing point.
    n = len(pts)
    if n < 3:
        return None

    cross_signs = []
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        cx, cy = pts[(i + 2) % n]
        cross_z = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        cross_signs.append(1 if cross_z > 0 else (-1 if cross_z < 0 else 0))

    positive = sum(1 for s in cross_signs if s > 0)
    negative = sum(1 for s in cross_signs if s < 0)
    majority = 1 if positive >= negative else -1
    return sum(1 for s in cross_signs if s != 0 and s != majority)


def estimate_shape_type(
    circularity: float | None,
    convexity_ratio: float | None,
    concave_vertex_count: int | None,
    box_fill_ratio: float | None = None,
    footprint_vertex_count: int | None = None,
) -> str | None:
    """Estimate footprint shape from circularity, convexity, and vertex data.

    A heuristic based on concave vertex count; does not guarantee a strict
    distinction between L/T/cross shapes, since the same concave count can
    arise from very different actual layouts.

    Args:
        circularity: 4π*area / perimeter² (1.0 = perfect circle), or None.
        convexity_ratio: area / convex_hull_area (1.0 = convex), or None.
        concave_vertex_count: Count of reflex vertices, or None.
        box_fill_ratio: footprint_area_m2 / bbox_area_m2, used for the oval
            test (see `_OVAL_BOX_FILL_MIN`/`_MAX`).
        footprint_vertex_count: Outer-ring vertex count, used for the
            high-vertex-count oval fallback (see `_OVAL_NOISY_MIN_VERTEX`).

    Returns:
        A Japanese shape-classification label, or None if `circularity` is None.
    """
    if circularity is None:
        return None
    if circularity >= _CIRCULAR_THRESHOLD:
        return "円形に近い"
    # Catch "elongated but round" shapes (ovals) that circularity alone
    # can't detect, using box_fill_ratio (insensitive to eccentricity).
    if box_fill_ratio is not None and _OVAL_BOX_FILL_MIN <= box_fill_ratio <= _OVAL_BOX_FILL_MAX:
        if concave_vertex_count == 0:
            return "楕円形"
        # High-vertex-count curved footprints tend to accumulate spurious
        # concave vertices from digitization noise, so when vertex count is
        # high and the shape is nearly convex, classify as oval regardless
        # of concave_vertex_count.
        if (
            convexity_ratio is not None and convexity_ratio >= _OVAL_NOISY_CONVEXITY_MIN
            and footprint_vertex_count is not None and footprint_vertex_count >= _OVAL_NOISY_MIN_VERTEX
        ):
            return "楕円形"
    if concave_vertex_count is None:
        return None
    if concave_vertex_count == 0:
        return "矩形・単純形状"
    if concave_vertex_count == 1:
        return "L字型"
    if concave_vertex_count == 2:
        return "コの字型・T字型"
    if concave_vertex_count in (3, 4):
        if convexity_ratio is not None and convexity_ratio >= _CROSS_CONVEXITY_MIN:
            return "十字型・複雑形状"
        return "星形・複雑形状"
    return "星形・複雑形状"


# ============================================================
# Step 9-1: Per-building geometry analysis
# ============================================================

def analyze_building(wkt: str) -> dict:
    """Extract 3D metadata for one building from its WKT.

    Args:
        wkt: A MULTIPOLYGON Z WKT string for one building.

    Returns:
        A dict with `ground_elev_m`, `building_height_m`, `roof_area_m2`,
        `wall_area_total_m2`, `wall_ratio_{n,e,s,w}` (each face's wall area
        as a fraction of total wall area), and `face_count`.
    """
    polys = parse_multipolygon_z(wkt)
    if not polys:
        return _empty_meta()

    z_vals: list[float] = []
    roof_area = 0.0
    wall_area: dict[str, float] = {"N": 0.0, "E": 0.0, "S": 0.0, "W": 0.0}
    # Accumulate (slope_deg, area) per roof face.
    roof_faces: list[tuple[float, float]] = []

    for pts in polys:
        # Collect Z values for ground elevation / building height.
        z_vals.extend(p[2] for p in pts)

        # Compute the face's normal vector.
        raw_n = newell_normal(pts)
        norm = np.linalg.norm(raw_n)
        if norm < 1e-10:
            continue  # Skip degenerate (zero-area) polygons.

        area = norm / 2.0
        unit_n = raw_n / norm
        nz, nx, ny = float(unit_n[2]), float(unit_n[0]), float(unit_n[1])

        face_type = classify_face(nz, nx, ny)
        if face_type == "roof":
            roof_area += area
            slope_deg = math.degrees(math.acos(min(1.0, max(-1.0, nz))))
            roof_faces.append((slope_deg, area))
        elif face_type == "wall":
            az = wall_azimuth_deg(nx, ny)
            direction = azimuth_to_direction(az)
            wall_area[direction] += area

    if not z_vals:
        return _empty_meta()

    ground_elev = min(z_vals)
    max_z       = max(z_vals)
    bldg_height = max_z - ground_elev
    total_wall  = sum(wall_area.values())

    # Wall area ratios (split evenly if there's no wall area at all).
    if total_wall > 0:
        ratios = {k: v / total_wall for k, v in wall_area.items()}
    else:
        ratios = {"N": 0.25, "E": 0.25, "S": 0.25, "W": 0.25}

    # Area-weighted mean roof slope and flat-area ratio (None if no roof faces).
    if roof_area > 0:
        roof_slope_mean_deg = sum(s * a for s, a in roof_faces) / roof_area
        flat_area = sum(a for s, a in roof_faces if s < _FLAT_ROOF_SLOPE_DEG)
        flat_roof_ratio = flat_area / roof_area
    else:
        roof_slope_mean_deg = None
        flat_roof_ratio = None
    roof_type_est = estimate_roof_type(flat_roof_ratio)

    return {
        "ground_elev_m":       round(ground_elev, 3),
        "building_height_m":   round(bldg_height, 3),
        "roof_area_m2":        round(roof_area, 2),
        "wall_area_total_m2":  round(total_wall, 2),
        "wall_ratio_n":        round(ratios["N"], 4),
        "wall_ratio_e":        round(ratios["E"], 4),
        "wall_ratio_s":        round(ratios["S"], 4),
        "wall_ratio_w":        round(ratios["W"], 4),
        "face_count":          len(polys),
        "roof_slope_mean_deg": round(roof_slope_mean_deg, 2) if roof_slope_mean_deg is not None else None,
        "flat_roof_ratio":     round(flat_roof_ratio, 4) if flat_roof_ratio is not None else None,
        "roof_type_est":       roof_type_est,
    }


def _empty_meta() -> dict:
    """Default values returned when a building's geometry can't be analyzed."""
    return {
        "ground_elev_m": None, "building_height_m": None,
        "roof_area_m2": None,  "wall_area_total_m2": None,
        "wall_ratio_n": None,  "wall_ratio_e": None,
        "wall_ratio_s": None,  "wall_ratio_w": None,
        "face_count": 0,
        "roof_slope_mean_deg": None, "flat_roof_ratio": None,
        "roof_type_est": None,
    }


# ============================================================
# Step 9-1: Process all buildings
# ============================================================

def fetch_footprint_shape(gpkg_path: Path) -> pd.DataFrame:
    """Fetch footprint area/perimeter/hull/bbox/vertex-count/WKT per building.

    Reads from `hiroshima_sample.gpkg` (the regular, non-maxlod version).
    Geometry is stored as a single-ring polygon with constant Z=0, but
    `ST_Force2D` is applied before each function as a defensive measure.

    The geometry type is MULTIPOLYGON with a single element, and DuckDB's
    spatial extension has no `ST_GeometryN` (so `ST_ExteriorRing` can't be
    applied directly), so this fetches the full WKT and lets
    `count_concave_vertices()` extract the outer ring via regex — same
    approach as `parse_multipolygon_z()`.

    Args:
        gpkg_path: Path to `hiroshima_sample.gpkg`.

    Returns:
        A DataFrame with columns [id, footprint_area_m2, footprint_perimeter_m,
        convex_hull_area_m2, bbox_area_m2, footprint_vertex_count, footprint_wkt].
    """
    tmp_con = duckdb.connect()
    tmp_con.execute("INSTALL spatial; LOAD spatial;")
    try:
        df = tmp_con.execute(f"""
            SELECT id,
                   ST_Area(ST_Force2D(geometry))                          AS footprint_area_m2,
                   ST_Perimeter(ST_Force2D(geometry))                     AS footprint_perimeter_m,
                   ST_Area(ST_ConvexHull(ST_Force2D(geometry)))           AS convex_hull_area_m2,
                   ST_Area(ST_MinimumRotatedRectangle(ST_Force2D(geometry))) AS bbox_area_m2,
                   ST_NPoints(ST_Force2D(geometry))                       AS footprint_vertex_count,
                   ST_AsText(ST_Force2D(geometry))                        AS footprint_wkt
            FROM st_read('{gpkg_path}', layer='bldg:Building')
        """).df()
    finally:
        tmp_con.close()
    return df


def extract_geom_meta(
    maxlod_gpkg: Path,
    rag_con: duckdb.DuckDBPyConnection,
) -> None:
    """Analyze every building's geometry and persist it to `building_geom_meta`.

    Reads MULTIPOLYGON Z from `hiroshima_sample_maxlod.gpkg`, then left-joins
    footprint area (from `hiroshima_sample.gpkg`) to also derive an
    approximate `volume_m3` and `slenderness`. Takes roughly 1-2 minutes
    (CPU-bound) for 2,958 buildings.

    Args:
        maxlod_gpkg: Path to `hiroshima_sample_maxlod.gpkg`.
        rag_con: An open connection from `connect_rag()`, with
            `building_geom_meta` already created.
    """
    print("  maxlod.gpkg から建物 WKT を読み込み中...")
    tmp_con = duckdb.connect()
    tmp_con.execute("INSTALL spatial; LOAD spatial;")

    df_wkt = tmp_con.execute(f"""
        SELECT id,
               ST_AsText(geometry::GEOMETRY) AS wkt
        FROM st_read('{maxlod_gpkg}', layer='bldg:Building')
    """).df()
    tmp_con.close()

    total = len(df_wkt)
    print(f"  {total} 件の建物を解析します...")

    records = []
    for i, (_, row) in enumerate(df_wkt.iterrows()):
        if (i + 1) % 500 == 0 or (i + 1) == total:
            print(f"  [{i + 1}/{total}] 解析中...")
        meta = analyze_building(row["wkt"] or "")
        meta["id"] = row["id"]
        records.append(meta)

    df_meta = pd.DataFrame(records, columns=[
        "id", "ground_elev_m", "building_height_m",
        "roof_area_m2", "wall_area_total_m2",
        "wall_ratio_n", "wall_ratio_e", "wall_ratio_s", "wall_ratio_w",
        "face_count", "roof_slope_mean_deg", "flat_roof_ratio", "roof_type_est",
    ])

    # Left-join footprint shape indicators and derive approximate volume,
    # slenderness, circularity, convexity ratio, concave count, and shape class.
    print("  hiroshima_sample.gpkg からフットプリント形状指標を取得中...")
    df_footprint = fetch_footprint_shape(GPKG_PATH)
    df_meta = df_meta.merge(df_footprint, on="id", how="left")

    has_shape = df_meta["footprint_area_m2"].notna() & (df_meta["footprint_area_m2"] > 0) \
        & df_meta["building_height_m"].notna()
    df_meta["volume_m3"] = np.where(
        has_shape, df_meta["footprint_area_m2"] * df_meta["building_height_m"], np.nan
    )
    df_meta["slenderness"] = np.where(
        has_shape, df_meta["building_height_m"] / np.sqrt(df_meta["footprint_area_m2"]), np.nan
    )

    # Compute concave count, circularity, convexity ratio, box fill ratio,
    # and shape classification for each building.
    print("  フットプリント形状（凹角数・真円度・凸性比・外接矩形充填率）を解析中...")
    concave_counts, circularities, convexity_ratios = [], [], []
    box_fill_ratios, shape_types = [], []
    for _, row in df_meta.iterrows():
        concave = count_concave_vertices(row.get("footprint_wkt"))
        area = row.get("footprint_area_m2")
        perim = row.get("footprint_perimeter_m")
        hull_area = row.get("convex_hull_area_m2")
        bbox_area = row.get("bbox_area_m2")

        circularity = None
        if pd.notna(area) and pd.notna(perim) and area > 0 and perim > 0:
            circularity = (4.0 * math.pi * area) / (perim ** 2)

        convexity = None
        if pd.notna(area) and pd.notna(hull_area) and hull_area > 0:
            convexity = area / hull_area

        box_fill = None
        if pd.notna(area) and pd.notna(bbox_area) and bbox_area > 0:
            box_fill = area / bbox_area

        concave_counts.append(concave)
        circularities.append(round(circularity, 4) if circularity is not None else None)
        convexity_ratios.append(round(convexity, 4) if convexity is not None else None)
        box_fill_ratios.append(round(box_fill, 4) if box_fill is not None else None)
        vcount = row.get("footprint_vertex_count")
        shape_types.append(estimate_shape_type(
            circularity, convexity, concave, box_fill,
            int(vcount) if pd.notna(vcount) else None,
        ))

    df_meta["concave_vertex_count"] = concave_counts
    df_meta["circularity"] = circularities
    df_meta["convexity_ratio"] = convexity_ratios
    df_meta["box_fill_ratio"] = box_fill_ratios
    df_meta["shape_type_est"] = shape_types

    df_meta = df_meta[[
        "id", "ground_elev_m", "building_height_m",
        "roof_area_m2", "wall_area_total_m2",
        "wall_ratio_n", "wall_ratio_e", "wall_ratio_s", "wall_ratio_w",
        "face_count", "roof_slope_mean_deg", "flat_roof_ratio", "roof_type_est",
        "footprint_area_m2", "volume_m3", "slenderness",
        "footprint_perimeter_m", "convex_hull_area_m2", "footprint_vertex_count",
        "concave_vertex_count", "circularity", "convexity_ratio",
        "bbox_area_m2", "box_fill_ratio", "shape_type_est",
    ]]

    print(f"  building_geom_meta テーブルに {len(df_meta)} 件を INSERT 中...")
    rag_con.execute("INSERT INTO building_geom_meta SELECT * FROM df_meta")
    print(f"  [OK] building_geom_meta 保存完了: {len(df_meta)} 件")

    # Print a summary of the computed statistics.
    valid = df_meta[df_meta["building_height_m"].notna()]
    valid_roof = df_meta[df_meta["roof_slope_mean_deg"].notna()]
    valid_shape = df_meta[df_meta["volume_m3"].notna()]
    print(f"\n  【統計サマリー】")
    print(f"  ・有効建物数: {len(valid)} 件 / {total} 件")
    print(f"  ・建物高さ: 平均 {valid['building_height_m'].mean():.1f}m, 最大 {valid['building_height_m'].max():.1f}m")
    print(f"  ・地面標高: 平均 {valid['ground_elev_m'].mean():.1f}m, 範囲 [{valid['ground_elev_m'].min():.1f}, {valid['ground_elev_m'].max():.1f}]m")
    print(f"  ・壁面方位（平均比率）: 北 {valid['wall_ratio_n'].mean()*100:.1f}%, 東 {valid['wall_ratio_e'].mean()*100:.1f}%, 南 {valid['wall_ratio_s'].mean()*100:.1f}%, 西 {valid['wall_ratio_w'].mean()*100:.1f}%")
    print(f"  ・屋根種別（有効 {len(valid_roof)} 件）: {valid_roof['roof_type_est'].value_counts().to_dict()}")
    print(f"  ・平坦面比率: 平均 {valid_roof['flat_roof_ratio'].mean():.2f}")
    print(f"  ・体積近似（有効 {len(valid_shape)} 件）: 平均 {valid_shape['volume_m3'].mean():.0f}m3, 最大 {valid_shape['volume_m3'].max():.0f}m3")
    print(f"  ・細長さ: 平均 {valid_shape['slenderness'].mean():.2f}, 最大 {valid_shape['slenderness'].max():.2f}")

    # Check the footprint shape classification distribution.
    valid_circ = df_meta[df_meta["circularity"].notna()]
    print(f"  ・真円度（有効 {len(valid_circ)} 件）: 平均 {valid_circ['circularity'].mean():.3f}, 最大 {valid_circ['circularity'].max():.3f}")
    valid_conv = df_meta[df_meta["convexity_ratio"].notna()]
    print(f"  ・凸性比（有効 {len(valid_conv)} 件）: 平均 {valid_conv['convexity_ratio'].mean():.3f}, 最小 {valid_conv['convexity_ratio'].min():.3f}")
    valid_box = df_meta[df_meta["box_fill_ratio"].notna()]
    print(f"  ・外接矩形充填率（有効 {len(valid_box)} 件）: 平均 {valid_box['box_fill_ratio'].mean():.3f}, "
          f"範囲 [{valid_box['box_fill_ratio'].min():.3f}, {valid_box['box_fill_ratio'].max():.3f}]")
    print(f"  ・凹角数の分布: {df_meta['concave_vertex_count'].value_counts().sort_index().to_dict()}")
    print(f"  ・形状分類（shape_type_est）: {df_meta['shape_type_est'].value_counts().to_dict()}")


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Phase 9: LOD2 ジオメトリ解析 開始")
    print("=" * 60)

    if not MAXLOD_PATH.exists():
        raise FileNotFoundError(
            f"maxlod GPKG が見つかりません: {MAXLOD_PATH}\n"
            "data/ フォルダに hiroshima_sample_maxlod.gpkg を配置してください。"
        )

    rag_con = connect_rag()
    print("  building_geom_meta テーブルを初期化中...")
    create_geom_meta_table(rag_con)

    extract_geom_meta(MAXLOD_PATH, rag_con)

    rag_con.close()
    print("\n[SUCCESS] Phase 9 完了")
