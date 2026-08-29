"""One-off investigation script: inspects the Hiroshima GeoPackage's table layout.

Run manually before building the pipeline to confirm table names, column
definitions, and JOIN keys match what the rest of the pipeline assumes.
"""

import duckdb
from pathlib import Path

# --- パス定義 ---
# `investigate.py` lives at src/pipeline/investigate.py, so the repo root is
# three levels up.
ROOT = Path(__file__).parent.parent.parent
GPKG_PATH = ROOT / "data" / "hiroshima_sample.gpkg"
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# --- Tables to inspect (priority order; skipped if absent from the GPKG) ---
TARGET_TABLES = [
    "bldg:Building",
    "tran:Road",
    "tran:TrafficArea",
    "tran:AuxiliaryTrafficArea",
    "uro:HighTideRiskAttribute",
    "uro:RiverFloodingRiskAttribute",
    "uro:TsunamiRiskAttribute",
    "uro:InlandFloodingRiskAttribute",
    "uro:LandSlideRiskAttribute",
    "uro:BuildingDetailAttribute",
    "uro:RoadStructureAttribute",
]


def connect() -> duckdb.DuckDBPyConnection:
    """Open an in-memory DuckDB connection with the `spatial` extension loaded.

    Returns:
        A DuckDB connection ready to query the GeoPackage via `st_read()`.
    """
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    return con


# ============================================================
# Step 1-1: テーブル一覧取得とスキーマ確認
# ============================================================

def step1_1_list_layers(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """List every layer in the GeoPackage via `ST_Read_Meta()`.

    Args:
        con: An open DuckDB connection with the `spatial` extension loaded.

    Returns:
        One dict per layer with `name` and `feature_count` keys.
    """
    print("\n" + "=" * 60)
    print("Step 1-1-1: テーブル一覧 (ST_Read_Meta)")
    print("=" * 60)
    rows = con.execute(f"""
        SELECT
            layer.name          AS name,
            layer.feature_count AS feature_count
        FROM (
            SELECT UNNEST(layers) AS layer
            FROM ST_Read_Meta('{GPKG_PATH}')
        )
    """).fetchall()
    cols = [d[0] for d in con.description]
    layers = [dict(zip(cols, r)) for r in rows]
    for layer in layers:
        print(f"  {layer}")
    return layers


def step1_1_inspect_table(
    con: duckdb.DuckDBPyConnection, table_name: str
) -> list[dict]:
    """Print and return the column schema and row count of one GPKG layer.

    Args:
        con: An open DuckDB connection with the `spatial` extension loaded.
        table_name: The GPKG layer name to inspect.

    Returns:
        A list of `{"column_name": ..., "column_type": ...}` dicts, or an empty
        list if the query fails (logged, not raised, since this is an
        interactive investigation script meant to survive individual failures).
    """
    print(f"\n--- テーブル: {table_name} ---")
    try:
        # Column info
        schema_rows = con.execute(
            f"DESCRIBE SELECT * FROM st_read('{GPKG_PATH}', layer='{table_name}')"
        ).fetchall()
        cols_info = [{"column_name": r[0], "column_type": r[1]} for r in schema_rows]
        for c in cols_info:
            print(f"  {c['column_name']:40s} {c['column_type']}")

        # Row count
        count = con.execute(
            f"SELECT COUNT(*) FROM st_read('{GPKG_PATH}', layer='{table_name}')"
        ).fetchone()[0]
        print(f"  → 件数: {count:,}")
        return cols_info
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []


# ============================================================
# Step 1-2: JOIN キー検証
# ============================================================

def step1_2_join_risk(
    con: duckdb.DuckDBPyConnection, layer_names: list[str]
) -> dict:
    """Verify each risk-attribute table's JOIN to `bldg:Building` returns rows.

    Confirms `*RiskAttribute.parentId -> bldg:Building.id` is a valid JOIN key
    (i.e. not zero matches, which would signal a schema assumption is wrong).

    Args:
        con: An open DuckDB connection with the `spatial` extension loaded.
        layer_names: Layer names present in the GPKG, from `step1_1_list_layers`.

    Returns:
        A dict mapping each risk table name to its JOIN match count (-1 on error).
    """
    print("\n" + "=" * 60)
    print("Step 1-2-1: 高潮リスク × 建物 JOIN 検証")
    print("=" * 60)
    results = {}

    # Only test risk tables that actually exist in this GPKG.
    all_risk_tables = [
        "uro:HighTideRiskAttribute",
        "uro:RiverFloodingRiskAttribute",
        "uro:TsunamiRiskAttribute",
        "uro:InlandFloodingRiskAttribute",
        "uro:LandSlideRiskAttribute",
    ]
    risk_tables = [t for t in all_risk_tables if t in layer_names] if layer_names else all_risk_tables

    for rtable in risk_tables:
        try:
            row = con.execute(f"""
                SELECT COUNT(*) AS cnt
                FROM st_read('{GPKG_PATH}', layer='{rtable}') r
                JOIN st_read('{GPKG_PATH}', layer='bldg:Building') b
                  ON r.parentId = b.id
            """).fetchone()
            cnt = row[0]
            print(f"  {rtable}: {cnt:,} 件")
            results[rtable] = cnt
        except Exception as e:
            print(f"  {rtable}: [ERROR] {e}")
            results[rtable] = -1

    return results


def step1_2_join_traffic(
    con: duckdb.DuckDBPyConnection, layer_names: list[str]
) -> dict:
    """Verify `tran:TrafficArea.parentId -> tran:Road.id` returns matches.

    Args:
        con: An open DuckDB connection with the `spatial` extension loaded.
        layer_names: Layer names present in the GPKG, from `step1_1_list_layers`.

    Returns:
        A dict mapping each traffic-area table name to its JOIN match count.
    """
    print("\n" + "=" * 60)
    print("Step 1-2-2: TrafficArea × Road JOIN 検証")
    print("=" * 60)
    results = {}

    # Only test tables that actually exist in this GPKG.
    for ttable in [t for t in ["tran:TrafficArea", "tran:AuxiliaryTrafficArea"] if t in layer_names]:
        try:
            row = con.execute(f"""
                SELECT COUNT(*) AS cnt
                FROM st_read('{GPKG_PATH}', layer='{ttable}') t
                JOIN st_read('{GPKG_PATH}', layer='tran:Road') r
                  ON t.parentId = r.id
            """).fetchone()
            cnt = row[0]
            print(f"  {ttable}: {cnt:,} 件")
            results[ttable] = cnt
        except Exception as e:
            print(f"  {ttable}: [ERROR] {e}")
            results[ttable] = -1

    return results


def step1_2_sample_risk_values(con: duckdb.DuckDBPyConnection) -> None:
    """Print sample `depth` / `rank` / `description` values for risk tables.

    Args:
        con: An open DuckDB connection with the `spatial` extension loaded.
    """
    print("\n" + "=" * 60)
    print("Step 1-2-3: リスク属性値サンプル")
    print("=" * 60)

    for rtable in [
        "uro:HighTideRiskAttribute",
        "uro:RiverFloodingRiskAttribute",
    ]:
        print(f"\n  [{rtable}] depth / rank / description サンプル（上位5件）")
        try:
            # Check which columns actually exist before selecting them, since
            # not every risk table shares the same schema.
            schema = con.execute(
                f"DESCRIBE SELECT * FROM st_read('{GPKG_PATH}', layer='{rtable}')"
            ).fetchall()
            available = {r[0] for r in schema}

            select_cols = []
            for col in ["parentId", "depth", "rank", "rankOrg", "description", "adminType"]:
                if col in available:
                    select_cols.append(col)

            if not select_cols:
                print("  対象カラムなし")
                continue

            rows = con.execute(f"""
                SELECT {', '.join(f'"{c}"' for c in select_cols)}
                FROM st_read('{GPKG_PATH}', layer='{rtable}')
                LIMIT 5
            """).fetchall()
            print(f"  カラム: {select_cols}")
            for r in rows:
                print(f"    {r}")
        except Exception as e:
            print(f"  [ERROR] {e}")


def step1_2_traffic_functions(
    con: duckdb.DuckDBPyConnection, layer_names: list[str]
) -> None:
    """Inspect `tran:TrafficArea.function` value distribution.

    In this sample GPKG, TrafficArea is embedded as a VARCHAR/JSON column on
    `tran:Road` rather than existing as its own table, so this falls back to
    inspecting `Road.trafficArea` when the standalone table is absent.

    Args:
        con: An open DuckDB connection with the `spatial` extension loaded.
        layer_names: Layer names present in the GPKG, from `step1_1_list_layers`.
    """
    print("\n" + "=" * 60)
    print('Step 1-2-4: TrafficArea function 値確認')
    print("=" * 60)

    if "tran:TrafficArea" in layer_names:
        # The standalone table exists in this GPKG.
        rows = con.execute(f"""
            SELECT "function", COUNT(*) AS cnt
            FROM st_read('{GPKG_PATH}', layer='tran:TrafficArea')
            GROUP BY "function"
            ORDER BY cnt DESC
        """).fetchall()
        for r in rows:
            print(f"  function={r[0]!r}  件数={r[1]:,}")
    else:
        # Fall back to the embedded tran:Road.trafficArea (VARCHAR/JSON) column.
        print("  tran:TrafficArea は独立テーブルとして存在しない。")
        print("  → tran:Road の trafficArea/auxiliaryTrafficArea カラムに埋め込み済みであることを確認。")
        rows = con.execute(f"""
            SELECT trafficArea, auxiliaryTrafficArea
            FROM st_read('{GPKG_PATH}', layer='tran:Road')
            WHERE trafficArea IS NOT NULL
            LIMIT 2
        """).fetchall()
        for r in rows:
            print(f"  trafficArea サンプル: {str(r[0])[:120]}...")
            print(f"  auxiliaryTrafficArea サンプル: {str(r[1])[:120]}...")


# ============================================================
# Entry point
# ============================================================

def run_phase1() -> dict:
    """Run every investigation step and return results for the sanity checks.

    Returns:
        A dict with `layers`, `layer_names`, `schema_map`, `risk_join`, and
        `traffic_join` keys, consumed by `tests/sanity_checks.py`.
    """
    con = connect()
    result = {}

    # Step 1-1
    layers = step1_1_list_layers(con)
    result["layers"] = layers
    result["layer_names"] = [l["name"] for l in layers]

    # Only inspect tables that actually exist — accessing a layer name that
    # isn't in the GPKG crashes the DuckDB spatial extension (segfault), not a
    # catchable Python exception.
    schema_map = {}
    existing_layers = set(result["layer_names"])
    for tbl in TARGET_TABLES:
        if tbl in existing_layers:
            cols = step1_1_inspect_table(con, tbl)
        else:
            print(f"\n--- テーブル: {tbl} [SKIP: GPKGに存在しない] ---")
            cols = []
        schema_map[tbl] = cols
    result["schema_map"] = schema_map

    # Step 1-2
    layer_names = result["layer_names"]
    result["risk_join"] = step1_2_join_risk(con, layer_names)
    result["traffic_join"] = step1_2_join_traffic(con, layer_names)
    step1_2_sample_risk_values(con)
    step1_2_traffic_functions(con, layer_names)

    con.close()
    return result


if __name__ == "__main__":
    run_phase1()
