"""Builds the RAG database: text cards, embeddings, and the HNSW index.

For all 2,958 buildings, generates a natural-language "card" combining building
attributes + disaster risk + surrounding geographic context, embeds it with
`gemini-embedding-001`, and persists everything to `output/plateau_rag.duckdb`
with an HNSW index for cosine-similarity search.
"""

import argparse
import os
import time
import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
from dotenv import load_dotenv
from src.pipeline.codelist_loader import CodelistLoader
from src.common.db import (
    EMROUTE_PATH,
    GPKG_PATH,
    LANDMARK_PATH,
    LANDUSE_GPKG_PATH as LANDUSE_PATH,
    PARK_PATH,
    RAG_DB_PATH,
    SHELTER_PATH,
    STATION_PATH,
    URF_GPKG_PATH as URF_PATH,
    connect_rag,
)

load_dotenv()

# `enrichment.py` lives at src/pipeline/enrichment.py, so the repo root is
# three levels up.
ROOT = Path(__file__).parent.parent.parent


# ============================================================
# DuckDB 永続化スキーマ設計・初期化
# ============================================================
# connect_rag() / RAG_DB_PATH moved to src/common/db.py since runtime
# modules (src/app/*) need them too, not just this pipeline script.


def create_table(rag_con: duckdb.DuckDBPyConnection, embedding_dim: int = 768) -> None:
    """Create the `building_chunks` table, dropping any existing one first.

    Args:
        rag_con: An open connection from `connect_rag()`.
        embedding_dim: Vector width for the `embedding` column. Must match
            whatever embedding model's output is inserted later.
    """
    rag_con.execute("DROP TABLE IF EXISTS building_chunks;")
    rag_con.execute(f"""
    CREATE TABLE building_chunks (
        -- Identity, text, and embedding
        id                       VARCHAR PRIMARY KEY,
        text_card                VARCHAR NOT NULL,
        embedding                FLOAT[{embedding_dim}],
        -- Basic building attributes
        usage                    VARCHAR,
        measured_height          DOUBLE,
        storeys                  BIGINT,
        -- Disaster risk
        ht_depth_max             DOUBLE,
        ht_rank_worst            VARCHAR,
        rv_depth_max             DOUBLE,
        rv_rank_worst            VARCHAR,
        ts_depth_max             DOUBLE,
        ts_rank_worst            VARCHAR,
        -- Structure
        structure_type           VARCHAR,
        fire_proof               VARCHAR,
        -- Nearest road (GPKG)
        nearest_road_dist_m      DOUBLE,
        nearest_road_width       DOUBLE,
        nearest_road_lanes       BIGINT,
        -- Land use / urban planning zone (GPKG polygon)
        landuse_class            VARCHAR,
        urf_usage                VARCHAR,
        -- Nearest shelter (GeoJSON)
        nearest_shelter_name     VARCHAR,
        nearest_shelter_dist_m   DOUBLE,
        nearest_shelter_disasters VARCHAR,
        -- Nearest station (GeoJSON)
        nearest_station_name     VARCHAR,
        nearest_station_line     VARCHAR,
        nearest_station_dist_m   DOUBLE,
        -- Nearest emergency transport route (GeoJSON)
        nearest_emroute_name     VARCHAR,
        nearest_emroute_dist_m   DOUBLE,
        -- Nearest park (GeoJSON)
        nearest_park_name        VARCHAR,
        nearest_park_dist_m      DOUBLE,
        -- Nearest landmark (GeoJSON)
        nearest_landmark_name    VARCHAR,
        nearest_landmark_dist_m  DOUBLE,
        -- Geometry (used by the app's spatial filter)
        geometry                 GEOMETRY
    )
    """)
    print(f"  テーブル building_chunks 作成完了（embedding_dim={embedding_dim}）")


def load_building_attributes(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Join building attributes with all surrounding geographic context.

    Combines GPKG sources (building, risk, road, land use, urban planning
    zone) and GeoJSON sources (shelter, station, emergency route, park,
    landmark) into one row per building via a single large CTE query.
    `geometry` is intentionally excluded — `save_chunks()` re-joins it from
    the GPKG at insert time instead.

    Args:
        con: An in-memory DuckDB connection with the `spatial` extension
            loaded (not the RAG database — this reads the raw GPKG/GeoJSON).

    Returns:
        One row per building with all joined attribute columns.
    """
    # Normalize to forward slashes before embedding paths in SQL (DuckDB's
    # st_read() on Windows is picky about backslashes in string literals).
    gpkg     = str(GPKG_PATH).replace("\\", "/")
    landuse  = str(LANDUSE_PATH).replace("\\", "/")
    urf      = str(URF_PATH).replace("\\", "/")
    shelter  = str(SHELTER_PATH).replace("\\", "/")
    station  = str(STATION_PATH).replace("\\", "/")
    emroute  = str(EMROUTE_PATH).replace("\\", "/")
    park     = str(PARK_PATH).replace("\\", "/")
    landmark = str(LANDMARK_PATH).replace("\\", "/")

    sql = f"""
    WITH
    -- Buildings (centroid used as the reference point for all distance calcs).
    bldg AS (
        SELECT id, usage, measuredHeight, storeysAboveGround,
               ST_Centroid(geometry) AS centroid
        FROM st_read('{gpkg}', layer='bldg:Building')
    ),
    -- Storm surge risk, aggregated per building.
    ht AS (
        SELECT parentId, MAX(depth) AS ht_depth_max, MAX(rank) AS ht_rank_worst
        FROM st_read('{gpkg}', layer='uro:HighTideRiskAttribute')
        GROUP BY parentId
    ),
    -- River flooding risk, aggregated per building.
    rv AS (
        SELECT parentId, MAX(depth) AS rv_depth_max, MAX(rank) AS rv_rank_worst
        FROM st_read('{gpkg}', layer='uro:RiverFloodingRiskAttribute')
        GROUP BY parentId
    ),
    -- Tsunami risk, aggregated per building.
    ts AS (
        SELECT parentId, MAX(depth) AS ts_depth_max, MAX(rank) AS ts_rank_worst
        FROM st_read('{gpkg}', layer='uro:TsunamiRiskAttribute')
        GROUP BY parentId
    ),
    -- Building structure / fire-resistance detail.
    det AS (
        SELECT parentId,
               MAX(buildingStructureType)  AS structure_type,
               MAX(fireproofStructureType) AS fire_proof
        FROM st_read('{gpkg}', layer='uro:BuildingDetailAttribute')
        GROUP BY parentId
    ),
    -- Nearest road: CROSS JOIN + ARG_MIN picks the closest one per building.
    nearest_road AS (
        SELECT b.id AS building_id,
               MIN(ST_Distance(b.centroid, r.geometry))                     AS nearest_road_dist_m,
               ARG_MIN(rs.width,         ST_Distance(b.centroid, r.geometry)) AS nearest_road_width,
               ARG_MIN(rs.numberOfLanes, ST_Distance(b.centroid, r.geometry)) AS nearest_road_lanes
        FROM bldg b
        CROSS JOIN st_read('{gpkg}', layer='tran:Road') r
        LEFT JOIN st_read('{gpkg}', layer='uro:RoadStructureAttribute') rs ON r.id = rs.parentId
        GROUP BY b.id
    ),
    -- Land use zone (the polygon containing the building's centroid).
    landuse_zone AS (
        SELECT b.id AS building_id,
               MAX(l.class) AS landuse_class
        FROM bldg b
        LEFT JOIN st_read('{landuse}', layer='hiroshima_landuse') l
              ON ST_Within(b.centroid, l.geom)
        GROUP BY b.id
    ),
    -- Urban planning use district (the polygon containing the centroid).
    urf_zone AS (
        SELECT b.id AS building_id,
               MAX(u.usage) AS urf_usage
        FROM bldg b
        LEFT JOIN st_read('{urf}', layer='urf:UseDistrict') u
              ON ST_Within(b.centroid, u.geometry)
        GROUP BY b.id
    ),
    -- GeoJSON shelters: WGS84 -> EPSG:6671 (always_xy:=true is required, see
    -- src/common/db.py's wgs84_to_epsg6671() for why).
    shelters AS (
        SELECT "名称" AS name, "対象とする災害の分類" AS disasters,
               ST_Transform(geom, 'EPSG:4326', 'EPSG:6671', always_xy := true) AS geom_6671
        FROM st_read('{shelter}')
    ),
    -- GeoJSON stations.
    stations AS (
        SELECT "駅名" AS name, "路線名" AS line,
               ST_Transform(geom, 'EPSG:4326', 'EPSG:6671', always_xy := true) AS geom_6671
        FROM st_read('{station}')
    ),
    -- GeoJSON emergency transport routes (LineString; ST_Distance also works
    -- against polygons/lines, not just points).
    emroutes AS (
        SELECT "路線名称" AS name,
               ST_Transform(geom, 'EPSG:4326', 'EPSG:6671', always_xy := true) AS geom_6671
        FROM st_read('{emroute}')
    ),
    -- GeoJSON parks.
    parks AS (
        SELECT "公園名" AS name,
               ST_Transform(geom, 'EPSG:4326', 'EPSG:6671', always_xy := true) AS geom_6671
        FROM st_read('{park}')
    ),
    -- GeoJSON landmarks.
    landmarks AS (
        SELECT "名称" AS name,
               ST_Transform(geom, 'EPSG:4326', 'EPSG:6671', always_xy := true) AS geom_6671
        FROM st_read('{landmark}')
    ),
    -- Nearest: shelter.
    nearest_shelter AS (
        SELECT b.id AS building_id,
               MIN(ST_Distance(b.centroid, s.geom_6671))                      AS nearest_shelter_dist_m,
               ARG_MIN(s.name,     ST_Distance(b.centroid, s.geom_6671))      AS nearest_shelter_name,
               ARG_MIN(s.disasters, ST_Distance(b.centroid, s.geom_6671))     AS nearest_shelter_disasters
        FROM bldg b CROSS JOIN shelters s GROUP BY b.id
    ),
    -- Nearest: station.
    nearest_station AS (
        SELECT b.id AS building_id,
               MIN(ST_Distance(b.centroid, s.geom_6671))                      AS nearest_station_dist_m,
               ARG_MIN(s.name, ST_Distance(b.centroid, s.geom_6671))          AS nearest_station_name,
               ARG_MIN(s.line, ST_Distance(b.centroid, s.geom_6671))          AS nearest_station_line
        FROM bldg b CROSS JOIN stations s GROUP BY b.id
    ),
    -- Nearest: emergency transport route.
    nearest_emroute AS (
        SELECT b.id AS building_id,
               MIN(ST_Distance(b.centroid, e.geom_6671))                      AS nearest_emroute_dist_m,
               ARG_MIN(e.name, ST_Distance(b.centroid, e.geom_6671))          AS nearest_emroute_name
        FROM bldg b CROSS JOIN emroutes e GROUP BY b.id
    ),
    -- Nearest: park.
    nearest_park AS (
        SELECT b.id AS building_id,
               MIN(ST_Distance(b.centroid, p.geom_6671))                      AS nearest_park_dist_m,
               ARG_MIN(p.name, ST_Distance(b.centroid, p.geom_6671))          AS nearest_park_name
        FROM bldg b CROSS JOIN parks p GROUP BY b.id
    ),
    -- Nearest: landmark.
    nearest_landmark AS (
        SELECT b.id AS building_id,
               MIN(ST_Distance(b.centroid, l.geom_6671))                      AS nearest_landmark_dist_m,
               ARG_MIN(l.name, ST_Distance(b.centroid, l.geom_6671))          AS nearest_landmark_name
        FROM bldg b CROSS JOIN landmarks l GROUP BY b.id
    )
    -- Final join (geometry excluded — save_chunks() re-joins it from the GPKG).
    SELECT
        b.id,
        b.usage,
        b.measuredHeight    AS measured_height,
        b.storeysAboveGround AS storeys,
        ht.ht_depth_max,    ht.ht_rank_worst,
        rv.rv_depth_max,    rv.rv_rank_worst,
        ts.ts_depth_max,    ts.ts_rank_worst,
        det.structure_type, det.fire_proof,
        nr.nearest_road_dist_m, nr.nearest_road_width, nr.nearest_road_lanes,
        lu.landuse_class,
        uz.urf_usage,
        ns.nearest_shelter_name, ns.nearest_shelter_dist_m, ns.nearest_shelter_disasters,
        nst.nearest_station_name, nst.nearest_station_line, nst.nearest_station_dist_m,
        ne.nearest_emroute_name, ne.nearest_emroute_dist_m,
        np.nearest_park_name, np.nearest_park_dist_m,
        nl.nearest_landmark_name, nl.nearest_landmark_dist_m
    FROM bldg b
    LEFT JOIN ht  ON b.id = ht.parentId
    LEFT JOIN rv  ON b.id = rv.parentId
    LEFT JOIN ts  ON b.id = ts.parentId
    LEFT JOIN det ON b.id = det.parentId
    LEFT JOIN nearest_road nr      ON b.id = nr.building_id
    LEFT JOIN landuse_zone lu      ON b.id = lu.building_id
    LEFT JOIN urf_zone uz          ON b.id = uz.building_id
    LEFT JOIN nearest_shelter ns   ON b.id = ns.building_id
    LEFT JOIN nearest_station nst  ON b.id = nst.building_id
    LEFT JOIN nearest_emroute ne   ON b.id = ne.building_id
    LEFT JOIN nearest_park np      ON b.id = np.building_id
    LEFT JOIN nearest_landmark nl  ON b.id = nl.building_id
    """

    print("  建物属性 + 空間文脈を結合中（数分かかる場合があります）...")
    t0 = time.time()
    df = con.execute(sql).df()
    print(f"  完了: {len(df):,} 件（{time.time() - t0:.1f} 秒）")
    return df


# ============================================================
# 属性カルテ（テキスト化）関数の実装
# ============================================================

def _v(val, fmt: str = "", default: str = "データなし") -> str:
    """Format a value for display, substituting `default` for None/NaN.

    Args:
        val: The raw value (any type, or None/NaN).
        fmt: An optional format spec passed to `format()`.
        default: Text shown when `val` is missing.

    Returns:
        The formatted value, or `default`.
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    return format(val, fmt) if fmt else str(val)


def build_text_card(
    row: dict,
    cl: "CodelistLoader",
    geom_meta: dict | None = None,
) -> str:
    """Generate the natural-language attribute card shown to the LLM and user.

    Decodes raw codes to Japanese labels via `cl`. Sections: basic building
    info / disaster risk / structure / surroundings / [3D shape & orientation]
    (only added when `geom_meta` is provided).

    Args:
        row: A `building_chunks` record as a dict.
        cl: Codelist decoder for converting raw codes to Japanese labels.
        geom_meta: A `building_geom_meta` record as a dict. When None, the 3D
            shape/orientation section is omitted entirely.

    Returns:
        The multi-line Japanese text card.
    """
    lines = []

    # Basic building info.
    lines.append(f"建物ID: {row['id']}")
    lines.append(f"用途: {cl.decode_usage(row.get('usage'))}")
    lines.append(f"高さ: {_v(row.get('measured_height'), '.1f')}m / {_v(row.get('storeys'))}階建て")
    lines.append("")

    # Disaster risk (rank decoded to a human-readable flood-depth range).
    lines.append("[災害リスク]")
    for depth_key, rank_key, label, rank_decoder in [
        ("ht_depth_max", "ht_rank_worst", "高潮", cl.decode_ht_rank),
        ("rv_depth_max", "rv_rank_worst", "洪水", cl.decode_rv_rank),
        ("ts_depth_max", "ts_rank_worst", "津波", cl.decode_ts_rank),
    ]:
        depth = row.get(depth_key)
        rank  = row.get(rank_key)
        if depth is not None and not (isinstance(depth, float) and pd.isna(depth)):
            rank_label = rank_decoder(str(rank)) if rank is not None else "不明"
            lines.append(f"・{label}: 最大浸水深 {depth:.2f}m（想定深さ {rank_label}）")
        else:
            lines.append(f"・{label}: リスクなし（浸水想定区域外）")
    lines.append("")

    # Structure (codes decoded to Japanese labels).
    lines.append("[構造]")
    lines.append(f"・建築構造: {cl.decode_structure(row.get('structure_type'))}")
    lines.append(f"・耐火仕様: {cl.decode_fire_proof(row.get('fire_proof'))}")
    lines.append("")

    # Surroundings.
    lines.append("[周辺環境]")

    # Nearest road.
    rd = row.get("nearest_road_dist_m")
    rw = row.get("nearest_road_width")
    rl = row.get("nearest_road_lanes")
    if rd is not None and not (isinstance(rd, float) and pd.isna(rd)):
        details = []
        if rw is not None and not (isinstance(rw, float) and pd.isna(rw)):
            details.append(f"幅 {rw}m")
        if rl is not None and not (isinstance(rl, float) and pd.isna(rl)):
            details.append(f"{int(rl)}車線")
        detail_str = f"（{', '.join(details)}）" if details else ""
        lines.append(f"・最寄り道路: 約 {rd:.0f}m{detail_str}")
    else:
        lines.append("・最寄り道路: データなし")

    # Land use (code decoded to Japanese label).
    lines.append(f"・土地利用: {cl.decode_landuse(row.get('landuse_class'))}")
    lines.append(f"・都市計画用途: {_v(row.get('urf_usage'))}")

    # Nearest station.
    sn = row.get("nearest_station_name")
    sl = row.get("nearest_station_line")
    sd = row.get("nearest_station_dist_m")
    if sn and not (isinstance(sn, float) and pd.isna(sn)):
        lines.append(f"・最寄り駅: {sn}（{_v(sl)}）約 {_v(sd, '.0f')}m")
    else:
        lines.append("・最寄り駅: データなし")

    # Nearest shelter.
    sh_n = row.get("nearest_shelter_name")
    sh_d = row.get("nearest_shelter_dist_m")
    sh_t = row.get("nearest_shelter_disasters")
    if sh_n and not (isinstance(sh_n, float) and pd.isna(sh_n)):
        lines.append(f"・最寄り避難所: {sh_n} 約 {_v(sh_d, '.0f')}m（対応: {_v(sh_t)}）")
    else:
        lines.append("・最寄り避難所: データなし")

    # Emergency transport route.
    em_n = row.get("nearest_emroute_name")
    em_d = row.get("nearest_emroute_dist_m")
    if em_n and not (isinstance(em_n, float) and pd.isna(em_n)):
        lines.append(f"・緊急輸送道路: {em_n} 約 {_v(em_d, '.0f')}m")
    else:
        lines.append("・緊急輸送道路: データなし")

    # Nearest park.
    pk_n = row.get("nearest_park_name")
    pk_d = row.get("nearest_park_dist_m")
    if pk_n and not (isinstance(pk_n, float) and pd.isna(pk_n)):
        lines.append(f"・近隣公園: {pk_n} 約 {_v(pk_d, '.0f')}m")
    else:
        lines.append("・近隣公園: データなし")

    # Nearest landmark.
    lm_n = row.get("nearest_landmark_name")
    lm_d = row.get("nearest_landmark_dist_m")
    if lm_n and not (isinstance(lm_n, float) and pd.isna(lm_n)):
        lines.append(f"・近隣ランドマーク: {lm_n} 約 {_v(lm_d, '.0f')}m")
    else:
        lines.append("・近隣ランドマーク: データなし")

    # 3D shape/orientation section, only added when geom_meta exists.
    if geom_meta is not None:
        lines.append("")
        lines.append("[3D形状・方位]")

        # Building height and ground elevation.
        bh  = geom_meta.get("building_height_m")
        ge  = geom_meta.get("ground_elev_m")
        _nan = lambda v: v is None or (isinstance(v, float) and pd.isna(v))
        if not _nan(bh) and not _nan(ge):
            lines.append(f"・建物高さ: {bh:.1f}m（地面標高: {ge:.1f}m）")

        # Wall orientation: only show directions with >5% wall ratio, sorted
        # descending so the dominant orientation reads first.
        direction_map = {"S": "南", "N": "北", "E": "東", "W": "西"}
        ratios = {
            "S": geom_meta.get("wall_ratio_s") or 0.0,
            "N": geom_meta.get("wall_ratio_n") or 0.0,
            "E": geom_meta.get("wall_ratio_e") or 0.0,
            "W": geom_meta.get("wall_ratio_w") or 0.0,
        }
        dominant = sorted(
            [(direction_map[k], v) for k, v in ratios.items() if v > 0.05],
            key=lambda x: -x[1]
        )
        if dominant:
            orientation_str = "、".join([f"{label}向き {v*100:.0f}%" for label, v in dominant])
            lines.append(f"・壁面方位: {orientation_str}")

        # Estimate flooded floor count from the existing disaster risk depths.
        for depth_key, label in [
            ("ht_depth_max", "高潮"),
            ("rv_depth_max", "洪水"),
            ("ts_depth_max", "津波"),
        ]:
            depth = row.get(depth_key)
            if depth is not None and not (isinstance(depth, float) and pd.isna(depth)) and depth > 0:
                floors = max(1, int(depth / 3.0))
                lines.append(f"・{label}浸水: 最大 {depth:.1f}m → 約 {floors} 階まで浸水の可能性")
            else:
                lines.append(f"・{label}浸水: リスクなし（浸水区域外）")

    return "\n".join(lines)


def _nan(v) -> bool:
    """Check for None/NaN (helper used only by `build_embed_text`)."""
    return v is None or (isinstance(v, float) and pd.isna(v))


def build_embed_text(
    row: dict,
    cl: "CodelistLoader",
    geom_meta: dict | None = None,
) -> dict[str, str]:
    """Generate embedding-only text, split into sections.

    `build_text_card()` produces a human-readable card for the LLM (section
    headers, "データなし" placeholders, bullet formatting). This function
    instead packs only building-specific information as densely as possible,
    to sharpen the embedding vector's discriminative power.

    Design rules:
    - Omit lines equivalent to "no data" — concatenate only present info.
    - No section headers or bullet markers ("・" etc.).
    - Round numbers into unit-suffixed Japanese phrases; avoid redundant
      qualifiers like "約" (roughly) stacking with rounding.

    Args:
        row: A `building_chunks` record as a dict.
        cl: Codelist decoder for converting raw codes to Japanese labels.
        geom_meta: A `building_geom_meta` record as a dict, or None to skip
            the shape section.

    Returns:
        A dict with `risk`, `environ`, and `shape` keys. Any section with no
        applicable info is an empty string — callers should skip empty
        sections when re-embedding rather than inserting a blank line.
    """
    # --- risk section: storm surge -> river -> tsunami, period-separated. ---
    risk_parts = []
    for depth_key, label in [
        ("ht_depth_max", "高潮"),
        ("rv_depth_max", "洪水"),
        ("ts_depth_max", "津波"),
    ]:
        depth = row.get(depth_key)
        if _nan(depth):
            risk_parts.append(f"{label}リスクなし")
        else:
            risk_parts.append(f"{label}浸水最大{depth:.1f}m")
    risk_text = "。".join(risk_parts) + "。" if risk_parts else ""

    # --- environ section: usage -> each nearby facility (only if present). ---
    environ_parts = []
    usage_label = cl.decode_usage(row.get("usage"))
    if usage_label and usage_label not in ("不明", "データなし"):
        environ_parts.append(usage_label)

    for name_key, dist_key, label in [
        ("nearest_station_name",  "nearest_station_dist_m",  "駅"),
        ("nearest_shelter_name",  "nearest_shelter_dist_m",  "避難所"),
        ("nearest_park_name",     "nearest_park_dist_m",     "公園"),
        ("nearest_emroute_name",  "nearest_emroute_dist_m",  "緊急輸送道路"),
        ("nearest_landmark_name", "nearest_landmark_dist_m", "ランドマーク"),
    ]:
        name = row.get(name_key)
        dist = row.get(dist_key)
        if name and not _nan(name) and not _nan(dist):
            environ_parts.append(f"{name}（{label}）まで{dist:.0f}m")
    environ_text = "。".join(environ_parts) + "。" if environ_parts else ""

    # --- shape section: height/floors/dominant orientation, geom_meta only. ---
    shape_parts = []
    if geom_meta is not None:
        bh = geom_meta.get("building_height_m")
        storeys = row.get("storeys")
        if not _nan(bh) and bh > 0:
            if not _nan(storeys):
                shape_parts.append(f"高さ{bh:.1f}m、{int(storeys)}階建て")
            else:
                shape_parts.append(f"高さ{bh:.1f}m")

        direction_map = {"S": "南", "N": "北", "E": "東", "W": "西"}
        ratios = {
            "S": geom_meta.get("wall_ratio_s") or 0.0,
            "N": geom_meta.get("wall_ratio_n") or 0.0,
            "E": geom_meta.get("wall_ratio_e") or 0.0,
            "W": geom_meta.get("wall_ratio_w") or 0.0,
        }
        dominant = sorted(
            [(direction_map[k], v) for k, v in ratios.items() if v > 0.05],
            key=lambda x: -x[1],
        )
        if dominant:
            orientation_str = "・".join(f"{label}向き{v*100:.0f}%" for label, v in dominant)
            shape_parts.append(f"壁面は{orientation_str}が主体")
    shape_text = "。".join(shape_parts) + "。" if shape_parts else ""

    return {"risk": risk_text, "environ": environ_text, "shape": shape_text}


# ============================================================
# Gemini embedding generation
# ============================================================

def batch_embed(
    texts: list[str],
    batch_size: int = 100,
    checkpoint_path: Path | None = None,
) -> list[list[float]]:
    """Embed texts with `gemini-embedding-001`, batched with checkpointing.

    Processes `batch_size` texts at a time. On API errors, parses the
    `retryDelay` field from the error and waits accordingly. If
    `checkpoint_path` is given, saves progress after each batch so a run can
    resume later — necessary because the Free Tier's 1,000 req/day quota
    means embedding all 2,958 rows takes 3 days split across runs.

    Args:
        texts: The text card strings to embed, in order.
        batch_size: How many texts to send per API call.
        checkpoint_path: Where to persist `{"processed": int, "embeddings":
            list}` between runs. Pass None to disable checkpointing.

    Returns:
        One embedding vector per input text, in the same order.

    Raises:
        RuntimeError: If a batch fails permanently (daily quota exceeded, or
            all retries exhausted). Progress up to that point is checkpointed
            first if `checkpoint_path` was given.
    """
    import re
    import json
    from google import genai
    from google.genai import types

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY が .env に設定されていません。")
    client = genai.Client(api_key=api_key)

    # Resume from a prior checkpoint if one exists.
    results: list[list[float]] = []
    start_idx = 0
    if checkpoint_path and checkpoint_path.exists():
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            ckpt = json.load(f)
        results = ckpt["embeddings"]
        start_idx = ckpt["processed"]
        print(f"  チェックポイントから再開: {start_idx} 件処理済み")

    total = len(texts)
    if start_idx >= total:
        print(f"  全件処理済み（チェックポイントから読み込み）")
        return results

    for i in range(start_idx, total, batch_size):
        batch = texts[i: i + batch_size]
        print(f"  埋め込み: {i + 1}〜{min(i + len(batch), total)} / {total} 件")

        for attempt in range(6):
            try:
                response = client.models.embed_content(
                    model="gemini-embedding-001",
                    contents=batch,
                    config=types.EmbedContentConfig(
                        task_type="RETRIEVAL_DOCUMENT"
                    ),
                )
                results.extend([list(e.values) for e in response.embeddings])
                break
            except Exception as exc:
                err_str = str(exc)
                # Daily quota exceeded (429 RPD) is unrecoverable within this
                # run — checkpoint progress and stop instead of retrying.
                if "PerDay" in err_str or (attempt == 5):
                    if checkpoint_path:
                        with open(checkpoint_path, "w", encoding="utf-8") as f:
                            json.dump({"processed": i, "embeddings": results}, f)
                        print(f"  チェックポイント保存: {i} 件処理済み → {checkpoint_path}")
                    raise RuntimeError(
                        f"埋め込み生成に失敗しました（{i}〜{i+len(batch)}件目）: {exc}"
                    ) from exc
                # Parse retryDelay from the error to pick a wait time (429 RPM).
                m = re.search(r"retryDelay.*?(\d+)s", err_str)
                wait = int(m.group(1)) + 5 if m else min(30 * (attempt + 1), 120)
                print(f"  [RETRY {attempt + 1}] {wait}秒後リトライ...")
                time.sleep(wait)

        # Small pause between batches to stay under the RPM limit.
        time.sleep(1.0)

        # Checkpoint after every completed batch.
        if checkpoint_path:
            with open(checkpoint_path, "w", encoding="utf-8") as f:
                json.dump({"processed": i + len(batch), "embeddings": results}, f)

    return results


# ============================================================
# Persist to DuckDB and build the HNSW index
# ============================================================

def save_chunks(
    rag_con: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    embeddings: list[list[float]],
) -> None:
    """Bulk-insert rows into `building_chunks`.

    Stores `embedding` as a numpy float32 array (DuckDB then recognizes it as
    `FLOAT[]`), and re-joins `geometry` from the GPKG rather than carrying it
    through the pandas DataFrame.

    Args:
        rag_con: An open connection from `connect_rag()`.
        df: Building attribute rows, must already have a `text_card` column
            (from `build_text_card()`).
        embeddings: One embedding vector per row of `df`, same order.
    """
    dim = len(embeddings[0])
    df = df.copy()
    # Convert to numpy float32 so DuckDB recognizes it as FLOAT[].
    df["embedding"] = [np.array(e, dtype=np.float32) for e in embeddings]
    assert "text_card" in df.columns, "df に text_card カラムがありません。"

    gpkg = str(GPKG_PATH).replace("\\", "/")

    # Register the pandas DataFrame as a temporary DuckDB view.
    rag_con.register("_tmp_chunks", df)

    rag_con.execute(f"""
    INSERT INTO building_chunks
    SELECT
        t.id,
        t.text_card,
        t.embedding::FLOAT[{dim}],
        t.usage,
        t.measured_height,
        t.storeys,
        t.ht_depth_max, t.ht_rank_worst,
        t.rv_depth_max, t.rv_rank_worst,
        t.ts_depth_max, t.ts_rank_worst,
        t.structure_type, t.fire_proof,
        t.nearest_road_dist_m, t.nearest_road_width, t.nearest_road_lanes,
        t.landuse_class, t.urf_usage,
        t.nearest_shelter_name, t.nearest_shelter_dist_m, t.nearest_shelter_disasters,
        t.nearest_station_name, t.nearest_station_line, t.nearest_station_dist_m,
        t.nearest_emroute_name, t.nearest_emroute_dist_m,
        t.nearest_park_name, t.nearest_park_dist_m,
        t.nearest_landmark_name, t.nearest_landmark_dist_m,
        b.geometry
    FROM _tmp_chunks t
    JOIN st_read('{gpkg}', layer='bldg:Building') b ON t.id = b.id
    """)

    rag_con.unregister("_tmp_chunks")
    cnt = rag_con.execute("SELECT COUNT(*) FROM building_chunks").fetchone()[0]
    print(f"  INSERT 完了: {cnt:,} 件")


def create_hnsw_index(rag_con: duckdb.DuckDBPyConnection) -> None:
    """Build the HNSW index used by `array_cosine_similarity()` at query time.

    Args:
        rag_con: An open connection from `connect_rag()`, with
            `building_chunks` already populated.
    """
    rag_con.execute("""
    CREATE INDEX IF NOT EXISTS building_chunks_embedding_idx
    ON building_chunks
    USING HNSW (embedding)
    WITH (metric = 'cosine')
    """)
    print("  HNSW インデックス作成完了")


# ============================================================
# Entry point
# ============================================================

def run_enrichment_pipeline() -> None:
    """Run the full pipeline: load, generate cards, embed, persist.

    Supports checkpointed resume, since the Gemini Free Tier's 1,000 req/day
    quota means embedding all 2,958 rows requires spreading the work across
    multiple days/runs.
    """
    EMBED_CKPT = ROOT / "output" / "embed_checkpoint.json"
    DF_CACHE   = ROOT / "output" / "building_attrs_cache.parquet"

    # Load + spatial join (skipped if a cache already exists).
    print("\n" + "=" * 60)
    print("データ読み込み・空間結合")
    print("=" * 60)
    if DF_CACHE.exists():
        df = pd.read_parquet(DF_CACHE)
        print(f"  キャッシュから読み込み: {len(df):,} 件（{DF_CACHE}）")
    else:
        gpkg_con = duckdb.connect()
        gpkg_con.execute("INSTALL spatial; LOAD spatial;")
        df = load_building_attributes(gpkg_con)
        gpkg_con.close()
        df.to_parquet(DF_CACHE, index=False)
        print(f"  キャッシュ保存: {DF_CACHE}")

    # Generate text cards (codes decoded to Japanese labels).
    print("\n" + "=" * 60)
    print("属性カルテ生成（コードリスト適用）")
    print("=" * 60)
    cl = CodelistLoader()
    print(cl.summary())

    # Bulk-load 3D metadata from building_geom_meta, if the table exists.
    geom_meta_map: dict[str, dict] = {}
    rag_con_check = connect_rag(RAG_DB_PATH)
    has_geom_meta = rag_con_check.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='building_geom_meta'"
    ).fetchone()[0] > 0
    if has_geom_meta:
        df_meta = rag_con_check.execute("SELECT * FROM building_geom_meta").df()
        geom_meta_map = {r["id"]: r.to_dict() for _, r in df_meta.iterrows()}
        print(f"  building_geom_meta から {len(geom_meta_map):,} 件の 3D メタデータをロード済み")
    else:
        print("  building_geom_meta テーブルが見つかりません。先に "
              "`pixi run python -m src.pipeline.geometry` を実行してください。")
    rag_con_check.close()

    # (1) Generate text_card: pass raw codes through, cl decodes internally.
    df["text_card"] = df.apply(
        lambda r: build_text_card(r.to_dict(), cl, geom_meta=geom_meta_map.get(r["id"])),
        axis=1,
    )
    print(f"  生成完了: {len(df):,} 件")
    print(f"  サンプル（先頭1件）:\n{df['text_card'].iloc[0]}")

    # (2) Also decode the DuckDB storage columns to Japanese labels (for
    # frontend display). Done after text_card generation to avoid decoding
    # the same code twice.
    def _safe(x):
        return x is not None and not (isinstance(x, float) and pd.isna(x))

    df["usage"]          = df["usage"].apply(cl.decode_usage)
    df["structure_type"] = df["structure_type"].apply(lambda x: cl.decode_structure(x) if _safe(x) else None)
    df["fire_proof"]     = df["fire_proof"].apply(lambda x: cl.decode_fire_proof(x) if _safe(x) else None)
    df["landuse_class"]  = df["landuse_class"].apply(lambda x: cl.decode_landuse(x) if _safe(x) else None)
    df["ht_rank_worst"]  = df["ht_rank_worst"].apply(lambda x: cl.decode_ht_rank(str(x)) if _safe(x) else None)
    df["rv_rank_worst"]  = df["rv_rank_worst"].apply(lambda x: cl.decode_rv_rank(str(x)) if _safe(x) else None)
    df["ts_rank_worst"]  = df["ts_rank_worst"].apply(lambda x: cl.decode_ts_rank(str(x)) if _safe(x) else None)

    # Generate embeddings (resumable via checkpoint).
    print("\n" + "=" * 60)
    print("Gemini 埋め込み生成（gemini-embedding-001）")
    print("=" * 60)
    try:
        embeddings = batch_embed(
            df["text_card"].tolist(),
            checkpoint_path=EMBED_CKPT,
        )
    except RuntimeError as e:
        processed = 0
        if EMBED_CKPT.exists():
            import json
            with open(EMBED_CKPT, "r", encoding="utf-8") as f:
                processed = json.load(f).get("processed", 0)
        print(f"\n[途中停止] {processed}/{len(df)} 件の埋め込みが完了しました。")
        print(f"  チェックポイント保存済み: {EMBED_CKPT}")
        print("  明日以降に再実行してください（Free Tier: 1000 req/day）。")
        return

    dim = len(embeddings[0])
    print(f"  埋め込み次元数: {dim}")

    # Persist to DuckDB and build the HNSW index.
    print("\n" + "=" * 60)
    print("DuckDB 保存・HNSW インデックス作成")
    print("=" * 60)
    rag_con = connect_rag(RAG_DB_PATH)
    create_table(rag_con, embedding_dim=dim)
    save_chunks(rag_con, df, embeddings)
    create_hnsw_index(rag_con)
    rag_con.close()

    # Remove the checkpoint on success (the attrs cache is kept — it's still
    # valid and re-running the spatial join is expensive).
    EMBED_CKPT.unlink(missing_ok=True)

    print("\n[SUCCESS] セマンティック・チャンク化完了")
    print(f"  出力先: {RAG_DB_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build building profile cards, embeddings, and the HNSW index."
    )
    parser.add_argument("--gpkg-path", type=Path, default=GPKG_PATH,
                         help=f"Path to the building GeoPackage (default: {GPKG_PATH}).")
    parser.add_argument("--landuse-path", type=Path, default=LANDUSE_PATH,
                         help=f"Path to the land-use GeoPackage (default: {LANDUSE_PATH}).")
    parser.add_argument("--urf-path", type=Path, default=URF_PATH,
                         help=f"Path to the urban-planning GeoPackage (default: {URF_PATH}).")
    parser.add_argument("--data-dir", type=Path, default=SHELTER_PATH.parent,
                         help="Directory holding the related GeoJSON files "
                              f"(default: {SHELTER_PATH.parent}).")
    parser.add_argument("--city-prefix", type=str, default=None,
                         help="PLATEAU related-dataset filename prefix, e.g. "
                              "'34100_hiroshima-shi_city_2022'. Combined with "
                              "--data-dir as '{prefix}_{shelter,station,...}.geojson'. "
                              "Only takes effect if provided.")
    parser.add_argument("--db-path", type=Path, default=RAG_DB_PATH,
                         help=f"Output DuckDB path (default: {RAG_DB_PATH}).")
    args = parser.parse_args()

    GPKG_PATH = args.gpkg_path
    LANDUSE_PATH = args.landuse_path
    URF_PATH = args.urf_path
    RAG_DB_PATH = args.db_path
    if args.city_prefix is not None:
        SHELTER_PATH = args.data_dir / f"{args.city_prefix}_shelter.geojson"
        STATION_PATH = args.data_dir / f"{args.city_prefix}_station.geojson"
        EMROUTE_PATH = args.data_dir / f"{args.city_prefix}_emergency_route.geojson"
        PARK_PATH = args.data_dir / f"{args.city_prefix}_park.geojson"
        LANDMARK_PATH = args.data_dir / f"{args.city_prefix}_landmark.geojson"
    elif args.data_dir != SHELTER_PATH.parent:
        SHELTER_PATH = args.data_dir / SHELTER_PATH.name
        STATION_PATH = args.data_dir / STATION_PATH.name
        EMROUTE_PATH = args.data_dir / EMROUTE_PATH.name
        PARK_PATH = args.data_dir / PARK_PATH.name
        LANDMARK_PATH = args.data_dir / LANDMARK_PATH.name

    run_enrichment_pipeline()
