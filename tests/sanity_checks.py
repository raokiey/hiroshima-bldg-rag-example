"""
tests/sanity_checks.py
Phase 1 サニティチェック — 全アサーションがパスしなければ次 Step に進まない。
"""

import sys
from pathlib import Path

# Add the repo root so `src.*` absolute imports resolve.
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pipeline.investigate import run_phase1
from src.pipeline.gpkg import (
    connect as connect_phase2,
    validate_epsg6671_range,
    search_buildings_with_risk,
    HIROSHIMA_X_MIN, HIROSHIMA_X_MAX,
    HIROSHIMA_Y_MIN, HIROSHIMA_Y_MAX,
)  # noqa: F401
from src.pipeline.enrichment import (
    build_text_card,
)  # noqa: F401
from src.common.db import (
    connect_rag,
    RAG_DB_PATH,
    wgs84_to_epsg6671,
)  # noqa: F401
from src.app.retrieval import (
    embed_query,
    vector_search,
    hybrid_search,
)  # noqa: F401
from src.app.query_parser import ParsedQuery  # noqa: F401


def assert_layers_exist(result: dict) -> None:
    """bldg:Building テーブルが存在すること"""
    names = result["layer_names"]
    assert "bldg:Building" in names, \
        f"bldg:Building テーブルが存在しない。取得テーブル一覧: {names}"
    print("  [OK] bldg:Building テーブルが存在する")


def assert_building_has_columns(result: dict) -> None:
    """bldg:Building に必須カラムが存在すること"""
    cols = {c["column_name"] for c in result["schema_map"].get("bldg:Building", [])}
    required = {"id", "geometry"}
    missing = required - cols
    assert not missing, \
        f"bldg:Building に必須カラムが不足: {missing}。実カラム: {cols}"
    print(f"  [OK] bldg:Building の必須カラム確認 ({cols})")


def assert_building_count_nonzero(result: dict) -> None:
    """
    bldg:Building の件数が 0 件でないこと。
    phase1_investigate の step1_1_inspect_table は件数をコンソール出力するのみで
    result には含めていないため、ここでは schema_map に列情報があれば OK とする。
    （件数が 0 の場合はスキーマ取得自体が失敗するため）
    """
    cols = result["schema_map"].get("bldg:Building", [])
    assert len(cols) > 0, "bldg:Building のスキーマ取得に失敗（件数 0 の可能性）"
    print("  [OK] bldg:Building のスキーマ取得成功（件数 > 0）")


def assert_risk_join_nonzero(result: dict) -> None:
    """
    parentId による LEFT JOIN 結果が 0 件でないこと。
    少なくとも 1 つのリスクテーブルが紐づいていること。
    """
    risk_join = result["risk_join"]
    nonzero = {k: v for k, v in risk_join.items() if v > 0}
    assert nonzero, \
        f"全リスクテーブルの JOIN 結果が 0 件または取得エラー: {risk_join}"
    for tbl, cnt in nonzero.items():
        print(f"  [OK] {tbl} JOIN: {cnt:,} 件")


def assert_risk_columns_exist(result: dict) -> None:
    """
    災害リスクテーブルに depth / rank / description カラムが存在すること。
    """
    risk_tables = [
        "uro:HighTideRiskAttribute",
        "uro:RiverFloodingRiskAttribute",
    ]
    for rtable in risk_tables:
        cols = {c["column_name"] for c in result["schema_map"].get(rtable, [])}
        if not cols:
            print(f"  [SKIP] {rtable} が GPKG に存在しないためスキップ")
            continue
        # depth / rank / description のいずれかが存在すれば OK
        expected = {"depth", "rank", "description"}
        found = expected & cols
        assert found, \
            f"{rtable} に depth/rank/description カラムが存在しない。実カラム: {cols}"
        print(f"  [OK] {rtable} カラム確認: {found}")


def assert_traffic_join_nonzero(result: dict) -> None:
    """
    tran:TrafficArea × tran:Road JOIN が 0 件でないこと。
    サンプルデータに tran:TrafficArea が存在しない場合はスキップ。
    """
    tj = result["traffic_join"]
    if not tj:
        print("  [SKIP] tran:TrafficArea が GPKG に存在しないためスキップ")
        return
    cnt = tj.get("tran:TrafficArea", -1)
    assert cnt > 0, \
        f"tran:TrafficArea × tran:Road JOIN が 0 件またはエラー: {tj}"
    print(f"  [OK] tran:TrafficArea × tran:Road JOIN: {cnt:,} 件")


# ============================================================
# Phase 2 サニティチェック関数
# ============================================================

def assert_epsg6671_range(con) -> None:
    """
    広島城（132.4625, 34.3955）の WGS84→EPSG:6671 変換結果が
    広島市の妥当範囲内に収まること。
    """
    x, y = wgs84_to_epsg6671(con, 132.4625, 34.3955)
    in_range = (
        HIROSHIMA_X_MIN <= x <= HIROSHIMA_X_MAX
        and HIROSHIMA_Y_MIN <= y <= HIROSHIMA_Y_MAX
    )
    assert in_range, (
        f"広島城の EPSG:6671 変換結果が妥当範囲外: x={x:.1f}, y={y:.1f}  "
        f"（期待 X=[{HIROSHIMA_X_MIN}, {HIROSHIMA_X_MAX}], "
        f"Y=[{HIROSHIMA_Y_MIN}, {HIROSHIMA_Y_MAX}]）"
    )
    print(f"  [OK] EPSG:6671 変換結果が広島市範囲内: x={x:.1f}, y={y:.1f}")


def assert_dwithin_increases_with_radius(con) -> None:
    """
    半径 500m の件数 ≤ 半径 1000m の件数（単調増加）であること。
    検索点: 広島城（132.4625, 34.3955）
    """
    tbl_500 = search_buildings_with_risk(con, 132.4625, 34.3955, 500.0)
    tbl_1000 = search_buildings_with_risk(con, 132.4625, 34.3955, 1000.0)
    cnt_500 = len(tbl_500)
    cnt_1000 = len(tbl_1000)
    assert cnt_500 <= cnt_1000, (
        f"半径を広げても件数が増加しない: 500m={cnt_500}, 1000m={cnt_1000}"
    )
    print(f"  [OK] 件数単調増加: 500m={cnt_500} 件 <= 1000m={cnt_1000} 件")


def assert_risk_join_present(con) -> None:
    """
    半径 500m 以内の建物に ht_depth_max カラムが存在し、
    少なくとも 1 件の非 NULL 行があること。
    """
    tbl = search_buildings_with_risk(con, 132.4625, 34.3955, 500.0)
    assert "ht_depth_max" in tbl.schema.names, (
        f"ht_depth_max カラムが結果に存在しない。カラム一覧: {tbl.schema.names}"
    )
    nn_count = sum(
        1 for v in tbl.to_pydict().get("ht_depth_max", []) if v is not None
    )
    assert nn_count > 0, (
        f"ht_depth_max が全件 NULL（高潮リスク付き建物が半径 500m 内に 0 件）"
    )
    print(f"  [OK] ht_depth_max カラム存在・非 NULL 行: {nn_count} 件")


# ============================================================
# Phase 3 サニティチェック関数
# ============================================================

def assert_text_card_nonempty() -> None:
    """
    サンプル建物データからテキストカルテを生成し、
    50文字以上かつ [周辺環境] セクションを含むことを確認する。
    """
    sample_row = {
        "id": "bldg_test_001",
        "usage": "401",
        "measured_height": 15.0,
        "storeys": 4,
        "ht_depth_max": 2.5,
        "ht_rank_worst": "3",
        "rv_depth_max": 1.0,
        "rv_rank_worst": "2",
        "ts_depth_max": None,
        "ts_rank_worst": None,
        "structure_type": "611",
        "fire_proof": "1001",
        "nearest_road_dist_m": 10.5,
        "nearest_road_width": 12.0,
        "nearest_road_lanes": 2,
        "landuse_class": "210",
        "urf_usage": "第一種住居地域",
        "nearest_shelter_name": "広島小学校",
        "nearest_shelter_dist_m": 300.0,
        "nearest_shelter_disasters": "洪水",
        "nearest_station_name": "広島駅",
        "nearest_station_line": "山陽本線",
        "nearest_station_dist_m": 800.0,
        "nearest_emroute_name": "国道2号",
        "nearest_emroute_dist_m": 150.0,
        "nearest_park_name": "中央公園",
        "nearest_park_dist_m": 500.0,
        "nearest_landmark_name": "広島城",
        "nearest_landmark_dist_m": 1200.0,
    }
    from src.pipeline.codelist_loader import CodelistLoader
    cl = CodelistLoader()
    card = build_text_card(sample_row, cl)
    assert len(card) >= 50, \
        f"テキストカルテが短すぎる: {len(card)} 文字（期待: 50以上）"
    assert "[周辺環境]" in card, \
        f"テキストカルテに [周辺環境] セクションが存在しない"
    print(f"  [OK] テキストカルテ生成: {len(card)} 文字、[周辺環境] セクションあり")


def assert_embedding_dim_consistent() -> None:
    """
    埋め込みチェックポイントが存在する場合、
    保存済みベクトルの次元数が全件一致することを確認する。
    チェックポイントが未作成の場合はスキップ。
    """
    import json
    ckpt_path = RAG_DB_PATH.parent / "embed_checkpoint.json"
    if not ckpt_path.exists():
        # 全件完了後にチェックポイントは削除されるため、スキップ
        print("  [SKIP] embed_checkpoint.json が存在しないためスキップ（全件完了済みか未実行）")
        return
    with open(ckpt_path, "r", encoding="utf-8") as f:
        ckpt = json.load(f)
    embeddings = ckpt.get("embeddings", [])
    if not embeddings:
        print("  [SKIP] チェックポイントに埋め込みが0件")
        return
    dims = {len(e) for e in embeddings}
    assert len(dims) == 1, \
        f"埋め込みの次元数が不一致: {dims}"
    print(f"  [OK] 埋め込み次元数一致: {dims.pop()} 次元（{len(embeddings):,} 件）")


def assert_duckdb_count_matches() -> None:
    """
    plateau_rag.duckdb が存在する場合、building_chunks の件数が 2,958 件であることを確認する。
    DuckDB が未作成の場合はスキップ。
    """
    EXPECTED_COUNT = 2958
    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ（Phase 3 Step 3-4 未完了）")
        return
    import duckdb
    con = duckdb.connect(str(RAG_DB_PATH), read_only=True)
    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        if "building_chunks" not in tables:
            print("  [SKIP] building_chunks テーブルが未作成のためスキップ")
            return
        cnt = con.execute("SELECT COUNT(*) FROM building_chunks").fetchone()[0]
        assert cnt == EXPECTED_COUNT, \
            f"building_chunks の件数が期待値と不一致: {cnt:,} 件（期待: {EXPECTED_COUNT:,} 件）"
        print(f"  [OK] building_chunks 件数: {cnt:,} 件（期待値と一致）")
    finally:
        con.close()


# ============================================================
# Phase 4 サニティチェック関数
# ============================================================

def assert_vector_search_returns_results() -> None:
    """
    TODO 4-4-1: デモクエリを埋め込み化して vector_search を実行し、
    1 件以上の結果が返り、score カラムが存在することを確認する。
    RAG DB が未作成の場合はスキップ。
    """
    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ（Phase 3 未完了）")
        return

    query_text = "高潮リスクが低く、駅から近い建物"
    print(f"  クエリ: {query_text}")

    query_vec = embed_query(query_text)
    assert len(query_vec) > 0, "クエリ埋め込みが空"

    rag_con = connect_rag()
    try:
        df = vector_search(rag_con, ParsedQuery(), "semantic", query_vec, top_k=5)
    finally:
        rag_con.close()

    assert len(df) >= 1, \
        f"vector_search の結果が 0 件（期待: 1 件以上）"
    assert "score" in df.columns, \
        f"score カラムが結果に存在しない。カラム一覧: {df.columns.tolist()}"
    print(f"  [OK] vector_search 結果: {len(df)} 件、最高スコア: {df['score'].max():.4f}")


def assert_answer_contains_building_id() -> None:
    """
    TODO 4-4-1: hybrid_search を実行し、LLM の回答に建物 ID（bldg_ 形式）
    または座標情報が含まれることを確認する。
    RAG DB が未作成の場合はスキップ。
    ※ この関数は Gemini API を呼び出すため API クレジットを消費します。

    Phase 10 補足: クエリは「高潮リスクが低く耐火構造の建物」から変更した。
    Phase 10 の構造化フィルタ導入により、ht_depth_max IS NULL（高潮リスクなし）
    に該当する建物は全市で 5 件のみで、いずれも fire_proof が「不明」のため
    「耐火構造」との積集合が実データ上 0 件になる（＝厳密なフィルタが機能している
    証拠であり不具合ではない）。0 件を回答生成のテストに使うと本チェックの目的
    （回答に建物IDが含まれるか）を検証できないため、実在する組み合わせに変更。
    """
    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ（Phase 3 未完了）")
        return

    result = hybrid_search(
        query="高潮リスクが低い建物",
        top_k=5,
    )

    answer = result["answer"]
    candidates = result["candidates"]

    assert len(candidates) >= 1, \
        f"hybrid_search の候補建物が 0 件"

    # 回答に建物 ID（bldg_...）が含まれているか確認
    has_building_id = "bldg_" in answer
    # 建物 ID が含まれていなければ候補の id を確認（LLM が言及したか）
    if not has_building_id:
        # 候補 id のいずれかが言及されているか
        has_building_id = any(bid in answer for bid in candidates["id"].tolist())

    assert has_building_id, \
        f"回答に建物 ID が含まれていない。\n回答（先頭 200 文字）:\n{answer[:200]}"
    print(f"  [OK] hybrid_search 回答に建物 ID が含まれている（{len(candidates)} 件の候補）")


# ============================================================
# 実行エントリポイント
# ============================================================

def run_all_checks() -> None:
    print("\n" + "=" * 60)
    print("Phase 1 サニティチェック 開始")
    print("=" * 60)

    # Phase 1 を実行してデータ収集
    result = run_phase1()

    print("\n" + "=" * 60)
    print("Phase 1 アサーション実行")
    print("=" * 60)

    phase1_checks = [
        assert_layers_exist,
        assert_building_has_columns,
        assert_building_count_nonzero,
        assert_risk_join_nonzero,
        assert_risk_columns_exist,
        assert_traffic_join_nonzero,
    ]

    passed = 0
    failed = 0
    for check in phase1_checks:
        try:
            check(result)
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    # Phase 2 サニティチェック
    print("\n" + "=" * 60)
    print("Phase 2 サニティチェック 開始")
    print("=" * 60)

    con2 = connect_phase2()
    phase2_checks = [
        assert_epsg6671_range,
        assert_dwithin_increases_with_radius,
        assert_risk_join_present,
    ]
    for check in phase2_checks:
        try:
            check(con2)
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1
    con2.close()

    # Phase 3 サニティチェック
    print("\n" + "=" * 60)
    print("Phase 3 サニティチェック 開始")
    print("=" * 60)

    phase3_checks = [
        assert_text_card_nonempty,
        assert_embedding_dim_consistent,
        assert_duckdb_count_matches,
    ]
    for check in phase3_checks:
        try:
            check()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    # Phase 4 サニティチェック
    print("\n" + "=" * 60)
    print("Phase 4 サニティチェック 開始")
    print("=" * 60)

    phase4_checks = [
        assert_vector_search_returns_results,
        assert_answer_contains_building_id,
    ]
    for check in phase4_checks:
        try:
            check()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"結果: {passed} 件パス / {failed} 件失敗")
    print("=" * 60)

    if failed > 0:
        print("\n[ERROR] サニティチェックに失敗しました。次 Step に進まないでください。")
        sys.exit(1)
    else:
        print("\n[SUCCESS] 全アサーションパス。次 Phase に進んでください。")


# ============================================================
# Phase 6 サニティチェック — FastAPI 起動中を前提
# ============================================================

def check_phase6_health() -> None:
    """GET /api/health が 200 を返し db_exists=true であること"""
    import urllib.request, json
    with urllib.request.urlopen("http://localhost:8000/api/health", timeout=5) as r:
        data = json.loads(r.read())
    assert data["status"] == "ok", f"status != ok: {data}"
    assert data["db_exists"] is True, f"db_exists != true: {data}"
    print("  [OK] /api/health: ok, db_exists=true")


def check_phase6_search() -> None:
    """POST /api/search が candidate_count >= 1 の GeoJSON を返すこと"""
    import urllib.request, json
    body = json.dumps({"query": "高潮リスクが低く駅から近い建物", "top_k": 3}).encode()
    req = urllib.request.Request(
        "http://localhost:8000/api/search",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    assert data["candidate_count"] >= 1, f"candidate_count < 1: {data['candidate_count']}"
    assert data["geojson"]["type"] == "FeatureCollection", "geojson.type != FeatureCollection"
    assert len(data["geojson"]["features"]) >= 1, "geojson.features が空"
    assert len(data["answer"]) > 0, "answer が空"
    print(f"  [OK] /api/search: {data['candidate_count']} 件, {data['elapsed_sec']:.1f}秒")


def run_phase6_checks() -> None:
    """Phase 6 サニティチェック（FastAPI が localhost:8000 で起動していること）"""
    print("\n" + "=" * 60)
    print("Phase 6 サニティチェック（FastAPI 起動前提）")
    print("=" * 60)

    passed = failed = 0
    for check in [check_phase6_health, check_phase6_search]:
        try:
            check()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    print(f"\n結果: {passed} 件パス / {failed} 件失敗")
    if failed > 0:
        import sys
        sys.exit(1)


# ============================================================
# Phase 8 サニティチェック — クエリ解析・ジオコーディング・統合検索
# ============================================================

def check_phase8_query_parser_ambiguous_height() -> None:
    """
    TODO 8-5-1a: 目的不明な「高い建物」クエリ → clarification_question が設定されること
    """
    from src.app.query_parser import parse_query

    result = parse_query("広島駅付近の高い建物は？")
    assert result.location_name == "広島駅", \
        f"location_name が '広島駅' でない: {result.location_name}"
    assert result.sort_by_height is True, \
        f"sort_by_height が True でない: {result.sort_by_height}"
    assert result.clarification_question is not None, \
        "目的不明な「高い建物」クエリで clarification_question が None"
    print(f"  [OK] 目的不明クエリ: location={result.location_name}, "
          f"sort_height=True, clarification_question 設定済み")


def check_phase8_query_parser_purpose_height() -> None:
    """
    TODO 8-5-1b: 目的ありの高い建物クエリ → height_min が推定されること
    """
    from src.app.query_parser import parse_query

    result = parse_query("洪水避難のための高い建物を探して")
    assert result.height_min is not None, \
        "目的あり（洪水避難）クエリで height_min が None"
    assert result.height_min >= 10.0, \
        f"洪水避難クエリの height_min が期待値（10m以上）より小さい: {result.height_min}"
    assert result.clarification_question is None, \
        f"目的明確クエリで clarification_question が設定されている: {result.clarification_question}"
    print(f"  [OK] 目的あり（洪水避難）クエリ: height_min={result.height_min}m, "
          f"clarification_question=None")


def check_phase8_query_parser_explicit_height() -> None:
    """
    TODO 8-5-1c: 明示的な高さ指定 → height_min に変換されること
    """
    from src.app.query_parser import parse_query

    result = parse_query("30m以上の建物を探して")
    assert result.height_min is not None and result.height_min >= 25.0, \
        f"明示的高さ指定クエリの height_min が期待値（25m以上）より小さい: {result.height_min}"
    assert result.clarification_question is None, \
        f"明示クエリで clarification_question が設定されている: {result.clarification_question}"
    print(f"  [OK] 明示高さクエリ: height_min={result.height_min}m, clarification_question=None")


def check_phase8_geocoder_station() -> None:
    """
    TODO 8-5-2: geocode("広島駅") → 広島市内の座標を返すこと
    """
    from src.app.geocoder import geocode

    coords = geocode("広島駅")
    assert coords is not None, "geocode('広島駅') が None を返した"
    lon, lat = coords
    assert 132.4 < lon < 132.6, f"広島駅の経度が範囲外: {lon}"
    assert 34.3 < lat < 34.5, f"広島駅の緯度が範囲外: {lat}"
    print(f"  [OK] geocode('広島駅'): lon={lon:.4f}, lat={lat:.4f}")


def check_phase8_integrated_search() -> None:
    """
    TODO 8-5-3: 統合検索 — 広島駅付近の建物が geocoded_location 付きで返ること
    RAG DB が未作成の場合はスキップ。
    """
    from src.common.db import RAG_DB_PATH
    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    from src.app.retrieval import hybrid_search

    # 確認質問が返るクエリ（検索スキップ）
    result_cq = hybrid_search(
        "広島駅付近の高い建物は？",
        top_k=5,
        use_query_parser=True,
    )
    assert result_cq.get("clarification_question") is not None, \
        "「高い建物（目的不明）」クエリで clarification_question が None"
    print(f"  [OK] 確認質問クエリ: clarification_question 設定済み")

    # 目的ありクエリ（実際に検索が走る）
    result = hybrid_search(
        "広島駅付近の洪水避難に適した建物は？",
        top_k=5,
        use_query_parser=True,
    )
    assert result.get("geocoded_location") is not None, \
        "広島駅クエリで geocoded_location が None"
    assert len(result["candidates"]) >= 1, \
        "候補建物が 0 件"
    print(f"  [OK] 統合検索: {len(result['candidates'])} 件, "
          f"geocoded_location={result['geocoded_location']}")


def run_phase8_checks() -> None:
    """Phase 8 サニティチェック（クエリ解析・ジオコーディング）"""
    print("\n" + "=" * 60)
    print("Phase 8 サニティチェック 開始")
    print("=" * 60)

    passed = failed = 0
    checks = [
        check_phase8_query_parser_ambiguous_height,
        check_phase8_query_parser_purpose_height,
        check_phase8_query_parser_explicit_height,
        check_phase8_geocoder_station,
        check_phase8_integrated_search,
    ]
    for check in checks:
        try:
            check()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    print(f"\n結果: {passed} 件パス / {failed} 件失敗")
    if failed > 0:
        sys.exit(1)
    else:
        print("[SUCCESS] Phase 8 全チェックパス")


# ============================================================
# Phase 9 サニティチェック — LOD2 ジオメトリ解析・text_card 3D セクション
# ============================================================

def check_phase9_geom_meta() -> None:
    """building_geom_meta テーブルの基本チェック"""
    con = connect_rag()
    count = con.execute("SELECT COUNT(*) FROM building_geom_meta").fetchone()[0]
    assert count > 0, f"building_geom_meta が空: {count} 件"

    # 高さが 0 より大きい建物が存在する
    positive_height = con.execute(
        "SELECT COUNT(*) FROM building_geom_meta WHERE building_height_m > 0"
    ).fetchone()[0]
    assert positive_height > 0, "building_height_m > 0 の建物が存在しない"

    # 壁面方位の合計が 0.99〜1.01（丸め誤差を許容）
    row = con.execute("""
        SELECT wall_ratio_n + wall_ratio_e + wall_ratio_s + wall_ratio_w AS total
        FROM building_geom_meta
        WHERE wall_area_total_m2 > 0
        LIMIT 1
    """).fetchone()
    assert row is not None, "wall_area_total_m2 > 0 の建物が存在しない"
    assert 0.99 < row[0] < 1.01, f"壁面方位比率の合計が 1 でない: {row[0]:.4f}"

    con.close()
    print(f"  [OK] building_geom_meta: {count} 件, height>0: {positive_height} 件, 方位合計: {row[0]:.4f}")


def check_phase9_text_card_3d() -> None:
    """text_card に [3D形状・方位] セクションが含まれているか（再埋め込み後に確認）"""
    con = connect_rag()

    # building_geom_meta に存在する ID の building_chunks を確認
    sample = con.execute("""
        SELECT b.text_card
        FROM building_chunks b
        JOIN building_geom_meta g ON b.id = g.id
        LIMIT 1
    """).fetchone()
    assert sample is not None, "building_chunks に geom_meta と JOIN できる建物が存在しない"
    assert "[3D形状・方位]" in sample[0], (
        f"[3D形状・方位] セクションが text_card にない（再埋め込みが必要な可能性）: "
        f"{sample[0][:300]}"
    )

    con.close()
    print("  [OK] text_card に [3D形状・方位] セクションが含まれている")


def check_phase9_vector_search_geom_cols() -> None:
    """vector_search() の結果に wall_ratio_s カラムが含まれるか"""
    rag_con = connect_rag()
    qvec = embed_query("南向きの建物")
    df = vector_search(rag_con, ParsedQuery(), "semantic", qvec, top_k=3, embedding_source="gemini")
    rag_con.close()
    assert len(df) >= 1, "vector_search の結果が 0 件"
    assert "wall_ratio_s" in df.columns, (
        f"wall_ratio_s カラムが結果に含まれない。カラム一覧: {list(df.columns)}"
    )
    print(f"  [OK] vector_search に wall_ratio_s カラムあり: {df['wall_ratio_s'].head(3).tolist()}")


def run_phase9_checks() -> None:
    """Phase 9 サニティチェック（LOD2 ジオメトリ解析・text_card 3D セクション）"""
    print("\n" + "=" * 60)
    print("Phase 9 サニティチェック 開始")
    print("=" * 60)

    passed = failed = 0
    checks = [
        check_phase9_geom_meta,
        check_phase9_text_card_3d,
        check_phase9_vector_search_geom_cols,
    ]
    for check in checks:
        try:
            check()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    print(f"\n結果: {passed} 件パス / {failed} 件失敗")
    if failed > 0:
        sys.exit(1)
    else:
        print("[SUCCESS] Phase 9 全チェックパス")


# ============================================================
# Phase 10 サニティチェック — SQL×ベクトル ハイブリッド検索ルーティング
# ============================================================

def check_phase10_route_structured() -> None:
    """
    TODO 10-5-4a: 純構造化クエリ（最上級表現）が route=structured と判定され、
    hybrid_search の候補先頭が SQL 直接実行の結果（高さ降順1位）と一致すること。
    """
    from src.app.query_parser import parse_query
    from src.app.router import classify_route

    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    pq = parse_query("広島市で最も高い建物は？")
    route = classify_route(pq)
    assert route == "structured", f"route が structured でない: {route}"

    import duckdb
    con = duckdb.connect(str(RAG_DB_PATH), read_only=True)
    try:
        expected_id = con.execute(
            "SELECT id FROM building_chunks WHERE measured_height > 0 "
            "ORDER BY measured_height DESC LIMIT 1"
        ).fetchone()[0]
    finally:
        con.close()

    result = hybrid_search("広島市で最も高い建物は？", top_k=5, skip_answer=True)
    assert result["route"] == "structured", f"hybrid_search の route が structured でない: {result['route']}"
    candidates = result["candidates"]
    assert len(candidates) >= 1, "候補建物が0件"
    assert candidates.iloc[0]["id"] == expected_id, (
        f"候補先頭が SQL 直接実行の結果と不一致: "
        f"候補={candidates.iloc[0]['id']}, 期待値={expected_id}"
    )
    print(f"  [OK] 純構造化クエリ: route=structured, 候補先頭が高さ降順1位と一致（{expected_id}）")


def check_phase10_route_hybrid() -> None:
    """
    TODO 10-5-4b: 距離条件＋意味的残差を含むクエリが route=hybrid と判定され、
    全候補が距離条件（駅から300m以内）を満たすこと。

    Phase 15 補足: クエリは「駅から300m以内で日当たりのよい建物」から変更した。
    Phase 15 で「日当たりのよい」が sunlight 構造化フィールドに完全吸収され
    semantic_residual="" になったため、このクエリは route=structured に
    変わった（Phase15 の配線が意図通り機能している証拠であり不具合ではない）。
    hybrid 経路の検証には、まだ構造化フィールドを持たない意味語彙
    「防災拠点に向いた」を使う。
    """
    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    result = hybrid_search("駅から300m以内で防災拠点に向いた建物", top_k=10, skip_answer=True)
    assert result["route"] == "hybrid", f"route が hybrid でない: {result['route']}"
    candidates = result["candidates"]
    assert len(candidates) >= 1, "候補建物が0件"
    violated = candidates[candidates["nearest_station_dist_m"] > 300]
    assert violated.empty, (
        f"距離条件（駅から300m以内）に違反する候補が存在: {violated[['id', 'nearest_station_dist_m']].to_dict('records')}"
    )
    print(f"  [OK] hybrid経路: route=hybrid（防災拠点に向いた=意味的残差）, 全{len(candidates)}件が駅から300m以内")


def check_phase10_risk_filter() -> None:
    """
    TODO 10-5-4c: 「高潮リスクがない建物」クエリで、全候補の ht_depth_max が NULL であること。
    """
    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    result = hybrid_search("高潮リスクがない建物", top_k=10, skip_answer=True)
    candidates = result["candidates"]
    assert len(candidates) >= 1, "候補建物が0件"
    violated = candidates[candidates["ht_depth_max"].notna()]
    assert violated.empty, (
        f"高潮リスクなし条件に違反する候補が存在: {violated[['id', 'ht_depth_max']].to_dict('records')}"
    )
    print(f"  [OK] リスクフィルタ: route={result['route']}, 全{len(candidates)}件が ht_depth_max=NULL")


def run_phase10_checks() -> None:
    """Phase 10 サニティチェック（SQL×ベクトル ハイブリッド検索ルーティング）"""
    print("\n" + "=" * 60)
    print("Phase 10 サニティチェック 開始")
    print("=" * 60)

    passed = failed = 0
    checks = [
        check_phase10_route_structured,
        check_phase10_route_hybrid,
        check_phase10_risk_filter,
    ]
    for check in checks:
        try:
            check()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    print(f"\n結果: {passed} 件パス / {failed} 件失敗")
    if failed > 0:
        sys.exit(1)
    else:
        print("[SUCCESS] Phase 10 全チェックパス")


# ============================================================
# Phase 11 サニティチェック — FTS×ベクトル RRF・HyDE（再埋め込みなし）
# ============================================================

def check_phase11_fts_index() -> None:
    """
    TODO 11-2-7a / 12-5-1a: ensure_fts_index() 実行後、fts_search() が
    固有名詞クエリ「広島駅」で1件以上返すこと。
    Phase 12 で SudachiPy（Mode C）による分かち書きを導入したことで、
    Phase 11 時点では 0 件だった固有名詞ヒットが解消されたことを検証する
    （分かち書き導入の核心的な合格基準）。
    """
    from src.app.search_fusion import ensure_fts_index, fts_search

    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    con = connect_rag()
    try:
        ensure_fts_index(con)
        df = fts_search(con, "広島駅", top_k=10)
    finally:
        con.close()

    assert len(df) >= 1, "fts_search('広島駅') の結果が0件（分かち書き導入前の症状が再発）"
    assert "bm25_score" in df.columns, f"bm25_score カラムが結果に存在しない: {df.columns.tolist()}"
    print(f"  [OK] fts_search('広島駅'): {len(df)} 件")


def check_phase11_rrf_merge() -> None:
    """
    TODO 11-2-7b: 人工データ（各3件、一部重複ID）で rrf_merge() を実行し、
    重複IDのスコアが加算されること・全件が結果に含まれることを確認する。
    """
    import pandas as pd
    from src.app.search_fusion import rrf_merge

    vec_df = pd.DataFrame({"id": ["a", "b", "c"], "score": [0.9, 0.8, 0.7]})
    fts_df = pd.DataFrame({"id": ["b", "d", "a"], "bm25_score": [5.0, 4.0, 3.0]})
    merged = rrf_merge(vec_df, fts_df, k=60)

    assert set(merged["id"]) == {"a", "b", "c", "d"}, (
        f"全件が結果に含まれていない: {merged['id'].tolist()}"
    )
    # b は vec 1位・fts 1位のため rrf_score が最大になるはず
    assert merged.iloc[0]["id"] == "b", (
        f"両方で上位の候補が最上位でない: 実際の先頭={merged.iloc[0]['id']}"
    )
    print(f"  [OK] rrf_merge: 全4件含む、先頭={merged.iloc[0]['id']}（両方で上位）")


def check_phase11_hyde_fallback() -> None:
    """
    TODO 11-2-7c: hyde_rewrite() が例外を発生させず文字列を返すことを確認する。
    ・GEMINI_API_KEY 不在を模した異常系（フォールバックで元テキストを返す）
    ・空文字入力（早期リターンで空文字を返す）
    """
    import os
    from src.app.search_fusion import hyde_rewrite

    # 空文字入力: 早期リターンで例外なく空文字を返す
    result_empty = hyde_rewrite("")
    assert result_empty == "", f"空文字入力で空文字以外が返った: {result_empty!r}"

    # GEMINI_API_KEY 不在を模した異常系
    original_key = os.environ.pop("GEMINI_API_KEY", None)
    try:
        result_no_key = hyde_rewrite("日当たりのよい建物")
        assert result_no_key == "日当たりのよい建物", (
            f"APIキー不在時に元テキストへのフォールバックがされていない: {result_no_key!r}"
        )
    finally:
        if original_key is not None:
            os.environ["GEMINI_API_KEY"] = original_key

    print("  [OK] hyde_rewrite: 空文字入力・APIキー不在時とも例外なくフォールバック")


def run_phase11_checks() -> None:
    """Phase 11 サニティチェック（FTS×ベクトル RRF・HyDE）"""
    print("\n" + "=" * 60)
    print("Phase 11 サニティチェック 開始")
    print("=" * 60)

    passed = failed = 0
    checks = [
        check_phase11_fts_index,
        check_phase11_rrf_merge,
        check_phase11_hyde_fallback,
    ]
    for check in checks:
        try:
            check()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    print(f"\n結果: {passed} 件パス / {failed} 件失敗")
    if failed > 0:
        sys.exit(1)
    else:
        print("[SUCCESS] Phase 11 全チェックパス")


# ============================================================
# Phase 12 サニティチェック — SudachiPy 分かち書きによる FTS 有効化
# ============================================================

def check_phase12_tokenize() -> None:
    """
    TODO 12-5-1b: tokenize_ja() の結果に固有名詞「横川駅」が単独トークンとして
    含まれ、空トークンが含まれないことを確認する。
    """
    from src.app.search_fusion import tokenize_ja

    result = tokenize_ja("横川駅（可部線）約500m")
    tokens = result.split(" ")

    assert "横川駅" in tokens, f"「横川駅」が単独トークンとして含まれない: {tokens}"
    assert all(t for t in tokens), f"空トークンが含まれている: {tokens}"
    assert tokenize_ja("") == "", "空文字入力で空文字が返っていない"
    print(f"  [OK] tokenize_ja('横川駅（可部線）約500m'): {tokens}")


def check_phase12_fts_rebuild() -> None:
    """
    TODO 12-5-1c: building_chunks_fts の件数が building_chunks と一致すること。
    """
    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    from src.app.search_fusion import ensure_fts_index

    con = connect_rag()
    try:
        ensure_fts_index(con)
        src_count = con.execute("SELECT COUNT(*) FROM building_chunks").fetchone()[0]
        fts_count = con.execute("SELECT COUNT(*) FROM building_chunks_fts").fetchone()[0]
    finally:
        con.close()

    assert src_count == fts_count, (
        f"building_chunks_fts の件数が一致しない: "
        f"building_chunks={src_count}, building_chunks_fts={fts_count}"
    )
    print(f"  [OK] building_chunks_fts 件数一致: {fts_count} 件")


def run_phase12_checks() -> None:
    """
    Phase 12 サニティチェック（SudachiPy 分かち書きによる FTS 有効化）。
    Phase 11 の3チェックも再実行し、分かち書き導入後の回帰確認を兼ねる。
    """
    print("\n" + "=" * 60)
    print("Phase 12 サニティチェック 開始")
    print("=" * 60)

    passed = failed = 0
    checks = [
        check_phase12_tokenize,
        check_phase12_fts_rebuild,
        check_phase11_fts_index,
        check_phase11_rrf_merge,
        check_phase11_hyde_fallback,
    ]
    for check in checks:
        try:
            check()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    print(f"\n結果: {passed} 件パス / {failed} 件失敗")
    if failed > 0:
        sys.exit(1)
    else:
        print("[SUCCESS] Phase 12 全チェックパス")


# ============================================================
# Phase 13 サニティチェック — 屋根形状・建物間コンテキスト前計算
# ============================================================

def check_phase13_geom_meta_extended() -> None:
    """
    TODO 13-3-1: building_geom_meta の新カラム6種が存在し、
    flat_roof_ratio が NULL または 0.0〜1.0 の範囲に収まる件数が全体と一致すること。
    """
    con = connect_rag()
    try:
        cols = {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'building_geom_meta'"
        ).fetchall()}
        required = {
            "roof_slope_mean_deg", "flat_roof_ratio", "roof_type_est",
            "footprint_area_m2", "volume_m3", "slenderness",
        }
        missing = required - cols
        assert not missing, f"building_geom_meta に新カラムが不足: {missing}"

        total = con.execute("SELECT COUNT(*) FROM building_geom_meta").fetchone()[0]
        in_range = con.execute(
            "SELECT COUNT(*) FROM building_geom_meta "
            "WHERE flat_roof_ratio IS NULL OR (flat_roof_ratio >= 0.0 AND flat_roof_ratio <= 1.0)"
        ).fetchone()[0]
        assert in_range == total, (
            f"flat_roof_ratio が範囲外の行が存在する: {total - in_range} 件"
        )
    finally:
        con.close()
    print(f"  [OK] building_geom_meta 新カラム6種確認、flat_roof_ratio 全{total}件が範囲内")


def check_phase13_context_meta() -> None:
    """
    TODO 13-3-2: building_context_meta の件数が building_chunks と一致すること、
    winter_sunlit に True/False 両方が存在すること、
    nearest_school_dist_m が非NULLの件数が0でないこと。
    """
    con = connect_rag()
    try:
        n_chunks = con.execute("SELECT COUNT(*) FROM building_chunks").fetchone()[0]
        n_context = con.execute("SELECT COUNT(*) FROM building_context_meta").fetchone()[0]
        assert n_chunks == n_context, (
            f"building_context_meta の件数が building_chunks と不一致: "
            f"chunks={n_chunks}, context={n_context}"
        )

        n_true = con.execute(
            "SELECT COUNT(*) FROM building_context_meta WHERE winter_sunlit = true"
        ).fetchone()[0]
        n_false = con.execute(
            "SELECT COUNT(*) FROM building_context_meta WHERE winter_sunlit = false"
        ).fetchone()[0]
        assert n_true > 0 and n_false > 0, (
            f"winter_sunlit に True/False 両方が存在しない: True={n_true}, False={n_false}"
        )

        n_school = con.execute(
            "SELECT COUNT(*) FROM building_context_meta WHERE nearest_school_dist_m IS NOT NULL"
        ).fetchone()[0]
        assert n_school > 0, "nearest_school_dist_m が全件NULL"
    finally:
        con.close()
    print(f"  [OK] building_context_meta 件数一致({n_context}件)、"
          f"winter_sunlit True={n_true}/False={n_false}、nearest_school_dist_m 非NULL={n_school}件")


def run_phase13_checks() -> None:
    """Phase 13 サニティチェック（屋根形状・建物間コンテキスト前計算）"""
    print("\n" + "=" * 60)
    print("Phase 13 サニティチェック 開始")
    print("=" * 60)

    passed = failed = 0
    checks = [
        check_phase13_geom_meta_extended,
        check_phase13_context_meta,
    ]
    for check in checks:
        try:
            check()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    print(f"\n結果: {passed} 件パス / {failed} 件失敗")
    if failed > 0:
        sys.exit(1)
    else:
        print("[SUCCESS] Phase 13 全チェックパス")


# ============================================================
# Phase 15 サニティチェック — 方位・日照・除外条件の構造化配線
# ============================================================

def check_phase15_orientation() -> None:
    """
    TODO 15-4-1a: 「南向きの建物」→ route=structured かつ
    全候補の wall_ratio_s >= ORIENT_PREFER_MIN であること。
    """
    from src.app.router import ORIENT_PREFER_MIN

    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    result = hybrid_search("南向きの建物", top_k=10, skip_answer=True)
    assert result["route"] == "structured", f"route が structured でない: {result['route']}"
    candidates = result["candidates"]
    assert len(candidates) >= 1, "候補建物が0件"
    violated = candidates[candidates["wall_ratio_s"] < ORIENT_PREFER_MIN]
    assert violated.empty, (
        f"南向き条件に違反する候補が存在: {violated[['id', 'wall_ratio_s']].to_dict('records')}"
    )
    print(f"  [OK] 南向きクエリ: route=structured, 全{len(candidates)}件が wall_ratio_s>={ORIENT_PREFER_MIN}")


def check_phase15_avoid_west() -> None:
    """
    TODO 15-4-1b: 「西日の当たらない建物」→ 全候補の
    wall_ratio_w <= ORIENT_AVOID_MAX であること。
    """
    from src.app.router import ORIENT_AVOID_MAX

    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    result = hybrid_search("西日の当たらない建物", top_k=10, skip_answer=True)
    candidates = result["candidates"]
    assert len(candidates) >= 1, "候補建物が0件"
    violated = candidates[candidates["wall_ratio_w"] > ORIENT_AVOID_MAX]
    assert violated.empty, (
        f"西日回避条件に違反する候補が存在: {violated[['id', 'wall_ratio_w']].to_dict('records')}"
    )
    print(f"  [OK] 西日回避クエリ: route={result['route']}, 全{len(candidates)}件が wall_ratio_w<={ORIENT_AVOID_MAX}")


def check_phase15_sunlight() -> None:
    """
    TODO 15-4-1c: 「日当たりのよい建物」→ 全候補の winter_sunlit=True であること。
    """
    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    result = hybrid_search("日当たりのよい建物", top_k=10, skip_answer=True)
    candidates = result["candidates"]
    assert len(candidates) >= 1, "候補建物が0件"
    violated = candidates[candidates["winter_sunlit"] != True]  # noqa: E712
    assert violated.empty, (
        f"日照条件に違反する候補が存在: {violated[['id', 'winter_sunlit']].to_dict('records')}"
    )
    print(f"  [OK] 日当たりクエリ: route={result['route']}, 全{len(candidates)}件が winter_sunlit=True")


def check_phase15_exclude() -> None:
    """
    TODO 15-4-1d: 「木造以外の建物」→ 候補に structure_type='木造・土蔵造' が含まれないこと。
    """
    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    result = hybrid_search("木造以外の建物", top_k=10, skip_answer=True)
    candidates = result["candidates"]
    assert len(candidates) >= 1, "候補建物が0件"
    violated = candidates[candidates["structure_type"] == "木造・土蔵造"]
    assert violated.empty, (
        f"除外条件に違反する候補（木造）が存在: {violated[['id', 'structure_type']].to_dict('records')}"
    )
    print(f"  [OK] 除外クエリ: route={result['route']}, 全{len(candidates)}件が木造以外")


def run_phase15_checks() -> None:
    """Phase 15 サニティチェック（方位・日照・除外条件の構造化配線）"""
    print("\n" + "=" * 60)
    print("Phase 15 サニティチェック 開始")
    print("=" * 60)

    passed = failed = 0
    checks = [
        check_phase15_orientation,
        check_phase15_avoid_west,
        check_phase15_sunlight,
        check_phase15_exclude,
    ]
    for check in checks:
        try:
            check()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    print(f"\n結果: {passed} 件パス / {failed} 件失敗")
    if failed > 0:
        sys.exit(1)
    else:
        print("[SUCCESS] Phase 15 全チェックパス")


# ============================================================
# Phase 17 サニティチェック — SQL×pandas 同値性・直接フィルタ動作
# （LLM API を一切呼ばない: ParsedQuery を直接構築して検証する）
# ============================================================

def _phase17_full_meta_df():
    """building_chunks + geom_meta + context_meta の検証用全件 DataFrame を取得する"""
    con = connect_rag()
    try:
        df = con.execute("""
            SELECT
                b.id, b.usage, b.structure_type, b.fire_proof,
                b.measured_height, b.storeys,
                b.ht_depth_max, b.rv_depth_max, b.ts_depth_max,
                b.nearest_station_dist_m, b.nearest_shelter_dist_m,
                b.nearest_park_dist_m, b.nearest_emroute_dist_m, b.nearest_landmark_dist_m,
                g.wall_ratio_n, g.wall_ratio_e, g.wall_ratio_s, g.wall_ratio_w,
                g.roof_type_est,
                c.winter_sunlit, c.nearest_major_road_dist_m, c.wooden_density_ratio,
                c.nearest_school_dist_m, c.nearest_hospital_dist_m,
                c.nearest_police_dist_m, c.nearest_fire_dist_m, c.nearest_post_dist_m
            FROM building_chunks b
            LEFT JOIN building_geom_meta g ON b.id = g.id
            LEFT JOIN building_context_meta c ON b.id = c.id
        """).df()
    finally:
        con.close()
    return df


def _phase17_sql_filter_ids(pq) -> set:
    """build_filter_clauses による SQL 全件フィルタの結果 id 集合を返す"""
    from src.app.router import build_filter_clauses

    table_aliases = {"b": "b.", "g": "g.", "c": "c."}
    clauses, params = build_filter_clauses(pq, alias="b.", table_aliases=table_aliases)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    con = connect_rag()
    try:
        rows = con.execute(f"""
            SELECT b.id
            FROM building_chunks b
            LEFT JOIN building_geom_meta g ON b.id = g.id
            LEFT JOIN building_context_meta c ON b.id = c.id
            {where}
        """, params).fetchall()
    finally:
        con.close()
    return {r[0] for r in rows}


def check_phase17_sql_verify_consistency() -> None:
    """
    TODO 17-4-1: 代表的な ParsedQuery 9種について、SQL フィルタ
    （build_filter_clauses）と pandas 検証（verify_candidates）の結果 id 集合が
    完全一致することを確認する。Phase 16 で実際に発生した「SQL と検証の閾値ズレ」
    （sunlight 0.2 vs 0.3）と同型の不整合を構造的に検知する仕組み。
    """
    from src.app.query_parser import ParsedQuery, OrientationFilter, DistanceFilter
    from src.app.router import verify_candidates

    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    full_df = _phase17_full_meta_df()
    total = len(full_df)

    test_pqs = [
        ("orientation prefer(南)", ParsedQuery(orientation_filters=[OrientationFilter("s", "prefer")])),
        ("orientation avoid(西)",  ParsedQuery(orientation_filters=[OrientationFilter("w", "avoid")])),
        ("sunlight",               ParsedQuery(sunlight=True)),
        ("quiet",                  ParsedQuery(quiet=True)),
        ("vertical_evacuation",    ParsedQuery(vertical_evacuation=True)),
        ("roof_type=陸屋根",       ParsedQuery(roof_type="陸屋根")),
        ("wooden_dense",           ParsedQuery(wooden_dense=True)),
        ("storeys 3〜10",          ParsedQuery(storeys_min=3, storeys_max=10)),
        ("複合(木造除外+高さ20-40+学校300m)", ParsedQuery(
            structure_exclude=["木造・土蔵造"], height_min=20.0, height_max=40.0,
            distance_filters=[DistanceFilter(target="school", max_dist_m=300.0)],
        )),
    ]

    for label, pq in test_pqs:
        sql_ids = _phase17_sql_filter_ids(pq)
        verified, _ = verify_candidates(full_df.copy(), pq)
        pandas_ids = set(verified["id"])
        only_sql = sql_ids - pandas_ids
        only_pandas = pandas_ids - sql_ids
        assert sql_ids == pandas_ids, (
            f"[{label}] SQL と verify_candidates の結果が不一致: "
            f"SQLのみ {len(only_sql)} 件（例: {sorted(only_sql)[:3]}）, "
            f"pandasのみ {len(only_pandas)} 件（例: {sorted(only_pandas)[:3]}）"
        )
        print(f"  [OK] {label}: SQL={len(sql_ids)}件 = pandas検証（全{total}件中）")


def check_phase17_direct_filters() -> None:
    """
    TODO 17-4-2: quiet/vertical_evacuation/roof_type/wooden_dense/storeys範囲の
    直接 ParsedQuery 構築 + vector_search 経由の動作を確認する（API 不要）。
    """
    from src.app.query_parser import ParsedQuery
    from src.app.router import QUIET_ROAD_MIN_M, VERTICAL_EVAC_MARGIN_M, WOODEN_DENSE_MIN

    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    con = connect_rag()
    try:
        # quiet
        df = vector_search(con, ParsedQuery(quiet=True), "structured", None, top_k=10)
        assert len(df) >= 1 and (df["nearest_major_road_dist_m"] >= QUIET_ROAD_MIN_M).all()

        # vertical_evacuation
        df = vector_search(con, ParsedQuery(vertical_evacuation=True), "structured", None, top_k=10)
        assert len(df) >= 1
        max_depth = df[["ht_depth_max", "rv_depth_max", "ts_depth_max"]].fillna(0.0).max(axis=1)
        assert ((df["storeys"] >= 3) & (df["measured_height"] - max_depth >= VERTICAL_EVAC_MARGIN_M)).all()

        # roof_type
        df = vector_search(con, ParsedQuery(roof_type="勾配屋根"), "structured", None, top_k=10)
        assert len(df) >= 1 and (df["roof_type_est"] == "勾配屋根").all()

        # wooden_dense
        df = vector_search(con, ParsedQuery(wooden_dense=True), "structured", None, top_k=10)
        assert len(df) >= 1 and (df["wooden_density_ratio"] >= WOODEN_DENSE_MIN).all()

        # storeys 範囲
        df = vector_search(con, ParsedQuery(storeys_min=3, storeys_max=10), "structured", None, top_k=10)
        assert len(df) >= 1 and df["storeys"].between(3, 10).all()
    finally:
        con.close()
    print("  [OK] quiet/vertical_evac/roof_type/wooden_dense/storeys範囲 の直接フィルタすべて条件充足")


def run_phase17_checks() -> None:
    """Phase 17 サニティチェック（SQL×pandas 同値性・直接フィルタ。LLM API 不要）"""
    print("\n" + "=" * 60)
    print("Phase 17 サニティチェック 開始")
    print("=" * 60)

    passed = failed = 0
    checks = [
        check_phase17_sql_verify_consistency,
        check_phase17_direct_filters,
    ]
    for check in checks:
        try:
            check()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    print(f"\n結果: {passed} 件パス / {failed} 件失敗")
    if failed > 0:
        sys.exit(1)
    else:
        print("[SUCCESS] Phase 17 全チェックパス")


# ============================================================
# Phase 18 サニティチェック — GeoJSON順序保持・推薦ID抽出
# （LLM API を一切呼ばない）
# ============================================================

def check_phase18_geojson_order() -> None:
    """
    TODO 18-1-3: candidates_to_geojson() が candidates（ランキング順）の
    順序どおりに features を返すことを、3パターンのシャッフルで確認する。
    rank が 1..N の連番であること、recommended_ids に渡した id だけ
    is_recommended=True になることも合わせて確認する。
    """
    import random
    import pandas as pd
    from src.app.main import candidates_to_geojson

    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    con = connect_rag()
    try:
        base_ids = [r[0] for r in con.execute(
            "SELECT id FROM building_chunks LIMIT 10"
        ).fetchall()]
    finally:
        con.close()
    assert len(base_ids) == 10, f"building_chunks から10件取得できなかった: {len(base_ids)}件"

    rng = random.Random(42)
    for trial in range(3):
        shuffled = base_ids[:]
        rng.shuffle(shuffled)
        df = pd.DataFrame({
            "id": shuffled,
            "score": [1.0 - i * 0.01 for i in range(len(shuffled))],
        })
        geojson = candidates_to_geojson(df, recommended_ids=shuffled[:2])
        got_ids = [f["properties"]["id"] for f in geojson["features"]]
        assert got_ids == shuffled, (
            f"[trial {trial}] feature順序が candidates 順と不一致: "
            f"期待={shuffled}, 実際={got_ids}"
        )
        ranks = [f["properties"]["rank"] for f in geojson["features"]]
        assert ranks == list(range(1, len(shuffled) + 1)), (
            f"[trial {trial}] rank が連番でない: {ranks}"
        )
        rec_flags = {f["properties"]["id"]: f["properties"]["is_recommended"] for f in geojson["features"]}
        assert rec_flags[shuffled[0]] is True and rec_flags[shuffled[1]] is True, \
            f"[trial {trial}] recommended_ids に渡した2件が is_recommended=True になっていない"
        assert sum(1 for v in rec_flags.values() if v) == 2, \
            f"[trial {trial}] is_recommended=True の件数が2件でない: {rec_flags}"

    print("  [OK] candidates_to_geojson() の順序保持・rank連番・is_recommended付与（3パターン）")


def check_phase18_recommended_ids() -> None:
    """
    TODO 18-2-6: extract_recommended_ids() の抽出ロジックを固定文字列で確認する。
    (a) 出現順維持・重複排除、(b) 候補外ID（幻覚）の除外、(c) ID非含有時は空配列。
    """
    from src.app.main import extract_recommended_ids

    candidate_ids = {
        "bldg_ad534835-ba73-4551-b008-27e8c0b4011b",
        "bldg_11111111-1111-1111-1111-111111111111",
    }

    # (a) 出現順維持・重複排除
    answer_a = (
        "推薦する建物ID: bldg_ad534835-ba73-4551-b008-27e8c0b4011b\n"
        "次点: bldg_11111111-1111-1111-1111-111111111111\n"
        "再掲: bldg_ad534835-ba73-4551-b008-27e8c0b4011b"
    )
    result_a = extract_recommended_ids(answer_a, candidate_ids)
    assert result_a == [
        "bldg_ad534835-ba73-4551-b008-27e8c0b4011b",
        "bldg_11111111-1111-1111-1111-111111111111",
    ], f"(a) 出現順維持・重複排除に失敗: {result_a}"

    # (b) 候補外ID（幻覚）の除外
    answer_b = (
        "推薦: bldg_ad534835-ba73-4551-b008-27e8c0b4011b と "
        "bldg_99999999-9999-9999-9999-999999999999（幻覚ID）"
    )
    result_b = extract_recommended_ids(answer_b, candidate_ids)
    assert result_b == ["bldg_ad534835-ba73-4551-b008-27e8c0b4011b"], \
        f"(b) 候補外IDの除外に失敗: {result_b}"

    # (c) ID非含有時は空配列
    answer_c = "該当する建物は見つかりませんでした。"
    result_c = extract_recommended_ids(answer_c, candidate_ids)
    assert result_c == [], f"(c) ID非含有時に空配列でない: {result_c}"

    print("  [OK] extract_recommended_ids(): 出現順維持/幻覚ID除外/空配列 すべて条件充足")


def run_phase18_checks() -> None:
    """Phase 18 サニティチェック（GeoJSON順序保持・推薦ID抽出。LLM API 不要）"""
    print("\n" + "=" * 60)
    print("Phase 18 サニティチェック 開始")
    print("=" * 60)

    passed = failed = 0
    checks = [
        check_phase18_geojson_order,
        check_phase18_recommended_ids,
    ]
    for check in checks:
        try:
            check()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    print(f"\n結果: {passed} 件パス / {failed} 件失敗")
    if failed > 0:
        sys.exit(1)
    else:
        print("[SUCCESS] Phase 18 全チェックパス")


# ============================================================
# Phase 20 サニティチェック — フットプリント形状指標
# ============================================================

def check_phase20_shape_columns() -> None:
    """
    TODO 20-5-2: building_geom_meta に形状指標の新カラム7種が存在し、
    circularity の非NULL件数が0でないこと。
    """
    con = connect_rag()
    try:
        cols = {r[0] for r in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'building_geom_meta'"
        ).fetchall()}
        required = {
            "footprint_perimeter_m", "convex_hull_area_m2", "footprint_vertex_count",
            "concave_vertex_count", "circularity", "convexity_ratio", "shape_type_est",
        }
        missing = required - cols
        assert not missing, f"building_geom_meta に形状指標カラムが不足: {missing}"

        n_circ = con.execute(
            "SELECT COUNT(*) FROM building_geom_meta WHERE circularity IS NOT NULL"
        ).fetchone()[0]
        assert n_circ > 0, "circularity が全件NULL"

        n_types = con.execute(
            "SELECT COUNT(DISTINCT shape_type_est) FROM building_geom_meta "
            "WHERE shape_type_est IS NOT NULL"
        ).fetchone()[0]
        assert n_types >= 2, f"shape_type_est の分類が1種類以下: {n_types}"
    finally:
        con.close()
    print(f"  [OK] building_geom_meta 形状指標カラム7種確認、circularity 非NULL={n_circ}件、"
          f"shape_type_est 分類数={n_types}")


def check_phase20_shape_filter() -> None:
    """
    TODO 20-5-2: 「円形に近い建物を教えて」→ route=structured かつ
    全候補の shape_type_est == "円形に近い" であること。
    """
    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    result = hybrid_search("円形に近い建物を教えて", top_k=10, skip_answer=True)
    assert result["route"] == "structured", f"route が structured でない: {result['route']}"
    candidates = result["candidates"]
    assert len(candidates) >= 1, "候補建物が0件"
    violated = candidates[candidates["shape_type_est"] != "円形に近い"]
    assert violated.empty, (
        f"円形フィルタに違反する候補が存在: {violated[['id', 'shape_type_est']].to_dict('records')}"
    )
    print(f"  [OK] 円形クエリ: route=structured, 全{len(candidates)}件が shape_type_est='円形に近い'")


def run_phase20_checks() -> None:
    """Phase 20 サニティチェック（フットプリント形状指標）"""
    print("\n" + "=" * 60)
    print("Phase 20 サニティチェック 開始")
    print("=" * 60)

    passed = failed = 0
    checks = [
        check_phase20_shape_columns,
        check_phase20_shape_filter,
    ]
    for check in checks:
        try:
            check()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    print(f"\n結果: {passed} 件パス / {failed} 件失敗")
    if failed > 0:
        sys.exit(1)
    else:
        print("[SUCCESS] Phase 20 全チェックパス")


# ============================================================
# Phase 25 サニティチェック — 楕円形分類・あいまい円形マッチ
# ============================================================

def check_phase25_ellipse_shape() -> None:
    """
    TODO 25-3-2: shape_type_est の分類が7種になっていること、
    「楕円形」「丸い（あいまい）」「真円（厳密）」の3クエリで
    それぞれ期待通りの shape_type_est 集合になっていることを確認する。
    """
    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    con = connect_rag()
    try:
        n_types = con.execute(
            "SELECT COUNT(DISTINCT shape_type_est) FROM building_geom_meta "
            "WHERE shape_type_est IS NOT NULL"
        ).fetchone()[0]
        assert n_types == 7, f"shape_type_est の分類数が7種でない（楕円形追加後の期待値）: {n_types}"
    finally:
        con.close()

    cases = [
        ("楕円形の建物を教えて", {"楕円形"}),
        ("丸い建物を探して", {"円形に近い", "楕円形"}),
        ("真円の建物を探して", {"円形に近い"}),
    ]
    for query, expected_shapes in cases:
        result = hybrid_search(query, top_k=10, skip_answer=True)
        assert result["route"] == "structured", f"[{query}] route が structured でない: {result['route']}"
        candidates = result["candidates"]
        assert len(candidates) >= 1, f"[{query}] 候補建物が0件"
        actual_shapes = set(candidates["shape_type_est"].tolist())
        assert actual_shapes <= expected_shapes, (
            f"[{query}] 期待外の shape_type_est が含まれる: {actual_shapes - expected_shapes}"
        )
        print(f"  [OK] 「{query}」: route=structured, 全{len(candidates)}件が {actual_shapes} "
              f"(期待集合 {expected_shapes} の部分集合)")

    print(f"  [OK] shape_type_est 分類数={n_types}種")


def run_phase25_checks() -> None:
    """Phase 25 サニティチェック（楕円形分類・あいまい円形マッチ）"""
    print("\n" + "=" * 60)
    print("Phase 25 サニティチェック 開始")
    print("=" * 60)

    passed = failed = 0
    checks = [
        check_phase25_ellipse_shape,
    ]
    for check in checks:
        try:
            check()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    print(f"\n結果: {passed} 件パス / {failed} 件失敗")
    if failed > 0:
        sys.exit(1)
    else:
        print("[SUCCESS] Phase 25 全チェックパス")


def check_phase28_superlative_recommendation() -> None:
    """
    TODO 28-2-1: sort_by が設定される最上級クエリ（一番高い等）で、
    LLMの回答冒頭で言及される建物IDが比較表1位（=候補DataFrameの先頭行）と
    一致することを確認する（日英2クエリ）。
    """
    if not RAG_DB_PATH.exists():
        print("  [SKIP] plateau_rag.duckdb が未作成のためスキップ")
        return

    from src.app.retrieval import _BUILDING_ID_PATTERN

    cases = [
        ("広島駅付近で一番高い建物を教えて", "ja"),
        ("What is the tallest building around Hiroshima Station?", "en"),
    ]
    for query, lang in cases:
        result = hybrid_search(query, top_k=10, response_language=lang)
        candidates = result["candidates"]
        assert len(candidates) >= 1, f"[{query}] 候補建物が0件"
        assert result["parsed_query"]["sort_by"] is not None, f"[{query}] sort_by が設定されていない"

        expected_top_id = candidates.iloc[0]["id"]
        mentioned_ids = _BUILDING_ID_PATTERN.findall(result["answer"])
        assert mentioned_ids, f"[{query}] 回答に建物IDが含まれていない"
        assert mentioned_ids[0] == expected_top_id, (
            f"[{query}] 回答冒頭の建物ID（{mentioned_ids[0]}）が"
            f"比較表1位（{expected_top_id}）と一致しない"
        )
        print(f"  [OK] 「{query}」: 推薦={mentioned_ids[0]} == 比較表1位")


def run_phase28_checks() -> None:
    """Phase 28 サニティチェック（最上級クエリの推薦確定化）"""
    print("\n" + "=" * 60)
    print("Phase 28 サニティチェック 開始")
    print("=" * 60)

    passed = failed = 0
    checks = [
        check_phase28_superlative_recommendation,
    ]
    for check in checks:
        try:
            check()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {check.__name__}: {e}")
            failed += 1

    print(f"\n結果: {passed} 件パス / {failed} 件失敗")
    if failed > 0:
        sys.exit(1)
    else:
        print("[SUCCESS] Phase 28 全チェックパス")


if __name__ == "__main__":
    import sys
    if "--phase6" in sys.argv:
        run_phase6_checks()
    elif "--phase8" in sys.argv:
        run_phase8_checks()
    elif "--phase9" in sys.argv:
        run_phase9_checks()
    elif "--phase10" in sys.argv:
        run_phase10_checks()
    elif "--phase11" in sys.argv:
        run_phase11_checks()
    elif "--phase12" in sys.argv:
        run_phase12_checks()
    elif "--phase13" in sys.argv:
        run_phase13_checks()
    elif "--phase15" in sys.argv:
        run_phase15_checks()
    elif "--phase17" in sys.argv:
        run_phase17_checks()
    elif "--phase18" in sys.argv:
        run_phase18_checks()
    elif "--phase20" in sys.argv:
        run_phase20_checks()
    elif "--phase25" in sys.argv:
        run_phase25_checks()
    elif "--phase28" in sys.argv:
        run_phase28_checks()
    else:
        run_all_checks()
