"""
評価基盤（ゴールドセット）

構造化条件（SQL で機械的に定義できる条件）を持つクエリについて、
building_chunks から正解建物 ID 集合を算出し、output/gold_set.json に保存する。
semantic カテゴリ（純粋な意味的クエリ）は gold_sql=None とし、recall 計測の対象外
（回答の定性確認のみ）とする。

実行:
    pixi run python tests/gold_set.py
"""

import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
RAG_DB_PATH = ROOT / "output" / "plateau_rag.duckdb"
OUT_PATH = ROOT / "output" / "gold_set.json"


def _resolve_station_coords(con: duckdb.DuckDBPyConnection) -> tuple[float, float]:
    """
    G34 用の広島駅座標を geocode() から動的に取得し、
    EPSG:6671 に変換して返す（ハードコード廃止。station.geojson 更新に追従する）。
    """
    from src.app.geocoder import geocode  # 遅延 import（gold_sql に {STATION_X} がある時のみ必要）

    coords = geocode("広島駅")
    if coords is None:
        raise RuntimeError("geocode('広島駅') が解決できませんでした（station.geojson を確認してください）")
    lon, lat = coords
    x, y = con.execute(
        """
        SELECT
            ST_X(ST_Transform(ST_Point(?, ?), 'EPSG:4326', 'EPSG:6671', always_xy := true)),
            ST_Y(ST_Transform(ST_Point(?, ?), 'EPSG:4326', 'EPSG:6671', always_xy := true))
        """,
        [lon, lat, lon, lat],
    ).fetchone()
    return float(x), float(y)


# ============================================================
# ゴールドクエリ定義（20 件: structured 8 / hybrid 8 / semantic 4）
# ============================================================

GOLD_QUERIES: list[dict] = [
    # ---------------- structured (8件) ----------------
    {
        "id": "G01",
        "query": "広島市で最も高い建物は？",
        "category": "structured",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE measured_height > 0
            ORDER BY measured_height DESC
            LIMIT 5
        """,
        "note": "高さ上位5件を正解とする（症状再現クエリ: 高い建物の誤選択）",
    },
    {
        "id": "G02",
        "query": "高潮リスクが低い建物",
        "category": "structured",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE ht_depth_max IS NULL
        """,
        "note": "症状再現クエリ: 高潮リスクありの建物が誤って推薦される問題",
    },
    {
        "id": "G03",
        "query": "駅から300m以内の建物",
        "category": "structured",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE nearest_station_dist_m <= 300
        """,
        "note": "症状再現クエリ: 距離条件が埋め込みでは判別できない問題",
    },
    {
        "id": "G04",
        "query": "洪水リスクが全くない建物",
        "category": "structured",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE rv_depth_max IS NULL
        """,
        "note": "リスクなし判定（NULL 判定）の確認",
    },
    {
        "id": "G05",
        "query": "耐火構造の共同住宅",
        "category": "structured",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE fire_proof = '耐火' AND usage = '共同住宅'
        """,
        "note": "属性フィルタ（fire_proof × usage）の複合条件",
    },
    {
        "id": "G06",
        "query": "浸水深1m以下の高潮リスク（リスクなし含む）の建物",
        "category": "structured",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE ht_depth_max IS NULL OR ht_depth_max <= 1.0
        """,
        "note": "深さ上限フィルタ（NULL は許容側に含める）",
    },
    {
        "id": "G07",
        "query": "最も駅に近い建物は？",
        "category": "structured",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE nearest_station_dist_m IS NOT NULL
            ORDER BY nearest_station_dist_m ASC
            LIMIT 5
        """,
        "note": "汎用ソートキー（距離昇順）の確認",
    },
    {
        "id": "G08",
        "query": "10階建て以上の建物",
        "category": "structured",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE storeys >= 10
        """,
        "note": "階数フィルタの確認",
    },
    # ---------------- hybrid (8件) ----------------
    {
        "id": "G09",
        "query": "駅から近く津波リスクのない宿泊施設",
        "category": "hybrid",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE ts_depth_max IS NULL AND usage = '宿泊施設'
        """,
        "note": "構造化条件（リスク・用途）を満たす集合が正解の上限"
               "（「駅から近く」は残差として順位付けのみに影響、フィルタ対象外）。"
               "宿泊施設22件は全件 ht_depth_max 有意値のため ht ではなく ts で定義",
    },
    {
        "id": "G10",
        "query": "避難所まで300m以内で日当たりのよい建物",
        "category": "hybrid",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE nearest_shelter_dist_m <= 300
        """,
        "note": "「日当たりのよい」は semantic_residual。距離条件のみ正解集合の上限とする",
    },
    {
        "id": "G11",
        "query": "浸水5m以下で耐火構造の建物",
        "category": "hybrid",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE (ht_depth_max IS NULL OR ht_depth_max <= 5.0) AND fire_proof = '耐火'
        """,
        "note": "リスク上限＋構造フィルタの複合。ht_depth_max の実測分布は中央値約5.06m"
               "（1m/2m/3mでは fire_proof='耐火' との積集合が0件だったため5.0mに調整）",
    },
    {
        "id": "G12",
        "query": "公園に隣接していて眺めのよい高い建物",
        "category": "hybrid",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE nearest_park_dist_m <= 100 AND measured_height >= 30.0
        """,
        "note": "距離＋高さの複合フィルタ（「眺めのよい」は semantic_residual）",
    },
    {
        "id": "G13",
        "query": "洪水避難のための高い建物を広島駅付近で",
        "category": "hybrid",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE measured_height >= 10.0
        """,
        "note": "location_name によるジオコーディング絞り込みは候補削減のみに使うため、"
               "正解集合は高さ条件のみで定義（空間フィルタの効果は recall では評価しない）",
    },
    {
        "id": "G14",
        "query": "緊急輸送道路から200m以内で鉄筋コンクリート造の建物",
        "category": "hybrid",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE nearest_emroute_dist_m <= 200 AND structure_type = '鉄筋コンクリート造'
        """,
        "note": "距離＋構造の複合フィルタ",
    },
    {
        "id": "G15",
        "query": "津波リスクがなく静かな住宅",
        "category": "hybrid",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE ts_depth_max IS NULL AND usage = '住宅'
        """,
        "note": "「静かな」は semantic_residual。リスク・用途のみ正解集合の上限とする",
    },
    {
        "id": "G16",
        "query": "ランドマークまで100m以内で防災拠点に向いた建物",
        "category": "hybrid",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE nearest_landmark_dist_m <= 100
        """,
        "note": "「防災拠点に向いた」は semantic_residual。距離条件のみ正解集合の上限とする。"
               "500m では平均距離134mのため全件ヒットし無意味な検証になるため100mに調整",
    },
    # ---------------- semantic (4件・recall計測対象外) ----------------
    {
        "id": "G17",
        "query": "日当たりのよい建物",
        "category": "semantic",
        "gold_sql": None,
        "note": "壁面方位（南向き比率）に基づく意味的な検索。正解定義不可のため定性確認のみ",
    },
    {
        "id": "G18",
        "query": "静かな住宅街にある建物",
        "category": "semantic",
        "gold_sql": None,
        "note": "定性確認のみ",
    },
    {
        "id": "G19",
        "query": "防災拠点として活用できそうな建物",
        "category": "semantic",
        "gold_sql": None,
        "note": "定性確認のみ",
    },
    {
        "id": "G20",
        "query": "landmarkとして目立つ特徴的な形の建物",
        "category": "semantic",
        "gold_sql": None,
        "note": "定性確認のみ",
    },
    # ---------------- geometric (10件・幾何前計算カラムの効果測定) ----------------
    {
        "id": "G21",
        "query": "南向きの壁面が最も大きい建物は？",
        "category": "geometric",
        "gold_sql": """
            SELECT id FROM building_geom_meta
            WHERE wall_area_total_m2 > 0
            ORDER BY wall_ratio_s DESC
            LIMIT 5
        """,
        "note": "南向き壁面比率トップ5。wall_ratio_s の配線確認",
    },
    {
        "id": "G22",
        "query": "西日の当たらない建物",
        "category": "geometric",
        "gold_sql": """
            SELECT id FROM building_geom_meta
            WHERE wall_area_total_m2 > 0 AND wall_ratio_w <= 0.1
        """,
        "note": "西向き壁面比率10%以下（ORIENT_AVOID_MAX と同一閾値をStep15-2で使用予定）",
    },
    {
        "id": "G23",
        "query": "日当たりのよい建物",
        "category": "geometric",
        "gold_sql": """
            SELECT g.id FROM building_geom_meta g
            JOIN building_context_meta c ON g.id = c.id
            WHERE c.winter_sunlit AND g.wall_ratio_s >= 0.3
        """,
        "note": "【擬似ゴールド】winter_sunlit(冬至南中仰角30°未満)かつ南壁面比率30%以上。"
               "絶対的な正解ではなく本プロジェクトの日照近似モデルによる定義",
    },
    {
        "id": "G24",
        "query": "屋上が広い建物トップ5",
        "category": "geometric",
        "gold_sql": """
            SELECT id FROM building_geom_meta
            WHERE roof_area_m2 IS NOT NULL
            ORDER BY roof_area_m2 DESC
            LIMIT 5
        """,
        "note": "屋根面積トップ5。太陽光パネル設置・屋上緑化の適地探索を想定",
    },
    {
        "id": "G25",
        "query": "屋根が平らな建物",
        "category": "geometric",
        "gold_sql": """
            SELECT id FROM building_geom_meta
            WHERE roof_type_est = '陸屋根'
        """,
        "note": "flat_roof_ratio>=0.7（実データ分布から確定済みの閾値）による陸屋根判定",
    },
    {
        "id": "G26",
        "query": "高台にある建物",
        "category": "geometric",
        "gold_sql": """
            SELECT id FROM building_geom_meta
            WHERE ground_elev_m >= (SELECT quantile_cont(ground_elev_m, 0.9) FROM building_geom_meta)
        """,
        "note": "地面標高の上位10%（実データで確認: 閾値約3.18m、該当296件）",
    },
    {
        "id": "G27",
        "query": "静かな環境の共同住宅",
        "category": "geometric",
        "gold_sql": """
            SELECT b.id FROM building_chunks b
            JOIN building_context_meta c ON b.id = c.id
            WHERE c.nearest_major_road_dist_m >= 100 AND b.usage = '共同住宅'
        """,
        "note": "幹線道路(tran:Road.function IN ('2','3'))から100m以上、かつ共同住宅",
    },
    {
        "id": "G28",
        "query": "浸水しても上層階に避難できる建物",
        "category": "geometric",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE storeys >= 3 AND measured_height > 0
              AND measured_height - GREATEST(COALESCE(ht_depth_max,0),
                  COALESCE(rv_depth_max,0), COALESCE(ts_depth_max,0)) >= 6.0
        """,
        "note": "垂直避難。Step15-2 の vertical_evacuation フィルタと同一の定義式・"
               "同一定数(VERTICAL_EVAC_MARGIN_M=6.0)を使うこと（評価と実装の定義ズレ防止）",
    },
    {
        "id": "G29",
        "query": "はしご車が届く高さで緊急輸送道路から100m以内の建物",
        "category": "geometric",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE measured_height BETWEEN 0.1 AND 31.0
              AND nearest_emroute_dist_m <= 100
        """,
        "note": "はしご車の届く高さ(一般的な目安31m)以下かつ緊急輸送道路から100m以内。"
               "クエリ文言は当初「緊急輸送道路に近い」（曖昧表現）だったが、"
               "distance_filtersのデフォルト距離(500m)が適用されgold_sqlの100mと"
               "ズレてhit1=0になったため、明示的な数値「100m以内」を含む文言に変更",
    },
    {
        "id": "G30",
        "query": "木造密集地にある耐火建築物",
        "category": "geometric",
        "gold_sql": """
            SELECT b.id FROM building_chunks b
            JOIN building_context_meta c ON b.id = c.id
            WHERE c.wooden_density_ratio >= 0.05 AND b.fire_proof = '耐火'
        """,
        "note": "閾値0.05（実データ分布から確定。当初想定0.5は木造建物が全体の2.5%しか"
               "存在せず wooden_density_ratio 最大値0.259のため常に0件になり非現実的だった）",
    },
    # ---------------- robustness (6件・除外/範囲/0件正解/複合ハイブリッド) ----------------
    {
        "id": "G31",
        "query": "木造以外の建物",
        "category": "robustness",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE structure_type IS NOT NULL AND structure_type <> '木造・土蔵造'
        """,
        "note": "除外条件（usage_exclude/structure_exclude）",
    },
    {
        "id": "G32",
        "query": "高さ20m以上40m以下の建物",
        "category": "robustness",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE measured_height BETWEEN 20.0 AND 40.0
        """,
        "note": "範囲条件（height_max。height_minは既存）",
    },
    {
        "id": "G33",
        "query": "高潮リスクがなく駅から100m以内の宿泊施設",
        "category": "robustness",
        "gold_sql": """
            SELECT id FROM building_chunks
            WHERE ht_depth_max IS NULL AND nearest_station_dist_m <= 100 AND usage = '宿泊施設'
        """,
        "note": "【正解0件を事前確認の上で採用】候補が0件で、かつ回答が該当なしを明言すれば"
               "合格とする定性基準（evaluate() 側で候補0件×gold0件を正解1.0として扱う）",
    },
    {
        "id": "G34",
        "query": "広島駅から500m以内で日当たりのよい建物",
        "category": "robustness",
        "gold_sql": """
            SELECT g.id FROM building_geom_meta g
            JOIN building_context_meta c ON g.id = c.id
            JOIN building_chunks b ON g.id = b.id
            WHERE c.winter_sunlit AND g.wall_ratio_s >= 0.3
              AND ST_DWithin(b.geometry, ST_Point({STATION_X}, {STATION_Y}), 500)
        """,
        "note": "空間×幾何のハイブリッド（提案書の看板クエリ）。G23条件+広島駅500m圏内。"
               "座標は build_gold() 実行時に geocode('広島駅') から動的計算する"
               "（station.geojson 更新への追従のためハードコードを廃止）",
    },
    {
        "id": "G35",
        "query": "学校まで300m以内の共同住宅",
        "category": "robustness",
        "gold_sql": """
            SELECT b.id FROM building_chunks b
            JOIN building_context_meta c ON b.id = c.id
            WHERE c.nearest_school_dist_m <= 300 AND b.usage = '共同住宅'
        """,
        "note": "landmark.geojsonの種類='学校'から計算したnearest_school_dist_m",
    },
    {
        "id": "G36",
        "query": "病院に近く洪水リスクのない建物",
        "category": "robustness",
        "gold_sql": """
            SELECT b.id FROM building_chunks b
            JOIN building_context_meta c ON b.id = c.id
            WHERE c.nearest_hospital_dist_m <= 500 AND b.rv_depth_max IS NULL
        """,
        "note": "landmark.geojsonの種類='病院'から計算したnearest_hospital_dist_m",
    },
    # ---------------- フットプリント形状（3件） ----------------
    {
        "id": "G37",
        "query": "円形に近い建物を教えて",
        "category": "geometric",
        "gold_sql": """
            SELECT id FROM building_geom_meta
            WHERE shape_type_est = '円形に近い'
        """,
        "note": "真円度(circularity>=0.85)による円形判定。実データ分布から確定した閾値",
    },
    {
        "id": "G38",
        "query": "L字型の建物はある？",
        "category": "geometric",
        "gold_sql": """
            SELECT id FROM building_geom_meta
            WHERE shape_type_est = 'L字型'
        """,
        "note": "凹角数1（concave_vertex_count=1）による L字型判定",
    },
    {
        "id": "G39",
        "query": "星形や複雑な形状の建物を探して",
        "category": "geometric",
        "gold_sql": """
            SELECT id FROM building_geom_meta
            WHERE shape_type_est = '星形・複雑形状'
        """,
        "note": "凹角数3以上かつ凸性比0.6未満（または凹角数5以上）による複雑形状判定",
    },
    # ---------------- 楕円形・あいまい円形マッチ（2件） ----------------
    {
        "id": "G40",
        "query": "楕円形の建物を教えて",
        "category": "geometric",
        "gold_sql": """
            SELECT id FROM building_geom_meta
            WHERE shape_type_est = '楕円形'
        """,
        "note": "外接矩形充填率(box_fill_ratio)0.70〜0.85による楕円形判定",
    },
    {
        "id": "G41",
        "query": "丸い建物を探して",
        "category": "geometric",
        "gold_sql": """
            SELECT id FROM building_geom_meta
            WHERE shape_type_est IN ('円形に近い', '楕円形')
        """,
        "note": "あいまい表現「丸い」は円形・楕円形の両方にマッチする",
    },
]


def build_gold(out_path: Path | str = OUT_PATH) -> list[dict]:
    """
    TODO 10-1-2: 各クエリの gold_sql を実行し、正解建物 ID 集合を JSON 保存する。
    gold_sql=None（semantic カテゴリ）は gold_ids=[] として保存する（recall 計測対象外）。
    """
    out_path = Path(out_path)
    if not RAG_DB_PATH.exists():
        raise FileNotFoundError(
            f"plateau_rag.duckdb が見つかりません: {RAG_DB_PATH}（`pixi run enrich` 未実行の可能性）"
        )

    con = duckdb.connect(str(RAG_DB_PATH), read_only=True)
    con.execute("INSTALL spatial; LOAD spatial;")
    results = []
    station_xy: tuple[float, float] | None = None  # 必要時のみ解決するキャッシュ
    try:
        for q in GOLD_QUERIES:
            if q["gold_sql"] is None:
                gold_ids: list[str] = []
            else:
                sql = q["gold_sql"]
                # {STATION_X}/{STATION_Y} プレースホルダを動的座標で置換
                if "{STATION_X}" in sql:
                    if station_xy is None:
                        station_xy = _resolve_station_coords(con)
                    sql = sql.replace("{STATION_X}", f"{station_xy[0]:.3f}") \
                             .replace("{STATION_Y}", f"{station_xy[1]:.3f}")
                rows = con.execute(sql).fetchall()
                gold_ids = [r[0] for r in rows]
            results.append({
                "id": q["id"],
                "query": q["query"],
                "category": q["category"],
                "gold_ids": gold_ids,
                "note": q["note"],
            })
            print(f"  {q['id']} [{q['category']}] 「{q['query']}」→ 正解 {len(gold_ids)} 件")
    finally:
        con.close()

    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n保存完了: {out_path}（{len(results)} 件）")
    return results


if __name__ == "__main__":
    build_gold()
