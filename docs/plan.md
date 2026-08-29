# 実装計画 — PLATEAU Semantic 3D-Geospatial RAG

承認日: 2026-03-22

---

## Phase 1: データ構造精査

### Step 1-1: テーブル一覧取得とスキーマ確認
  - TODO 1-1-1: DuckDB で hiroshima_sample.gpkg をロードし、
                st_layers() でテーブル名・地物数・CRS を取得
  - TODO 1-1-2: bldg:Building の全カラム名・型・件数を確認
  - TODO 1-1-3: tran:Road の全カラム名・型・件数を確認
  - TODO 1-1-4: uro:HighTideRiskAttribute / RiverFloodingRiskAttribute 等
                リスク属性テーブルの存在とカラム構成を確認
  - TODO 1-1-5: TrafficArea / AuxiliaryTrafficArea テーブルの存在確認

### Step 1-2: JOIN キー検証
  - TODO 1-2-1: uro:HighTideRiskAttribute.parentId → bldg:Building.id の
                LEFT JOIN 結果件数を確認（0件でないこと）
  - TODO 1-2-2: tran:TrafficArea.parentId → tran:Road.id の
                LEFT JOIN 結果件数を確認
  - TODO 1-2-3: depth / rank / description カラムの値サンプル取得
  - TODO 1-2-4: tran:TrafficArea.function の値種類を確認
                （歩道・車道が存在するかチェック）

### Step 1-3: サニティチェック関数実装
  - TODO 1-3-1: tests/sanity_checks.py に Step 1-1〜1-2 の
                アサーション関数を実装
  - TODO 1-3-2: pixi run で実行・全項目パスを確認
  - TODO 1-3-3: work_log.md に結果記録、git commit

---

## Phase 2: 空間演算実装（完了）

### Step 2-1〜2-5: 座標変換・建物・道路検索・統合関数・サニティチェック
  - TODO 2-1-1: wgs84_to_epsg6671(con, lon, lat) を ST_Transform(always_xy:=true) で実装
  - TODO 2-2-1: search_buildings_within(con, lon, lat, radius_m) を ST_DWithin + ST_Distance で実装
  - TODO 2-3-1: search_buildings_with_risk(con, lon, lat, radius_m) を CTE 集約 + LEFT JOIN で実装
  - TODO 2-4-1: search_roads_near(con, x, y, radius_m) を ST_DWithin で実装
  - TODO 2-5-1: build_spatial_context(con, lon, lat, radius_m) で Phase 3 引き継ぎ辞書を実装
  - TODO 2-5-2: tests/sanity_checks.py に Phase 2 用アサーション 3 関数を追加

---

## Phase 3: セマンティック・チャンク化（実装中 / 埋め込み生成は Free Tier 制限により日次実行）

### Step 3-1: データ読み込み・空間結合の実装
  - TODO 3-1-1: connect_rag() を実装（plateau_rag.duckdb への永続化接続、spatial + vss ロード）
  - TODO 3-1-2: building_chunks テーブルを CREATE TABLE IF NOT EXISTS で作成（拡張版スキーマ）
  - TODO 3-1-3: GPKG 系（建物・リスク・道路・landuse・urf）の一括 JOIN を CTE で実装
               load_buildings_gpkg(gpkg_con) → pd.DataFrame
  - TODO 3-1-4: GeoJSON 系（避難施設・駅・緊急輸送道路・公園・ランドマーク）の
               最近傍距離を建物ごとに付与（CROSS JOIN + ARG_MIN、WGS84→EPSG:6671変換）

### Step 3-2: 属性カルテ（テキスト化）関数の実装
  - TODO 3-2-1: build_text_card(row: dict) → str を実装
               セクション構成: 建物基本情報 / 災害リスク / 構造 / 周辺環境
  - TODO 3-2-2: NULL・コード値の人間可読化ルール定義（NULL → "データなし"等）

### Step 3-3: Gemini 埋め込み生成
  - TODO 3-3-1: google-genai クライアント初期化（.env の GEMINI_API_KEY を使用）
  - TODO 3-3-2: batch_embed(texts, batch_size=100, checkpoint_path) → list[list[float]] を実装
               （model="gemini-embedding-001"、task_type="RETRIEVAL_DOCUMENT"、
               レート制限対応・日次チェックポイント機能付き）
  - TODO 3-3-3: 全 2,958 件を変換し埋め込み次元数を確認・スキーマに反映
               ※ Free Tier 制限（1000 req/day）のため、数日に分けて実行が必要

### Step 3-4: DuckDB への保存と HNSW インデックス作成
  - TODO 3-4-1: building_chunks テーブルへ pyarrow.Table で一括 INSERT
  - TODO 3-4-2: HNSW インデックスを CREATE INDEX で作成（array_cosine_similarity 用）

### Step 3-5: サニティチェック・コミット
  - TODO 3-5-1: tests/sanity_checks.py に Phase 3 用アサーション 3 関数を追加 ✅
  - TODO 3-5-2: pixi run で全チェック通過確認・work_log.md 更新・git commit

---

## Phase 4: ハイブリッド検索構築

### Step 4-1: ベクトル検索エンジン実装
  - TODO 4-1-1: connect_rag() を再利用して RAG DB に接続
  - TODO 4-1-2: embed_query(text) → list[float] を実装
               （gemini-embedding-001、task_type="RETRIEVAL_QUERY"）
  - TODO 4-1-3: vector_search(rag_con, query_vec, lon, lat, radius_m, top_k) を実装
               ・空間フィルタあり: ST_DWithin 後 array_cosine_similarity で ORDER BY
               ・空間フィルタなし: 全件 HNSW 検索

### Step 4-2: LLM 回答生成
  - TODO 4-2-1: build_prompt(query, candidates) → str を実装
               （text_card を [1],[2],... 形式で列挙）
  - TODO 4-2-2: generate_answer(query, candidates, model_provider="gemini") → str を実装
               ・"gemini" → Gemini 2.5 Flash（デフォルト）
               ・"claude" → Claude Sonnet 4.6（将来切り替え用）

### Step 4-3: 統合 API 関数
  - TODO 4-3-1: hybrid_search(query, lon, lat, radius_m, top_k, model_provider) → dict を実装
  - TODO 4-3-2: main() でデモクエリ 2 件（空間フィルタなし・あり）を実行

### Step 4-4: サニティチェック・コミット
  - TODO 4-4-1: tests/sanity_checks.py に Phase 4 用アサーション 2 関数を追加
               ・assert_vector_search_returns_results
               ・assert_answer_contains_building_id
  - TODO 4-4-2: pixi run で全チェック通過確認・work_log.md 更新・git commit

---

## Phase 10: ハイブリッド検索高度化（SQL × ベクトル ルーティング）

承認日: （未承認 — 実装開始前にユーザー承認を得ること）

> **背景（2026-07-13 調査結果）:**
> - 保存済みカルテ埋め込みはコサイン類似度 0.83〜0.96 に密集しており、
>   ベクトル検索単体ではランキングの識別力がほぼない（定型文が支配的なため）。
> - 「高い」「リスクが低い」「500m以内」等の数値・順序・否定・距離条件は
>   埋め込みが原理的に扱えず、誤選択（条件違反の建物を推薦）の主因になっている。
> - 一方、距離条件の大半は Phase 3 で事前計算済みのカラム
>   （nearest_station_dist_m 等）への単純な WHERE 比較で確定的に処理できる。
>
> **方針:** クエリを「構造化条件（SQL で確定判定）」と「意味的残差（ベクトル検索）」に
> 分離し、3分岐ルーティング（①純構造化 → SQL のみ / ②純意味 → ベクトルのみ /
> ③混合 → SQL フィルタ後にベクトルランキング）で両者を使い分ける。
> 再埋め込みは不要（既存 plateau_rag.duckdb のまま実装可能）。

> **共通仕様（Phase 10 全 Step で参照）:**
>
> フィルタ対象カラム対応表（building_chunks テーブル / すべて実在確認済み）:
>
> | クエリ内の概念 | カラム | 備考 |
> |---|---|---|
> | 高さ | `measured_height` | **-9999.0 が無効値**。高さ条件・ソート使用時は必ず `measured_height > 0` を併置 |
> | 階数 | `storeys` | 「N階以上」→ `measured_height >= N*3.0` に換算してもよいが、原則 `storeys >= N` を使う |
> | 高潮リスク | `ht_depth_max` | **NULL = リスクなし（浸水想定区域外）** |
> | 洪水リスク | `rv_depth_max` | 同上 |
> | 津波リスク | `ts_depth_max` | 同上 |
> | 用途 | `usage` | 日本語ラベル格納済み（query_parser.py の _USAGE_VALUES 参照） |
> | 構造 | `structure_type` | 日本語ラベル格納済み（_STRUCTURE_VALUES 参照） |
> | 耐火 | `fire_proof` | 日本語ラベル格納済み。実値は Step 10-2 で SELECT DISTINCT により列挙 |
> | 駅までの距離 | `nearest_station_dist_m` | 事前計算済み（m）。空間演算不要 |
> | 避難所までの距離 | `nearest_shelter_dist_m` | 同上 |
> | 公園までの距離 | `nearest_park_dist_m` | 同上 |
> | 緊急輸送道路までの距離 | `nearest_emroute_dist_m` | 同上 |
> | ランドマークまでの距離 | `nearest_landmark_dist_m` | 同上 |
> | 任意地点の周辺 | `geometry` + `ST_DWithin` | ジオコーディング起点の場合のみ使用（従来どおり） |

### Step 10-1: 評価基盤（ゴールドセット）の構築

  - TODO 10-1-1: `tests/gold_set.py` を新規作成し、評価クエリ 20 件を
                モジュール定数 `GOLD_QUERIES: list[dict]` として定義する。
                各要素のスキーマ:
                ```python
                {
                  "id": "G01",                       # 通し番号
                  "query": "広島市で最も高い建物は？",   # 自然言語クエリ
                  "category": "structured",           # structured / semantic / hybrid
                  "gold_sql": "SELECT id FROM building_chunks WHERE measured_height > 0 ORDER BY measured_height DESC LIMIT 5",
                  "note": "高さ上位5件を正解とする",
                }
                ```
                内訳: structured 8 件・hybrid 8 件・semantic 4 件。
                以下の症状再現クエリを必ず含める:
                ・「広島市で最も高い建物は？」（structured / 高さ降順 5 件）
                ・「高潮リスクが低い建物」（structured / `ht_depth_max IS NULL` 全件）
                ・「駅から300m以内の建物」（structured / `nearest_station_dist_m <= 300` 全件）
                ・「駅から近く高潮リスクのない宿泊施設」（hybrid）
                ※ semantic カテゴリ（例:「日当たりのよい建物」）は gold_sql を
                  定義できないため `"gold_sql": None` とし、recall 計測対象外
                  （回答の定性確認のみ）とする。
  - TODO 10-1-2: `tests/gold_set.py` に `build_gold(out_path="output/gold_set.json")` を実装する。
                処理: `duckdb.connect('output/plateau_rag.duckdb', read_only=True)` →
                各 gold_sql を実行し `{"id": ..., "query": ..., "category": ...,
                "gold_ids": [...]}` のリストを JSON 保存。
                `__main__` で実行可能にする（`pixi run python tests/gold_set.py`）。
  - TODO 10-1-3: `tests/eval_retrieval.py` を新規作成する。
                ・関数 `evaluate(top_k=10, use_query_parser=True) -> pd.DataFrame`:
                  gold_set.json を読み、各クエリで
                  `hybrid_search(query, top_k=top_k)` を実行し、
                  `candidates["id"]` と gold_ids から
                  recall@k・precision@k・hit@1 を算出。
                ・出力: クエリ別スコア表（id / category / recall / precision / hit1）
                  と category 別マクロ平均を print し、
                  `output/eval_result_{YYYYMMDD_HHMM}.csv` に保存。
                ・LLM 回答生成はスキップする（検索段のみ評価。
                  `hybrid_search` に `skip_answer: bool = False` 引数を追加し、
                  True 時は `answer=""` で返す改修を本 TODO に含める）。
  - TODO 10-1-4: 現行実装（改修前）のベースラインを
                `pixi run python tests/eval_retrieval.py` で計測し、
                結果 CSV のパスと category 別平均値を work_log.md に記録する。
                ※ Gemini API を 20 回程度呼ぶため Free Tier クォータに注意。

### Step 10-2: クエリ解析スキーマの拡張（query_parser.py）

  - TODO 10-2-1: フィルタ条件用の dataclass を query_parser.py に追加する:
                ```python
                @dataclass
                class RiskFilter:
                    hazard: str        # "ht" | "rv" | "ts"
                    mode: str          # "none"（リスクなし） | "max_depth"（深さ上限）
                    max_depth_m: float | None = None   # mode="max_depth" 時のみ

                @dataclass
                class DistanceFilter:
                    target: str        # "station" | "shelter" | "park" | "emroute" | "landmark"
                    max_dist_m: float

                @dataclass
                class SortSpec:
                    key: str           # "measured_height" | "storeys" |
                                       # "nearest_station_dist_m" | "nearest_shelter_dist_m" |
                                       # "nearest_park_dist_m" | "nearest_emroute_dist_m" |
                                       # "nearest_landmark_dist_m" |
                                       # "ht_depth_max" | "rv_depth_max" | "ts_depth_max"
                    order: str         # "asc" | "desc"
                ```
  - TODO 10-2-2: ParsedQuery に以下のフィールドを追加する
                （既存フィールドは後方互換のため削除しない）:
                ```python
                risk_filters: list[RiskFilter] = field(default_factory=list)
                distance_filters: list[DistanceFilter] = field(default_factory=list)
                fire_proof: str | None = None
                sort_by: SortSpec | None = None      # 設定時は sort_by_height より優先
                semantic_residual: str = ""          # 構造化しきれなかった意味条件。なければ空文字
                ```
                ※ 既存の `sort_by_height=True` は `sort_by=SortSpec("measured_height","desc")`
                  へ parse_query() 内で正規化する（呼び出し側は sort_by のみ参照）。
  - TODO 10-2-3: fire_proof の実値を列挙する。
                `SELECT DISTINCT fire_proof FROM building_chunks WHERE fire_proof IS NOT NULL`
                を実行し、結果を `_FIRE_PROOF_VALUES` 定数として
                _USAGE_VALUES と同形式で定義・プロンプトに埋め込む。
  - TODO 10-2-4: _SYSTEM_PROMPT と response_schema を拡張する。プロンプトに明記する規則:
                ・「リスクが低い/ない/安全」→ RiskFilter(mode="none")、
                  「浸水 Nm 以下なら可」→ mode="max_depth", max_depth_m=N
                ・「徒歩 N 分」→ max_dist_m = N × 80.0（不動産表示規約の換算）
                ・「近い」等の曖昧距離 → 施設種別が明確なら max_dist_m=500.0 をデフォルト適用
                ・「最も高い/一番近い」等の最上級 → sort_by を設定（フィルタは設定しない）
                ・上記および既存フィールドで表現しきれない条件
                  （例:「日当たりのよい」「静かな」「防災拠点に向いた」）のみを
                  semantic_residual に原文のまま残す。
                  **全条件が構造化できた場合は semantic_residual="" とする**
                ・response_schema には risk_filters / distance_filters を
                  ネスト object 配列として定義し、全フィールドを required に含める
  - TODO 10-2-5: `__main__` の test_cases に以下 5 件を追加し、期待値をコメントで併記する:
                「高潮リスクがない建物」「駅から徒歩5分以内の共同住宅」
                「最も高い建物は？」「避難所まで300m以内で日当たりのよい建物」
                「浸水1m以下で耐火構造の建物」

### Step 10-3: ルーター＋SQL ビルダーの実装（src/phase10_router.py 新規作成）

  - TODO 10-3-1: `src/phase10_router.py` を新規作成し、`classify_route(pq: ParsedQuery) -> str` を実装する。
                判定ロジック（この順で評価）:
                ```
                has_structured = bool(pq.risk_filters or pq.distance_filters or
                                      pq.fire_proof or pq.height_min or
                                      pq.usage_include or pq.structure_type or
                                      pq.sort_by or pq.location_name)
                has_semantic   = bool(pq.semantic_residual.strip())
                ①  has_structured and not has_semantic → "structured"
                ②  has_semantic  and not has_structured → "semantic"
                ③  両方あり → "hybrid"
                ④  両方なし → "semantic"（元クエリ全文でベクトル検索: フォールバック）
                ```
  - TODO 10-3-2: 同ファイルに `build_filter_clauses(pq: ParsedQuery, alias: str = "") ->
                tuple[list[str], list]` を実装する（WHERE 句断片リストとバインド値リストを返す）。
                変換規則（プレースホルダ `?` 必須・文字列連結による値埋め込み禁止）:
                ```
                RiskFilter(hazard="ht", mode="none")
                  → "{alias}ht_depth_max IS NULL"
                RiskFilter(hazard="ht", mode="max_depth", max_depth_m=1.0)
                  → "({alias}ht_depth_max IS NULL OR {alias}ht_depth_max <= ?)"  / params: [1.0]
                DistanceFilter(target="station", max_dist_m=400)
                  → "{alias}nearest_station_dist_m <= ?"                          / params: [400.0]
                fire_proof="耐火"     → "{alias}fire_proof = ?"
                height_min=10.0      → "{alias}measured_height > 0" と
                                       "{alias}measured_height >= ?" の 2 句
                usage_include        → "{alias}usage IN (?, ...)"（既存ロジックを移設）
                structure_type       → "{alias}structure_type = ?"（既存ロジックを移設）
                ```
                hazard→カラムの対応は `{"ht": "ht_depth_max", "rv": "rv_depth_max",
                "ts": "ts_depth_max"}`、target→カラムの対応は
                `{"station": "nearest_station_dist_m", "shelter": "nearest_shelter_dist_m",
                "park": "nearest_park_dist_m", "emroute": "nearest_emroute_dist_m",
                "landmark": "nearest_landmark_dist_m"}` の dict 定数として定義する。
  - TODO 10-3-3: 同ファイルに `build_order_clause(pq, route, alias="") -> str` を実装する。
                優先順位:
                ```
                ① pq.sort_by あり → "ORDER BY {alias}{key} {order} NULLS LAST"
                   （key が measured_height の場合は WHERE に measured_height > 0 を追加、
                    key が *_depth_max で order=asc の場合は NULL＝リスクなしを先頭に
                    する必要があるため "NULLS FIRST" とする）
                ② sort_by なし & route が hybrid/semantic → "ORDER BY score DESC"
                ③ sort_by なし & route が structured → "ORDER BY {alias}id"（決定的な順序の保証のみ）
                ```
  - TODO 10-3-4: phase4_retrieval.py の `vector_search()` を改修する。
                シグネチャを `vector_search(rag_con, pq: ParsedQuery, route: str,
                query_vec: list[float] | None, lon, lat, radius_m, top_k) -> pd.DataFrame`
                に変更（Phase 8 の個別フィルタ引数は削除し、pq に集約。
                既存呼び出し元は hybrid_search のみなので同時に修正）。
                経路別動作:
                ・structured: `query_vec=None`。SELECT から
                  array_cosine_similarity を除外し `NULL AS score` とする。
                  WHERE = build_filter_clauses ＋（lon/lat 指定時のみ）ST_DWithin
                ・semantic: WHERE は ST_DWithin（指定時）のみ。ORDER BY score DESC
                ・hybrid: WHERE = build_filter_clauses ＋ ST_DWithin（指定時）、
                  ORDER BY は build_order_clause に従う
                （フィルタ後は HNSW が効かず総当たりになるが全 2,958 件のため問題なし）
  - TODO 10-3-5: `embed_query()` の呼び出しを経路別に変更する（hybrid_search 内）:
                ・structured → 呼ばない（API 節約・レイテンシ削減）
                ・hybrid → `embed_query(pq.semantic_residual)`
                ・semantic → `embed_query(pq.semantic_residual or query)`

### Step 10-4: 候補検証パス・LLM プロンプト改善（phase4_retrieval.py）

  - TODO 10-4-1: `verify_candidates(candidates: pd.DataFrame, pq: ParsedQuery) ->
                tuple[pd.DataFrame, list[str]]` を phase10_router.py に実装する。
                build_filter_clauses と同じ条件を pandas 側で再評価し、
                違反行を除外した DataFrame と、除外理由文字列のリスト
                （例: `"bldg_xxx: nearest_station_dist_m=812 > 500"`）を返す。
                ※ SQL フィルタ通過後は原則違反ゼロのはずだが、
                  ジオコーディング座標由来の候補や後方互換経路
                  （use_query_parser=False）の防御として実装する。
                  除外件数が 1 以上なら print でログ出力。
  - TODO 10-4-2: `build_prompt(query, candidates)` を全面改修する:
                ・類似度スコアの数値表示と「類似度スコア順」の文言を削除
                ・冒頭に Markdown 比較表を出力する。列:
                  `No. | 建物ID | 用途 | 高さ(m) | 階数 | 高潮浸水(m) | 洪水浸水(m) |
                   津波浸水(m) | 構造 | 耐火 | 駅まで(m) | 避難所まで(m)`
                  （リスク値 NULL は「なし」、-9999.0 の高さは「不明」と表示）
                ・text_card 全文の添付は上位 10 件までに制限し、
                  11 件目以降は比較表の行のみとする
                ・回答形式指示に「比較表の数値に基づき条件充足を確認してから
                  推薦すること」「表にない情報を創作しないこと」を追記
  - TODO 10-4-3: `validate_answer(answer: str, candidates: pd.DataFrame) -> str` を実装する。
                処理: candidates["id"] の各値について answer 内での出現を確認し、
                answer 中に現れる建物 ID 形式文字列のうち candidates に存在しない
                ものがあれば、回答末尾に
                「※ 注記: 回答中の建物ID {…} は検索候補に含まれていません」を追記して返す。
                （ID 抽出は candidates["id"] の実書式を確認して正規表現を決定する。
                generate_answer() の直後に hybrid_search() 内で呼び出す）

### Step 10-5: 統合・効果測定・サニティチェック

  - TODO 10-5-1: `hybrid_search()` に Step 10-2〜10-4 を統合する。処理順:
                ```
                parse_query → clarification 判定（既存のまま）
                → geocode（既存のまま）
                → route = classify_route(pq)
                → query_vec = 経路別 embed（TODO 10-3-5）
                → candidates = vector_search(...)
                → candidates, removed = verify_candidates(candidates, pq)
                → answer = generate_answer(...) → validate_answer(...)
                ```
                戻り値 dict に `"route": route` を追加する。
                `use_query_parser=False` 時は route="semantic" 固定で従来動作を維持する。
  - TODO 10-5-2: phase6_app.py を更新する:
                ・SearchResponse に `route: str | None = None` を追加
                ・search() で `route=result.get("route")` を返却
                （SearchRequest・フロントエンドは変更不要。
                route はデバッグ用にレスポンスへ載せるのみ）
  - TODO 10-5-3: `pixi run python tests/eval_retrieval.py` を再実行し、
                Step 10-1-4 のベースラインと category 別 recall@k / precision@k を
                比較して work_log.md に Before/After 表で記録する。
                structured カテゴリの recall@k = 1.0（決定的正答）を合格基準とする。
  - TODO 10-5-4: tests/sanity_checks.py に Phase 10 チェックを追加する
                （既存の命名規則・`--phaseN` CLI 分岐に倣う）:
                ・`check_phase10_route_structured()`:
                  parse_query("広島市で最も高い建物は？") → classify_route が
                  "structured" を返し、hybrid_search の候補先頭が
                  `SELECT id FROM building_chunks WHERE measured_height > 0
                   ORDER BY measured_height DESC LIMIT 1` と一致すること
                ・`check_phase10_route_hybrid()`:
                  「駅から300m以内で日当たりのよい建物」→ route="hybrid" かつ
                  全候補の nearest_station_dist_m <= 300 であること
                ・`check_phase10_risk_filter()`:
                  「高潮リスクがない建物」→ 全候補の ht_depth_max が NULL であること
                ・`run_phase10_checks()` と `--phase10` CLI 分岐を追加
  - TODO 10-5-5: 全サニティチェック（既存 Phase 分含む）のパスを確認し、
                work_log.md 更新 → Step 単位で git commit
                （コミット規則: `feat(phase10): <日本語概要>`）

---

## Phase 11: ベクトル検索側の識別力改善（埋め込み再生成は対象外）

承認日: 2026-07-17（Step 11-1 は関数実装・サンプル検証のみ。再埋め込み・
building_chunk_sections の作成/投入は本 Phase では実施しない）

> **背景:** カルテ間コサイン類似度が 0.83〜0.96 に密集する原因は、
> text_card の大半が全建物共通の定型文（セクション見出し・「データなし」
> 「リスクなし（浸水想定区域外）」等）で占められているため。
> 埋め込み用テキストと LLM 提示用テキストを分離するのが本来の方針だが、
> 今回は **gemini-embedding-001 の再埋め込みを実施しない**（Free Tier の
> クォータ消費・日数がかかるため）。よって以下の範囲に限定する:
>   - Step 11-1: 埋め込み用テキストの再設計＝関数実装とサンプル出力の目視確認のみ。
>     `building_chunk_sections` テーブルの作成・投入・vector_search() 拡張は
>     re-embedding が前提のため今回は行わない（将来の再埋め込み時にそのまま使える
>     形で関数を用意しておく）。
>   - Step 11-2: 既存の text_card・埋め込み・building_chunks のみで完結する
>     FTS×ベクトルのハイブリッド検索（RRF）と HyDE 的クエリ書き換えを実装する
>     （どちらも新規の埋め込み生成を必要としない）。

### Step 11-1: 埋め込み用テキストの再設計（関数実装のみ・再埋め込みなし）
  - TODO 11-1-1: `src/phase3_enrichment.py` に `build_embed_text(row: dict, cl: "CodelistLoader",
                geom_meta: dict | None = None) -> dict[str, str]` を新規実装する
                （`build_text_card` はプロンプト提示用にそのまま残し、変更しない）。
                戻り値はセクション別テキストの辞書:
                ```python
                {
                  "risk":     "高潮浸水最大3.2m。洪水リスクなし。津波リスクなし。",   # 定型見出し・箇条書き記号なし
                  "environ":  "宿泊施設。広島駅まで210m。中央公園まで340m。…",       # 固有名詞＋数値中心
                  "shape":    "高さ45.2m、12階建て。南向き壁面が主体。",             # geom_meta なしなら空文字
                }
                ```
                設計規則:
                ・「データなし」に相当する行は出力しない（未設定セクションは
                  他の有効な情報だけで構成し、全て無効なら空文字を返す）
                ・セクション見出し（[災害リスク]等）・「・」等の箇条書き記号を含めない
                ・数値は丸めて単位付き日本語文にする（例: 「約210m」ではなく「210m」
                  のように簡潔に。他の値との重複表現を避ける）
                ・`risk` セクション: 高潮/洪水/津波の順に「◯◯浸水最大X.Xm」または
                  「◯◯リスクなし」を句点区切りで連結
                ・`environ` セクション: 用途 → 最寄り駅・避難所・公園・緊急輸送道路・
                  ランドマークの順に、データがあるもののみ「◯◯まで◯◯m」を連結
                ・`shape` セクション: geom_meta が None または building_height_m が
                  無効値の場合は空文字。有効な場合のみ高さ・階数・優勢な壁面方位
                  （比率5%超のみ）を連結
  - TODO 11-1-2: `build_embed_text()` の動作確認を行う。
                `tests/sanity_checks.py` の `assert_text_card_nonempty` と同じ
                サンプル建物データ（Phase 3 のテスト用 dict）に対して実行し、
                以下を目視確認する:
                ・各セクションに「データなし」等の定型文が含まれないこと
                ・`risk` / `environ` セクションが空文字にならないこと
                ・`shape` セクションは geom_meta=None のとき空文字になること
                本 TODO は printデバッグでの確認のみとし、DB への保存や
                embedding 生成（batch_embed 呼び出し）は行わない。
  - TODO 11-1-3（将来実施・今回はスコープ外）: 再埋め込みを実施する際は
                `building_chunk_sections` テーブル（id, section, text, embedding
                FLOAT[3072], PRIMARY KEY(id, section)）を作成し、
                `build_embed_text()` の出力を `batch_embed()` で埋め込んで投入、
                `vector_search()` にセクション別 MAX 集約検索を追加する。
                本計画には設計を残すのみとし、実装・実行はしない。

### Step 11-2: ハイブリッド検索の高度化（FTS×ベクトル RRF・HyDE。再埋め込み不要）

  - TODO 11-2-1: DuckDB FTS 拡張のインストール・インデックス作成を
                `src/phase11_hybrid_search.py`（新規作成）に実装する。
                `ensure_fts_index(rag_con)`:
                ```sql
                INSTALL fts; LOAD fts;
                PRAGMA create_fts_index(
                    'building_chunks', 'id', 'text_card',
                    stemmer = 'none', overwrite = 1
                );
                ```
                日本語は空白区切りでないため DuckDB FTS の既定トークナイザでは
                精度が落ちる可能性がある点を関数のコメントに明記し、
                TODO 11-2-3 の検証で実際の効果を確認する（分かち書き前処理が
                必要と判明した場合は本 TODO のスコープ外として work_log に記録）。
  - TODO 11-2-2: 同ファイルに以下を実装する。
                `fts_search(rag_con, query_text: str, top_k: int = 30) -> pd.DataFrame`:
                `SELECT id, fts_main_building_chunks.match_bm25(id, ?) AS bm25_score
                 FROM building_chunks WHERE bm25_score IS NOT NULL
                 ORDER BY bm25_score DESC LIMIT ?` を実行し返す。
                `rrf_merge(vec_df: pd.DataFrame, fts_df: pd.DataFrame, k: int = 60,
                id_col: str = "id") -> pd.DataFrame`:
                各 DataFrame の順位（1始まり）から
                `rrf_score = 1/(k+rank_vec) + 1/(k+rank_fts)`（片方に無い場合は
                その項を0とする）を計算し、`rrf_score` 降順にマージした
                DataFrame（元の vec_df の列を保持し rrf_score 列を追加）を返す。
  - TODO 11-2-3: `phase4_retrieval.py` の `vector_search()` の semantic/hybrid 経路に
                `use_fts: bool = False` 引数を追加する。True の場合、
                ベクトル検索結果（top_k*2件程度）と `fts_search()` の結果を
                `rrf_merge()` で融合してから top_k に絞り込む。
                `hybrid_search()` にも `use_fts: bool = False` を追加し
                `vector_search()` へ伝播する。
  - TODO 11-2-4: `tests/eval_retrieval.py` の `evaluate()` に `use_fts: bool = False`
                引数を追加し、`hybrid_search()` へ伝播する。固有名詞を含む
                ゴールドクエリ（駅名・公園名・ランドマーク名）で `use_fts=True/False`
                の recall@k を比較し、work_log.md に記録する。
  - TODO 11-2-5: HyDE 的クエリ書き換えを `src/phase11_hybrid_search.py` に実装する。
                `hyde_rewrite(semantic_residual: str) -> str`:
                Gemini Flash（temperature=0）に「以下の検索意図を満たす建物の
                特徴を、実際の建物カルテと同じ簡潔な日本語の説明文として
                2〜3文で生成してください（建物IDや具体的な数値は創作しないこと）」
                という指示で `semantic_residual` を仮想カルテ文に変換する。
                失敗時は元の `semantic_residual` をそのまま返す（フォールバック）。
  - TODO 11-2-6: `hybrid_search()` に `use_hyde: bool = False` を追加する。
                True かつ route が hybrid/semantic の場合、`embed_query()` に渡す
                テキストを `hyde_rewrite(embed_text)` の出力に置き換える。
                `tests/eval_retrieval.py` の `evaluate()` にも `use_hyde` 引数を
                追加し、semantic カテゴリ（recall 計測不可のため定性確認のみ）で
                `use_hyde=True/False` の候補建物を目視比較する。
  - TODO 11-2-7: `tests/sanity_checks.py` に Phase 11 用チェックを追加する:
                ・`check_phase11_fts_index()`: `ensure_fts_index()` 実行後に
                  `fts_search()` が1件以上返すこと
                ・`check_phase11_rrf_merge()`: 人工的な vec_df/fts_df（各3件、
                  一部重複ID）で `rrf_merge()` を実行し、重複IDのスコアが
                  加算されること・全件が結果に含まれることを確認
                ・`check_phase11_hyde_fallback()`: GEMINI_API_KEY 不在を模した
                  異常系、または通常呼び出しで `hyde_rewrite()` が例外を
                  発生させず文字列を返すこと
                `run_phase11_checks()` と `--phase11` CLI 分岐を追加する。
  - TODO 11-2-8: 効果測定結果（TODO 11-2-4 の recall 比較、TODO 11-2-6 の定性
                比較）と、採用/不採用の判断（デフォルト値をどちらにするか）を
                work_log.md に記録し、Step 単位で git commit する
                （コミット規則: `feat(phase11): <日本語概要>`）。

---

## Phase 12: SudachiPy 分かち書きによる FTS 有効化

承認日: （未承認 — 実装開始前にユーザー承認を得ること）

> **背景（Phase 11 Step 11-2 の実測結果）:**
> - DuckDB FTS の既定トークナイザは ASCII 空白・半角記号のみを区切りとするため、
>   区切りのない連続日本語文である text_card では固有名詞が単独トークンに
>   ならず、`fts_search('広島駅')` が 0 件になることを確認済み。
> - 埋め込み（意味検索）側はモデル内部のサブワード分割で機能しているため
>   **変更不要**。分かち書きは FTS（BM25）専用の前処理である。
> - トークナイザには SudachiPy（辞書: sudachidict_core、分割モード C）を採用する。
>   Mode C は「広島駅」のような固有名詞・複合語を1トークンに保つため、
>   今回の症状に直接効く。fugashi より低速だが全 2,958 件規模では無視できる。
>
> **設計方針:**
> - `building_chunks` は HNSW インデックス（実験的永続化）を持つため
>   ALTER TABLE で分かち書きカラムを追加せず、**FTS 専用の別テーブル
>   `building_chunks_fts(id, wakati)`** を新設して索引を張る。
> - ドキュメント側・クエリ側で**同一のトークナイズ関数**を必ず通す
>   （設定が食い違うと一致しない）。
> - Phase 11 で実装済みの `use_fts` フラグ・`rrf_merge()`・評価基盤
>   （`eval_retrieval.py --fts`）はそのまま再利用する。

### Step 12-1: 依存パッケージの追加（pixi）

  - TODO 12-1-1: SudachiPy と辞書を pixi で追加する。
                まず conda-forge を試す:
                `/c/Users/pikkarin/AppData/Local/pixi/bin/pixi.exe add sudachipy sudachidict-core`
                conda-forge に存在しない・解決に失敗する場合は pixi.toml の
                `[pypi-dependencies]` セクションに
                `sudachipy = ">=0.6"` / `sudachidict-core = "*"` を記載して
                `pixi.exe install` する（どちらの経路を採ったか work_log に記録）。
  - TODO 12-1-2: インストール確認:
                `pixi.exe run python -c "from sudachipy import Dictionary, SplitMode;
                t = Dictionary().create(); print([m.surface() for m in
                t.tokenize('広島駅（山陽本線）約800m', SplitMode.C)])"`
                出力に `広島駅` が単独トークンとして含まれることを確認する。

### Step 12-2: トークナイズ関数の実装（phase11_hybrid_search.py に追加）

  - TODO 12-2-1: `src/phase11_hybrid_search.py` に以下を実装する:
                ```python
                _sudachi_tokenizer = None  # モジュールレベル遅延キャッシュ

                def tokenize_ja(text: str) -> str:
                    """SudachiPy Mode C で分かち書きし、表層形を半角スペース区切りで返す。
                    空白・記号のみのトークンは除外する。text が空なら空文字を返す。"""
                ```
                実装規則:
                ・`Dictionary().create()` は初回のみ生成しモジュール変数にキャッシュ
                  （辞書ロードが重いため。呼び出しごとの生成は禁止）
                ・`SplitMode.C` を使用（固有名詞・複合語を1トークンに保つ）
                ・`m.surface().strip()` が空のトークンは除外
                ・Sudachi は1回の tokenize に約 49,000 文字の上限があるため、
                  text_card（平均 579 文字）では問題ないが、防御として
                  10,000 文字超は改行単位で分割してから処理する
  - TODO 12-2-2: 単体動作確認（print デバッグ）:
                `tokenize_ja('建物ID: bldg_b 用途: 住宅 最寄り駅: 横川駅（可部線）約500m')`
                の出力に `住宅` `横川駅` が独立トークンとして含まれること。

### Step 12-3: FTS 専用テーブル・インデックス再構築

  - TODO 12-3-1: `ensure_fts_index(rag_con)` を全面改修する:
                ```
                ① INSTALL fts; LOAD fts;
                ② CREATE TABLE IF NOT EXISTS building_chunks_fts (
                       id     VARCHAR PRIMARY KEY,
                       wakati VARCHAR NOT NULL
                   );
                ③ building_chunks_fts の件数が building_chunks の件数と
                   一致しない場合のみ再構築:
                   ・DELETE FROM building_chunks_fts
                   ・SELECT id, text_card FROM building_chunks を全件取得し、
                     Python 側で tokenize_ja(text_card) を適用して
                     executemany / register で一括 INSERT
                     （2,958 件 × 平均 579 文字。Sudachi Mode C で数十秒程度の見込み）
                ④ PRAGMA create_fts_index('building_chunks_fts', 'id', 'wakati',
                                          stemmer='none', overwrite=1)
                ```
                ※ 旧実装（building_chunks.text_card への直接索引）は削除する。
                  既存 DB に残る旧 FTS スキーマ `fts_main_building_chunks` は
                  `PRAGMA drop_fts_index('building_chunks')` で削除を試み、
                  失敗しても無視して続行する（try/except）。
  - TODO 12-3-2: `fts_search(rag_con, query_text, top_k)` を改修する:
                ・検索前に `query_text = tokenize_ja(query_text)` を適用
                ・参照先を `fts_main_building_chunks_fts.match_bm25(id, ?)`
                  / `FROM building_chunks_fts` に変更
                ・戻り値スキーマ（id, bm25_score）は変更しない
                  （rrf_merge・vector_search 側の呼び出しコードは無修正で動く）
  - TODO 12-3-3: `phase4_retrieval.py` の FTS インデックス存在チェックを
                新スキーマ名に合わせて更新する:
                `schema_name = 'fts_main_building_chunks_fts'`
                （加えて building_chunks_fts テーブル自体の存在も確認する）

### Step 12-4: 動作確認・効果測定

  - TODO 12-4-1: 実データで固有名詞ヒットを確認する（Phase 11 で 0 件だった症状の解消確認）:
                ・`fts_search(con, '広島駅', top_k=10)` → **1 件以上**（合格基準）
                ・`fts_search(con, '平和記念公園', top_k=10)` → 1 件以上
                ・`fts_search(con, '住宅', top_k=10)` → 1 件以上（既存動作の維持）
  - TODO 12-4-2: `pixi run python tests/eval_retrieval.py --fts` を再実行し、
                Phase 11 時点の結果（use_fts 効果ゼロ）と比較して work_log.md に記録する。
                観点:
                ・structured カテゴリは FTS 経路を通らないため不変であること（回帰確認）
                ・hybrid / semantic カテゴリでの候補変化・recall 変化
                ・固有名詞を含むクエリ（G09 駅・G12 公園・G16 ランドマーク）の変化に注目
  - TODO 12-4-3: 効果測定の結果に基づき `use_fts` のデフォルト値を判断する:
                ・recall/hit@1 が改善または不変（劣化なし）→ デフォルト True 化を検討し
                  ユーザーに提案（インデックス初回構築コストとのトレードオフを併記）
                ・劣化が観測された場合 → デフォルト False のまま、原因を work_log に記録

### Step 12-5: サニティチェック・コミット

  - TODO 12-5-1: `tests/sanity_checks.py` の Phase 11 チェックを更新・追加する:
                ・`check_phase11_fts_index()` を改修: 検証クエリを「住宅」から
                  **「広島駅」に変更**（分かち書き導入の核心が固有名詞ヒットのため。
                  docstring の「連続日本語文では固有名詞がヒットしない場合がある」
                  という注記も削除する）
                ・`check_phase12_tokenize()` を新規追加:
                  `tokenize_ja('横川駅（可部線）約500m')` の結果に `横川駅` が
                  含まれ、空トークンが含まれないこと
                ・`check_phase12_fts_rebuild()` を新規追加:
                  `building_chunks_fts` の件数が `building_chunks` と一致すること
                ・`run_phase12_checks()` と `--phase12` CLI 分岐を追加
                  （Phase 11 の 3 チェックも `run_phase12_checks()` から再実行して
                  回帰確認を兼ねる）
  - TODO 12-5-2: `--phase9` / `--phase10` / `--phase11` / `--phase12` の全チェック
                パスを確認し、work_log.md 更新 → Step 単位で git commit
                （コミット規則: `feat(phase12): <日本語概要>`）。
                pixi.toml / pixi.lock の変更は Step 12-1 のコミットに含める。

---

## Phase 13: 幾何・近傍コンテキストの前計算拡充

承認日: 2026-07-19

> **背景（FOSS4G 提案書とのギャップ調査より）:**
> `building_geom_meta`（Phase 9）に `wall_ratio_n/e/s/w` が既に存在するにもかかわらず、
> query_parser → router → verify_candidates → LLM プロンプトのどこからも参照されておらず、
> 提案書の看板クエリ「日当たりのよい建物」が実質ベクトル検索（識別力ほぼ無し）に
> 丸投げされている。本 Phase はこの「配線の欠落」と「建物間関係の前計算の欠落」を、
> **追加データなし**（`hiroshima_sample.gpkg` / `hiroshima_sample_maxlod.gpkg` /
> `data/related/*.geojson` の既存ファイルのみ）で解消する。
>
> **方針:**
> - 単一建物で閉じる指標（屋根形状・体積近似等）は `building_geom_meta` に追加カラムとして拡張する。
> - 建物間の関係（南側遮蔽・近傍密度・最近傍施設種別）は新テーブル
>   `building_context_meta` に分離する（パラメータ調整のたびに Phase 9 の
>   面解析を再実行しなくて済むようにするため）。
> - `data/related/34100_hiroshima-shi_city_2022_landmark.geojson` の `種類` 属性
>   （学校251/病院52/警察署70/消防署30/郵便局133 件を含む）を種別分解して
>   活用する。**新規ファイルの追加は不要**（既存 landmark.geojson の再利用）。
> - 閾値（陸屋根判定・冬至仰角・幹線道路幅員）はすべて「仮置き→実データ分布で
>   確認→確定値を work_log に記録」の手順を踏む（Phase 10 の G09/G11/G16 と同じ手順）。

### Step 13-1: 屋根・形状指標の追加（phase9_geometry.py 拡張）

  - TODO 13-1-1: `classify_face()` の呼び出し元 `analyze_building()` で、
                `face_type == "roof"` と判定された面ごとに勾配角度
                `slope_deg = math.degrees(math.acos(min(1.0, max(-1.0, nz))))`
                （nz は単位法線の Z 成分。roof 分類済みなので通常 0°〜36.87° の範囲）
                を計算し、面積で加重平均した `roof_slope_mean_deg` を求める
                （屋根面が 0 の建物は None）。
  - TODO 13-1-2: 同じループ内で `flat_roof_area`（`slope_deg < 10.0` の屋根面積の合計）
                を集計し、`flat_roof_ratio = flat_roof_area / roof_area`
                （`roof_area` が 0 の場合は None）を計算する。
  - TODO 13-1-3: `roof_type_est` を導出するヘルパー関数
                `estimate_roof_type(flat_roof_ratio: float | None) -> str | None` を追加する:
                `flat_roof_ratio is None → None`、`>= 0.7 → "陸屋根"`、`< 0.7 → "勾配屋根"`。
                閾値 `0.7` はモジュール定数 `_FLAT_ROOF_THRESHOLD = 0.7` として定義し、
                Step 13-4（分布確認）で確定するまでの仮値であることをコメントに明記する。
  - TODO 13-1-4: `analyze_building()` の戻り値（および `_empty_meta()`）に
                `roof_slope_mean_deg`, `flat_roof_ratio`, `roof_type_est` の 3 キーを追加する。
  - TODO 13-1-5: `hiroshima_sample.gpkg`（LOD1相当の2Dフットプリント。maxlod ではない
                通常版）から `bldg:Building.geometry` の `ST_Area()` を取得し
                `footprint_area_m2` を計算する関数 `fetch_footprint_areas(gpkg_path) -> pd.DataFrame`
                （列: id, footprint_area_m2）を新規実装する。
                実装前に `ST_GeometryType()` または `ST_Z()` の有無で該当ジオメトリが
                2D（Z 値なし）であることを確認し、3D だった場合は `ST_Force2D()` してから
                `ST_Area()` を呼ぶガードを入れる。
  - TODO 13-1-6: `extract_geom_meta()`内で `fetch_footprint_areas()` の結果を
                建物解析結果 DataFrame に `id` で LEFT JOIN し、以下を計算する:
                `volume_m3 = footprint_area_m2 * building_height_m`
                （メッシュが閉多面体でないための近似値。カラムコメントに明記）、
                `slenderness = building_height_m / sqrt(footprint_area_m2)`
                （`footprint_area_m2` が NULL または 0 の場合は両方 None）。
  - TODO 13-1-7: `create_geom_meta_table()` の CREATE TABLE 文に新カラム 6 種
                （`roof_slope_mean_deg DOUBLE`, `flat_roof_ratio DOUBLE`,
                `roof_type_est VARCHAR`, `footprint_area_m2 DOUBLE`,
                `volume_m3 DOUBLE`, `slenderness DOUBLE`）を追加し、それぞれに
                単位・近似である旨のコメントを付与する。
  - TODO 13-1-8: `extract_geom_meta()` の DataFrame 列リスト（`pd.DataFrame(records, columns=[...])`）
                と統計サマリー出力（print）に新カラムを追加する
                （`roof_type_est` の value_counts、`flat_roof_ratio` の平均、
                `volume_m3` / `slenderness` の平均・最大を出力）。
  - TODO 13-1-9: `if __name__ == "__main__":` ブロックを、既存 `building_geom_meta`
                の有無に関わらず常に DROP → 再作成するよう確認する（既存動作のまま）。
                `pixi run python src/phase9_geometry.py` で 2,958 件を再生成し、
                実行時間・統計サマリーを work_log 用に控えておく
                （text_card・embedding・building_chunks は本 Step では一切変更しない）。

### Step 13-2: 建物間コンテキストの前計算（src/phase13_context.py 新規作成）

  - TODO 13-2-1: `src/phase13_context.py` を新規作成し、以下のヘッダコメントを付与する:
                「建物間の空間関係（南側遮蔽・近傍密度・最近傍施設種別）を事前計算し
                building_context_meta テーブルに保存する。単一建物属性は phase9_geometry.py
                （building_geom_meta）を参照。」
  - TODO 13-2-2: `create_context_meta_table(rag_con)` を実装する:
                ```sql
                CREATE TABLE building_context_meta (
                    id                         VARCHAR PRIMARY KEY,
                    south_max_elev_angle_deg   DOUBLE,   -- 南側扇形(135-225°)内の近傍への最大仰角(度)。近傍なしは0.0
                    winter_sunlit              BOOLEAN,  -- 冬至南中でも日照が確保できるか（仰角30°未満で快晴扱い）
                    prominence_m               DOUBLE,   -- 自建物頂部標高 - 近傍(100m以内)最高建物頂部標高
                    wooden_density_ratio       DOUBLE,   -- 近傍(100m以内)建物に占める木造建物の比率(0-1)。近傍0件はNULL
                    nearest_major_road_dist_m  DOUBLE,   -- 幹線道路(基準は work_log記載の閾値)までの距離(m)
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
                ```
                既存テーブルは DROP して再作成する（phase9_geometry.py の流儀に合わせる）。
  - TODO 13-2-3: 近傍ペア抽出関数 `fetch_neighbor_pairs(rag_con, radius_m: float = 100.0) -> pd.DataFrame`
                を実装する。`building_chunks.geometry` から
                `ST_Centroid` 同士の自己結合を行い
                `SELECT a.id, b.id AS neighbor_id, ST_Distance(ca, cb) AS dist_m,
                 ST_X(cb)-ST_X(ca) AS dx, ST_Y(cb)-ST_Y(ca) AS dy
                 FROM ... WHERE ST_DWithin(ca, cb, ?) AND a.id <> b.id`
                で `(id, neighbor_id, dist_m, dx, dy)` を返す
                （方位角は Python 側で `math.degrees(math.atan2(dx, dy)) % 360`
                として phase9 の `wall_azimuth_deg()` と同じ規約に揃える）。
  - TODO 13-2-4: 近傍の頂部標高を引くため、`building_geom_meta` から
                `top_elev_m = ground_elev_m + building_height_m` を計算した
                `id → top_elev_m` の辞書を作るヘルパー `_load_top_elevations(rag_con) -> dict`
                を実装する（`building_height_m` が None の建物は辞書から除外）。
  - TODO 13-2-5: `compute_south_shading(pairs_df, top_elev_map, ground_elev_map) -> pd.DataFrame`
                を実装する。`pairs_df` を方位角 135°〜225° に絞り込み、各 `id` について
                `隣の頂部標高 - 自分の地面標高` と `dist_m` から
                `elev_angle = degrees(atan2(隣top - 自分ground, dist_m))` を計算し
                （負値＝隣が自分より低い場合は 0° 扱いにクリップ）、
                `id` ごとの最大値を `south_max_elev_angle_deg` とする（南側近傍 0 件は 0.0）。
                `winter_sunlit = south_max_elev_angle_deg < _WINTER_SUN_THRESHOLD_DEG`
                （モジュール定数 `_WINTER_SUN_THRESHOLD_DEG = 30.0`。広島の冬至南中高度
                ≈32.2°から算出した仮値である旨をコメントに明記し、Step 13-4 で確定する）。
  - TODO 13-2-6: `compute_prominence(pairs_df, top_elev_map) -> pd.DataFrame` を実装する。
                `id` ごとに近傍（全方位、pairs_df の全件）の `top_elev_m` の最大値を求め、
                `prominence_m = 自分のtop_elev_m - 近傍最大top_elev_m`。
                近傍 0 件（孤立建物）の場合は `prominence_m = building_height_m` とする
                （比較対象がないため自身の高さをそのまま突出度とみなす）。
  - TODO 13-2-7: `compute_wooden_density(pairs_df, structure_map) -> pd.DataFrame` を実装する。
                `structure_map` は `{id: structure_type}`（`building_chunks.structure_type`
                から取得）。`id` ごとに近傍のうち `structure_type == '木造・土蔵造'` の
                比率を計算する（近傍 0 件は None）。
  - TODO 13-2-8: 幹線道路までの距離を実装する `compute_major_road_dist(gpkg_con, rag_con) -> pd.DataFrame`。
                実装前に `SELECT width, numberOfLanes FROM st_read(gpkg, layer='uro:RoadStructureAttribute')`
                の分布（ヒストグラムまたは describe()）を確認し、モジュール定数
                `_MAJOR_ROAD_MIN_WIDTH = 13.0`, `_MAJOR_ROAD_MIN_LANES = 4` を
                仮設定する（Step 13-4 で確定）。`tran:Road` を
                `width >= _MAJOR_ROAD_MIN_WIDTH OR numberOfLanes >= _MAJOR_ROAD_MIN_LANES`
                で絞り込み、`building_chunks.geometry` の centroid との
                `MIN(ST_Distance(...))` を建物ごとに計算する
                （Phase 3 の `nearest_road` CTE と同じ CROSS JOIN + GROUP BY パターンを踏襲）。
                該当する幹線道路が 0 件の場合は全建物 NULL とし、その旨を print で警告する。
  - TODO 13-2-9: `data/related/34100_hiroshima-shi_city_2022_landmark.geojson` を
                読み込み `種類` 列で以下にフィルタする
                `compute_nearest_facility(gpkg_con, landmark_path, category_map) -> dict[str, pd.DataFrame]`
                を実装する:
                ```python
                _FACILITY_CATEGORY_MAP = {
                    "学校": "school", "病院": "hospital", "警察署": "police",
                    "消防署": "fire", "郵便局": "post",
                }
                ```
                各カテゴリごとに Phase 3 の `nearest_shelter` 等と同じ
                CROSS JOIN + ARG_MIN パターン（WGS84→EPSG:6671変換込み）で
                `(building_id, nearest_{cat}_name, nearest_{cat}_dist_m)` を計算し、
                カテゴリ名 → DataFrame の dict を返す。
  - TODO 13-2-10: `build_context_meta(rag_con, gpkg_con) -> pd.DataFrame` を実装し、
                TODO 13-2-3〜13-2-9 の結果をすべて `id` で LEFT JOIN して
                1 つの DataFrame にまとめる（`building_chunks` の全 id を基準に
                LEFT JOIN し、値がない場合は NULL のまま残す）。
  - TODO 13-2-11: `save_context_meta(rag_con, df)` で `building_context_meta` へ
                一括 INSERT する（`phase9_geometry.py::extract_geom_meta` の
                INSERT パターンを踏襲）。統計サマリー（`winter_sunlit` の True 率、
                `prominence_m` の分布、カテゴリ別最近傍距離の平均、
                `nearest_major_road_dist_m` が NULL の件数）を print する。
  - TODO 13-2-12: `if __name__ == "__main__":` で `connect_rag()` →
                `create_context_meta_table()` → `build_context_meta()` →
                `save_context_meta()` を実行するエントリーポイントを実装する。

### Step 13-3: サニティチェック・分布確認・コミット

  - TODO 13-3-1: `tests/sanity_checks.py` に `check_phase13_geom_meta_extended()`
                を追加する: `building_geom_meta` の新カラム 6 種が存在し
                （`information_schema.columns` で確認）、`flat_roof_ratio` が
                NULL または `0.0〜1.0` の範囲に収まる件数が全体と一致することを確認する。
  - TODO 13-3-2: `check_phase13_context_meta()` を追加する:
                `building_context_meta` の件数が `building_chunks` と一致すること、
                `winter_sunlit` に True/False 両方が存在すること、
                `nearest_school_dist_m` が非 NULL の件数が 0 でないことを確認する。
  - TODO 13-3-3: `run_phase13_checks()` と `--phase13` CLI 分岐を追加する。
  - TODO 13-3-4: TODO 13-1-3（flat_roof 閾値 0.7）・TODO 13-2-5（冬至仰角 30°）・
                TODO 13-2-8（幹線道路 width>=13.0 or lanes>=4）について、実データでの
                分布（該当件数・パーセンタイル）を確認し、確定値（または据え置きの判断）
                を work_log.md に記録する。極端な偏り（99% が該当/非該当等）があれば
                閾値を調整して再実行する。
  - TODO 13-3-5: `--phase13` 全チェックパス確認 → work_log.md 更新 → git commit。
                Step 13-1（`feat(phase13): 屋根・形状指標をbuilding_geom_metaに追加`）と
                Step 13-2（`feat(phase13): 建物間コンテキストテーブルを新設`）は
                別コミットとする。Step 13-3 は
                `test(phase13): サニティチェック追加・閾値確定`。

---

## Phase 14: 評価基盤の拡充（ゴールドセット v2・ベースライン計測）

承認日: 2026-07-19

> **方針:** Phase 10 と同じ順序（ゴールド確定 → Before 計測 → 実装 → After 計測）を踏む。
> Phase 13 で新設したカラムにより、従来 semantic（recall 測定不能）だった方位・日照系
> クエリが gold_sql で機械的に定義できるようになる。

### Step 14-1: ゴールドクエリの追加（tests/gold_set.py 拡張）

  - TODO 14-1-1: `GOLD_QUERIES` に category `"geometric"` として ID G21〜G30 の
                10 件を追加する（各要素は既存スキーマ `{id, query, category, gold_sql, note}`
                に従う）:
                - G21「南向きの壁面が最も大きい建物は？」:
                  `SELECT id FROM building_geom_meta WHERE wall_area_total_m2 > 0
                   ORDER BY wall_ratio_s DESC LIMIT 5`
                - G22「西日の当たらない建物」:
                  `SELECT id FROM building_geom_meta WHERE wall_area_total_m2 > 0
                   AND wall_ratio_w <= 0.1`
                - G23「日当たりのよい建物」（**擬似ゴールド**。note に定義式を明記）:
                  `SELECT g.id FROM building_geom_meta g
                   JOIN building_context_meta c ON g.id = c.id
                   WHERE c.winter_sunlit AND g.wall_ratio_s >= 0.3`
                - G24「屋上が広い建物トップ5」:
                  `SELECT id FROM building_geom_meta WHERE roof_area_m2 IS NOT NULL
                   ORDER BY roof_area_m2 DESC LIMIT 5`
                - G25「屋根が平らな建物」:
                  `SELECT id FROM building_geom_meta WHERE roof_type_est = '陸屋根'`
                - G26「高台にある建物」（閾値はTODO 14-1-3で分布確認の上パーセンタイルで確定。
                  仮に上位10%）:
                  `SELECT id FROM building_geom_meta WHERE ground_elev_m >=
                   (SELECT quantile_cont(ground_elev_m, 0.9) FROM building_geom_meta)`
                - G27「静かな環境の共同住宅」:
                  `SELECT b.id FROM building_chunks b JOIN building_context_meta c
                   ON b.id = c.id WHERE c.nearest_major_road_dist_m >= 100
                   AND b.usage = '共同住宅'`
                - G28「浸水しても上層階に避難できる建物」（垂直避難。実装と定義式を
                  共有する定数化を Step 15-2-2 で行う。ここでは SQL として直書き）:
                  `SELECT id FROM building_chunks WHERE storeys >= 3 AND measured_height > 0
                   AND measured_height - GREATEST(COALESCE(ht_depth_max,0),
                   COALESCE(rv_depth_max,0), COALESCE(ts_depth_max,0)) >= 6.0`
                - G29「はしご車が届く高さで緊急輸送道路に近い建物」:
                  `SELECT id FROM building_chunks WHERE measured_height BETWEEN 0.1 AND 31.0
                   AND nearest_emroute_dist_m <= 100`
                - G30「木造密集地にある耐火建築物」:
                  `SELECT b.id FROM building_chunks b JOIN building_context_meta c
                   ON b.id = c.id WHERE c.wooden_density_ratio >= 0.5
                   AND b.fire_proof = '耐火'`
  - TODO 14-1-2: category `"robustness"` として ID G31〜G36 の 6 件を追加する:
                - G31「木造以外の建物」（除外条件）:
                  `SELECT id FROM building_chunks WHERE structure_type IS NOT NULL
                   AND structure_type <> '木造・土蔵造'`
                - G32「高さ20m以上40m以下の建物」（範囲条件）:
                  `SELECT id FROM building_chunks WHERE measured_height BETWEEN 20.0 AND 40.0`
                - G33「高潮リスクがなく駅から100m以内の宿泊施設」（**正解0件を事前確認の上で採用**。
                  note に「候補0件かつ回答が該当なしを明言すれば合格」という定性合格基準を明記）:
                  `SELECT id FROM building_chunks WHERE ht_depth_max IS NULL
                   AND nearest_station_dist_m <= 100 AND usage = '宿泊施設'`
                - G34「広島駅から500m以内で日当たりのよい建物」（空間×幾何のハイブリッド）:
                  G23 の SQL に `AND ST_DWithin(b.geometry, ST_Point(<広島駅x>, <広島駅y>), 500)`
                  を追加（座標は `geocoder.geocode('広島駅')` の結果を事前計算し定数として埋め込む）
                - G35「学校まで300m以内の共同住宅」:
                  `SELECT b.id FROM building_chunks b JOIN building_context_meta c
                   ON b.id = c.id WHERE c.nearest_school_dist_m <= 300
                   AND b.usage = '共同住宅'`
                - G36「病院に近く洪水リスクのない建物」:
                  `SELECT b.id FROM building_chunks b JOIN building_context_meta c
                   ON b.id = c.id WHERE c.nearest_hospital_dist_m <= 500
                   AND b.rv_depth_max IS NULL`
  - TODO 14-1-3: `pixi run python tests/gold_set.py` 相当の実行で G21〜G36 の
                母数を確認する。0 件または全件近く（Phase 10 の G09/G11/G16 と同じ基準：
                極端な母数は検証として無意味）になったクエリは閾値調整する
                （G33 は意図的な0件なので対象外）。G26 のパーセンタイル基準は
                このタイミングで確定する。調整内容を work_log に記録。
  - TODO 14-1-4: `build_gold()` を実行し `output/gold_set.json` を
                20 件 → 36 件に更新する。`tests/eval_retrieval.py` の集計処理が
                category 名をデータ駆動で拾うことを確認する
                （固定リストになっていた場合は `"geometric"`, `"robustness"` を追加）。
                G33（正解0件）で recall の 0 除算が起きないよう、
                `evaluate()` に `gold_ids` が空集合の場合の分岐
                （candidates も空なら recall=1.0・precision=1.0 として扱う等の規約を
                コメントで明記）を追加する。

### Step 14-2: ベースライン計測（配線前）

  - TODO 14-2-1: 現行実装（Phase 15 着手前）のまま
                `pixi run python tests/eval_retrieval.py` を実行し、
                `geometric` / `robustness` カテゴリの Before 値
                （新フィールドが ParsedQuery に存在しないため大半が semantic ルートに
                落ち、recall はほぼ 0 になる想定）を CSV 出力とともに記録する。
                ※ Gemini API 呼び出しが 36 クエリ × (parse_query + embed_query) ≈ 70 回強に
                なるため、Free Tier クォータに注意し、必要なら
                `evaluate(query_ids=[...])` のような部分実行オプションの追加を検討する
                （既存 `evaluate()` にcrie引数がなければ、まず全量で1回試し、
                失敗時のみ最小限の絞り込み機能を追加する）。
  - TODO 14-2-2: 結果を work_log.md に記録し、
                `test(phase14): geometric/robustnessカテゴリのゴールドセット追加、ベースライン計測`
                で git commit する。

---

## Phase 15: クエリ解析・検索配線の拡張

承認日: 2026-07-19

### Step 15-1: query_parser.py の語彙拡張

  - TODO 15-1-1: `OrientationFilter` dataclass を追加する:
                ```python
                @dataclass
                class OrientationFilter:
                    direction: str   # "n" | "e" | "s" | "w"
                    mode: str        # "prefer"（その向き主体） | "avoid"（その向きを避ける）
                ```
  - TODO 15-1-2: `ParsedQuery` に以下のフィールドを追加する（既存フィールドは削除しない）:
                ```python
                orientation_filters: list[OrientationFilter] = field(default_factory=list)
                sunlight: bool = False
                quiet: bool = False
                vertical_evacuation: bool = False
                height_max: float | None = None
                storeys_min: int | None = None
                storeys_max: int | None = None
                usage_exclude: list[str] = field(default_factory=list)
                structure_exclude: list[str] = field(default_factory=list)
                roof_type: str | None = None   # "陸屋根" | "勾配屋根"
                ```
  - TODO 15-1-3: `_SORT_KEYS` に以下を追加する:
                `roof_area_m2 / ground_elev_m / prominence_m / volume_m3 /
                footprint_area_m2 / wall_ratio_n / wall_ratio_e / wall_ratio_s / wall_ratio_w /
                nearest_school_dist_m / nearest_hospital_dist_m`
  - TODO 15-1-4: `_DISTANCE_TARGETS` に `school / hospital / police / fire / post` を追加する
                （`DistanceFilter.target` の許容値を拡張。既存の
                station/shelter/park/emroute/landmark は維持）。
  - TODO 15-1-5: `_STRUCTURED_RULES` に以下の変換規則を追記する（既存の書式・
                「重要な区別」注記スタイルを踏襲し、例文を必ず添える）:
                - 「南向き」「南側に窓が多い」→ `orientation_filters=[{direction:"s", mode:"prefer"}]`
                - 「朝日が入る」→ direction="e" mode="prefer"、
                  「西日が当たらない」「北向きを避けたい」→ mode="avoid"
                - 「日当たりがよい」「日照重視」「日当たりを気にしている」→ `sunlight=true`
                  （**orientation_filters は設定しない**。遮蔽込みの判定は sunlight 専用フィールドが
                  担うため、南向き指定と二重に条件をかけない）
                - 「静かな」「騒音が少ない」「幹線道路から離れた」→ `quiet=true`
                - 「浸水しても上の階に逃げられる」「垂直避難できる」→ `vertical_evacuation=true`
                - 「Nm以下」「N階建て以下」→ `height_max` / `storeys_max`（既存の
                  height_min とは独立。両方設定されれば範囲指定になる）
                - 「N階建て以上」→ `storeys_min`（`height_min` の3m換算より優先して使う）
                - 「◯◯以外」「◯◯を除く」（用途）→ `usage_exclude`、
                  （構造）→ `structure_exclude`
                - 「屋上が広い」→ `sort_by={"key":"roof_area_m2","order":"desc"}`、
                  「平らな屋根」「陸屋根」→ `roof_type="陸屋根"`
                - 「高台」「標高が高い場所」→ `sort_by={"key":"ground_elev_m","order":"desc"}`、
                  「目立つ」「ひときわ高い」「周囲より突出した」→
                  `sort_by={"key":"prominence_m","order":"desc"}`
                - 「学校の近く」「病院まで徒歩10分」等は既存 distance_filters の
                  仕組みに `target` の新値（school等）で自然に乗る旨を明記
                - semantic_residual のルールに「上記いずれかで表現済みの語
                  （方位・日照・静けさ・階数範囲・除外・屋根・標高・卓越性）を
                  重複して残さないこと」を追記する。
  - TODO 15-1-6: `response_schema`（Gemini structured output 用 JSON スキーマ）に
                新フィールド 10 種を追加する。`orientation_filters` は
                `direction` enum ["n","e","s","w"] / `mode` enum ["prefer","avoid"] の
                object 配列とし、他は該当する型（boolean / number / string配列 / string）で
                定義し、すべて required に含める（既存フィールドと同じ流儀）。
  - TODO 15-1-7: `__main__` の test_cases に以下 6 件を期待値コメント付きで追加し、
                `pixi run python src/query_parser.py` で目視確認する:
                「南向きの建物」「西日の当たらない住宅」「日当たりのよい建物」
                「静かな環境の共同住宅」「木造以外で20m以上40m以下の建物」
                「屋上が広い建物」

### Step 15-2: ルーター・SQL ビルダーの拡張（phase10_router.py）

  - TODO 15-2-1: カラムのテーブル出所を表す辞書 `COLUMN_SOURCE` を定義する:
                ```python
                COLUMN_SOURCE = {
                    # "b"=building_chunks（既定）, "g"=building_geom_meta, "c"=building_context_meta
                    "wall_ratio_n": "g", "wall_ratio_e": "g", "wall_ratio_s": "g", "wall_ratio_w": "g",
                    "roof_area_m2": "g", "roof_type_est": "g", "ground_elev_m": "g",
                    "volume_m3": "g", "footprint_area_m2": "g",
                    "winter_sunlit": "c", "prominence_m": "c", "wooden_density_ratio": "c",
                    "nearest_major_road_dist_m": "c",
                    "nearest_school_dist_m": "c", "nearest_hospital_dist_m": "c",
                    "nearest_police_dist_m": "c", "nearest_fire_dist_m": "c", "nearest_post_dist_m": "c",
                }
                ```
                （building_chunks 由来のカラムは辞書に載せず「未掲載＝b」をデフォルトとする）
  - TODO 15-2-2: `build_filter_clauses(pq, alias)` のシグネチャに
                `table_aliases: dict[str, str] = {"b": "b.", "g": "g.", "c": "c."}` を追加し、
                `COLUMN_SOURCE` を引いて各条件に正しい alias を付与するよう改修する
                （空間フィルタなしで alias="" の呼び出し元は `table_aliases` も
                空文字に揃えた辞書を渡し、後方互換を保つ）。
                新フィルタの WHERE 句変換を追加する（すべてプレースホルダ使用、
                閾値はモジュール定数として一箇所に集約）:
                ```python
                ORIENT_PREFER_MIN = 0.3   # OrientationFilter mode="prefer" の下限
                ORIENT_AVOID_MAX = 0.1    # OrientationFilter mode="avoid" の上限
                SUNLIGHT_WALL_S_MIN = 0.2 # sunlight=true 時の南壁面比率下限
                QUIET_ROAD_MIN_M = 100.0  # quiet=true 時の幹線道路距離下限
                VERTICAL_EVAC_MARGIN_M = 6.0  # vertical_evacuation=true の余裕高さ
                ```
                - `OrientationFilter(direction=d, mode="prefer")` →
                  `wall_ratio_{d} >= ORIENT_PREFER_MIN`
                - `mode="avoid"` → `wall_ratio_{d} <= ORIENT_AVOID_MAX`
                - `sunlight=True` → `winter_sunlit = true AND wall_ratio_s >= SUNLIGHT_WALL_S_MIN`
                - `quiet=True` → `nearest_major_road_dist_m >= QUIET_ROAD_MIN_M`
                - `vertical_evacuation=True` →
                  `storeys >= 3 AND measured_height > 0 AND measured_height -
                   GREATEST(COALESCE(ht_depth_max,0),COALESCE(rv_depth_max,0),
                   COALESCE(ts_depth_max,0)) >= VERTICAL_EVAC_MARGIN_M`
                  （**Step 14-1 G28 の gold_sql と同一の定数・同一の式**であることをコメントで明記し、
                  評価と実装の定義ズレを防ぐ）
                - `height_max` → `measured_height > 0 AND measured_height <= ?`
                - `storeys_min` → `storeys >= ?`、`storeys_max` → `storeys <= ?`
                - `usage_exclude` → `usage NOT IN (?, ...)`（空リストなら句を生成しない）
                - `structure_exclude` → `structure_type NOT IN (?, ...)`
                - `roof_type` → `roof_type_est = ?`
                - `distance_filters` の target 別カラム対応表 `TARGET_COLUMN` に
                  `school/hospital/police/fire/post` を追加する
                  （`nearest_school_dist_m` 等、Step 13-2-2 のカラム名と一致させる）
  - TODO 15-2-3: `build_order_clause()` は `COLUMN_SOURCE` 経由で alias を解決するよう
                同様に改修する（ロジック自体（sort_by優先度・NULLS FIRST/LAST）は変更しない）。
  - TODO 15-2-4: `classify_route()` の `has_structured` 判定に新フィールド
                （orientation_filters, sunlight, quiet, vertical_evacuation, height_max,
                storeys_min, storeys_max, usage_exclude, structure_exclude, roof_type）を
                OR 条件に追加する。
  - TODO 15-2-5: `verify_candidates()` に新フィルタの pandas 側再評価を追加する。
                `build_filter_clauses` で使ったのと同じモジュール定数
                （ORIENT_PREFER_MIN 等）を import して使い、SQL とロジックがずれないようにする。
  - TODO 15-2-6: `phase4_retrieval.py::vector_search()` の `from_clause` 構築部を改修し、
                `has_geom_meta` に加えて `has_context_meta`
                （`information_schema.tables` で `building_context_meta` の存在確認）を追加、
                両方 true の場合のみ
                `FROM building_chunks b LEFT JOIN building_geom_meta g ON b.id=g.id
                 LEFT JOIN building_context_meta c ON b.id=c.id` とする
                （`has_geom_meta` のみ true・`has_context_meta` false の場合は
                Phase 9 相当の JOIN のみに留める後方互換を維持）。
  - TODO 15-2-7: `select_cols` に新カラムを追加する: `g.roof_area_m2, g.roof_type_est,
                g.ground_elev_m, g.wall_ratio_n, g.wall_ratio_e, g.wall_ratio_s, g.wall_ratio_w`
                （wall_ratio 系は既存 Step 9 分で選択済みか確認し、未選択なら追加）、
                `c.winter_sunlit, c.prominence_m, c.nearest_school_name,
                c.nearest_school_dist_m, c.nearest_hospital_name, c.nearest_hospital_dist_m`。
  - TODO 15-2-8: `has_context_meta = False` の場合に新フィルタ
                （orientation_filters 等）が指定されていたら、
                `hybrid_search()` 側で明示的なエラーメッセージ
                （"building_context_meta が存在しません。先に phase13_context.py を
                実行してください"）を返す分岐を追加する（サイレントに無視しない）。

### Step 15-3: LLM プロンプト・回答の拡張

  - TODO 15-3-1: `phase4_retrieval.py::build_prompt()` の Markdown 比較表に列を追加する:
                「主壁面方位」（4方位のうち最大比率の方位＋% を
                `f"{dir_label}{ratio*100:.0f}%"` 形式で1列にまとめる。全方位が5%未満なら「-」）、
                「冬日照」（`winter_sunlit` を「○」「×」「不明」で表示）、
                「屋根」（`roof_type_est` をそのまま表示、NULLは「不明」）、
                「標高(m)」（`ground_elev_m` を `.1f`、NULLは「不明」）。
                既存の NULL→「なし」/-9999.0→「不明」表示規則と一貫させる。
  - TODO 15-3-2: 回答形式の指示文に
                「方位・日照・静けさに関する推薦は、比較表の主壁面方位・冬日照・
                標高等の数値を根拠として明示すること」を追記する。

### Step 15-4: サニティチェック・コミット

  - TODO 15-4-1: `tests/sanity_checks.py` に Phase 15 用チェック 4 関数を追加する:
                - `check_phase15_orientation()`: 「南向きの建物」で route="structured" かつ
                  全候補の `wall_ratio_s >= ORIENT_PREFER_MIN` であること。
                - `check_phase15_avoid_west()`: 「西日の当たらない建物」で
                  全候補の `wall_ratio_w <= ORIENT_AVOID_MAX` であること。
                - `check_phase15_sunlight()`: 「日当たりのよい建物」で
                  全候補の `winter_sunlit = True` であること。
                - `check_phase15_exclude()`: 「木造以外の建物」で
                  候補に `structure_type = '木造・土蔵造'` が含まれないこと。
                `run_phase15_checks()` と `--phase15` CLI 分岐を追加する。
  - TODO 15-4-2: `--phase8` 〜 `--phase13` を再実行し回帰がないことを確認する →
                work_log.md 更新 → Step 単位で git commit
                （Step 15-1: `feat(phase15): query_parserに方位・日照・除外条件等を追加`、
                Step 15-2: `feat(phase15): phase10_routerとvector_searchを新フィルタに対応`、
                Step 15-3: `feat(phase15): LLMプロンプト比較表に方位・日照列を追加`、
                Step 15-4: `test(phase15): サニティチェック追加・回帰確認`）。

---

## Phase 16: 効果測定・限界整理（発表素材化）

承認日: 2026-07-19

### Step 16-1: Before/After 効果測定

  - TODO 16-1-1: `pixi run python tests/eval_retrieval.py` を再実行し、
                Phase 14-2 の Before と `geometric` / `robustness` カテゴリの
                recall@10 / precision@10 / hit@1 を Before/After 表で work_log.md に記録する。
                合格基準（Phase 10 に倣う）: `geometric` カテゴリの hit@1 = 1.0。
                未達の場合は原因（閾値のズレ・SQL条件の誤り等）を特定し
                Step 15 に戻って修正する（R-10 に準拠、work_log の不具合ログに記録）。
  - TODO 16-1-2: 看板クエリ「広島駅の近くで日当たりのよい建物」（G34 相当）を
                `hybrid_search()` で実行し、route・候補一覧・生成回答を
                `output/demo_flagship_query.md` に保存する（再現コマンドも併記）。

### Step 16-2: 限界と設計判断の文書化（発表の「難しかったこと」）

  - TODO 16-2-1: `docs/foss4g/limitations.md` を新規作成する。以下 3 分類で整理する
                （各項目「何が難しいか」「今回どう回避/近似したか」を1〜2文で記載）:
                - **①データの限界**: DEM 不使用（地形越しの眺望判定は非対応）、
                  urf_usage・yearOfConstruction の欠損、道路側の浸水属性なし（孤立判定不可）、
                  landmark の学校区分が校種を持たない、生活利便施設（スーパー・保育園等）は
                  データセット外。
                - **②手法上の近似**: 日照は冬至南中高度との角度比較による簡易判定
                  （物理的な日照シミュレーションではない）、体積は底面積×高さの近似
                  （閉多面体でないメッシュのため）、「日当たりのよい」等の擬似ゴールドは
                  定義式に依存し絶対的な正解ではない、埋め込み類似度の密集問題
                  （Phase 11 で確認）は再埋め込み未実施のため構造化経路で迂回している。
                - **③射程外**: ビル風・ヒートアイランド等の流体/熱環境シミュレーション、
                  集計・比較・対話継続ルート（「平均高さは？」「AとBどちらが安全？」）、
                  容積率等の都市計画規制ベースの質問、parse_query() の非決定性
                  （Phase 11 で観測。temperature=0でも解析結果が揺れる場合がある）。
  - TODO 16-2-2: `--phase9` 〜 `--phase15` の全チェックを再実行し最終回帰確認 →
                work_log.md 更新 → `docs(phase16): 限界整理ドキュメントを追加、最終効果測定を記録`
                で git commit する。

---

## Phase 17: レビュー指摘の解消（整合性・精度・可視化の総仕上げ）

承認日: 2026-07-20（ユーザー指示「最大限の力でこれらを解決」により計画→実装まで承認済み）

> **背景（Phase 16 完了後の全体レビューで検出した指摘）:**
> Phase 13〜15 で実装したフィルタ群は「候補を絞り込む」段までは機能しているが、
> 「絞り込んだ理由をユーザーに見せる」経路（LLM 提示カルテ・地図 GeoJSON・
> フロントポップアップ）に新カラムが一切届いていない。また SQL フィルタと
> pandas 検証（verify_candidates）が別実装のままで、Phase 16 で実際に発生した
> 「閾値ズレ」（sunlight 0.2 vs 0.3）と同型の不整合を将来検知できない。
>
> **制約:** 埋め込みの再生成は行わない。DB 内の text_card・embedding は不変とし、
> LLM への新情報提示は build_prompt() が候補 DataFrame から動的生成する
> 「追加情報ブロック」で行う（text_card 凍結の維持）。

### Step 17-1: LLM プロンプトへの新カラム反映（build_prompt 拡張）

  - TODO 17-1-1: `_fmt_storeys(v)` を新設する: NULL/NaN/500以上（9999等の無効値）→「不明」。
                比較表の階数列を `_fmt_plain` から `_fmt_storeys` に差し替える
                （text_card 内の「9999階建て」は DB 凍結のため対象外。limitations.md 記載済み）。
  - TODO 17-1-2: `_fmt_orientation(row)` を「最大方位1つ」から「4方位すべての比率」の
                コンパクト表記（例: `南30/北30/東20/西20`）に変更する。
                検索条件（南向き）とのズレ（僅差で北が最大になる等）の混乱を解消する。
  - TODO 17-1-3: 比較表に「学校まで(m)」「病院まで(m)」「幹線道路まで(m)」
                「木造密度」「突出(m)」の5列を追加する（NULL は既存規則に従い表示）。
  - TODO 17-1-4: 候補ごとの `[追加情報（前計算）]` ブロックを build_prompt 内で
                DataFrame から動的生成し、詳細カルテの直後に付加する:
                最寄り学校/病院/警察署/消防署/郵便局（名称+距離）、幹線道路距離、
                木造密度、突出度、屋根種別、屋根面積。text_card は変更しない。
  - TODO 17-1-5: 回答形式指示に「学校・病院等の施設近接の推薦は追加情報ブロックの
                名称・距離を根拠として示すこと」を追記する。

### Step 17-2: 地図 UI（GeoJSON・フロントエンド）への反映

  - TODO 17-2-1: `phase6_app.py::candidates_to_geojson()` を building_geom_meta /
                building_context_meta との LEFT JOIN に改修し、GeoJSON properties に
                roof_type_est / ground_elev_m / wall_ratio_s / winter_sunlit /
                prominence_m / wooden_density_ratio / nearest_major_road_dist_m /
                nearest_school_name+dist / nearest_hospital_name+dist を追加する。
                テーブル不在時は既存クエリにフォールバックする。
                storeys の無効値（>=500）は None に正規化してから返す。
  - TODO 17-2-2: `frontend/src/map.ts`（ポップアップ）と `frontend/src/chat.ts`
                （候補リスト）に新プロパティの表示を追加する（存在時のみ表示）。
  - TODO 17-2-3: `pixi run build` でフロントエンドを再ビルドし、`src/static/` を更新する。

### Step 17-3: パーサ・ルーターの精度/堅牢性改善

  - TODO 17-3-1: OrientationFilter mode="prefer" を「比率>=0.3」から
                「比率>=0.3 かつ 4方位中最大（優勢方位）」に強化する
                （build_filter_clauses の SQL と verify_candidates の pandas 両方）。
                南30%・北30%の建物が「南向き」と「北向き」の両方にヒットする問題を解消。
                ゴールドセットに prefer 依存クエリはないため評価への影響なし。
  - TODO 17-3-2: `parse_query()` に後処理バリデーションを追加する:
                usage_include ∩ usage_exclude / structure_type ∈ structure_exclude の
                矛盾を検出したら exclude 側から除去し WARN を print する。
  - TODO 17-3-3: `slenderness` を _SORT_KEYS / COLUMN_SOURCE に追加し、
                プロンプトの sort_by ルールに「細長い建物」→ slenderness desc、
                「体積が大きい」→ volume_m3 desc、「最も階数が多い」→ storeys desc を明記する。
  - TODO 17-3-4: `vector_search()` の has_geom_meta / has_context_meta 判定を
                プロセス内キャッシュ化する（モジュール変数。接続ごとの
                information_schema 問い合わせを初回のみに削減）。
  - TODO 17-3-5: `tests/gold_set.py` の G34 から座標ハードコードを除去する。
                gold_sql に `{STATION_X}` / `{STATION_Y}` プレースホルダを置き、
                `build_gold()` 実行時に geocode('広島駅') + ST_Transform で動的計算して
                埋め込む（geocoder のデータ更新に追従する）。

### Step 17-4: SQL×pandas 同値性チェックの自動化（サニティ拡充）

  - TODO 17-4-1: `check_phase17_sql_verify_consistency()` を実装する:
                代表的な ParsedQuery 9種（orientation prefer/avoid・sunlight・quiet・
                vertical_evacuation・roof_type・wooden_dense・storeys範囲・
                usage_exclude）について、(a) build_filter_clauses による SQL 全件
                フィルタの結果 id 集合と、(b) 全 2,958 件に verify_candidates を
                適用した残存 id 集合が**完全一致**することを確認する。
                LLM API を一切呼ばない（ParsedQuery 直接構築）。
                Phase 16 で実際に起きた「SQL と検証の閾値ズレ」を構造的に検知する仕組み。
  - TODO 17-4-2: quiet / vertical_evacuation / roof_type / wooden_dense / storeys 範囲の
                個別動作チェック（ParsedQuery 直接構築 + vector_search、API不要）を追加する。
  - TODO 17-4-3: `run_phase17_checks()` と `--phase17` CLI 分岐を追加し、
                `--phase13` `--phase15` の回帰確認も行う。

### Step 17-5: 評価・最終確認

  - TODO 17-5-1: `tests/eval_retrieval.py` に `--ids G21,G23` 形式の部分実行
                オプションを追加する（API クォータ節約・回帰確認の高速化）。
  - TODO 17-5-2: `build_gold()` を再実行し、G34 の動的座標化後も gold_ids が
                従来と一致することを確認する（座標値は同一のはずのため件数不変）。
  - TODO 17-5-3: 方位まわりの変更影響を受けるクエリ（G21/G22/G23/G34）を
                `--ids` 部分評価で再実行し、回帰がないことを確認する。
  - TODO 17-5-4: 看板クエリを回答生成込みで1回実行し、追加情報ブロック・
                新比較表列が回答の根拠として引用されることを目視確認する。
  - TODO 17-5-5: `docs/foss4g/limitations.md` を更新する（解消した項目:
                storeys 表示・フロント未反映 → 解消済みと注記 or 削除）。
  - TODO 17-5-6: work_log.md 更新 → Step 単位で git commit。

---

## Phase 18: 回答提示とマップ表現の改善

> **背景:** 看板クエリ「where is the tallest building around the Hiroshima sta.」の
> 実行画面レビューで判明した 5 件の課題に対応する。
> 「推薦IDが候補リストに見当たらない」「順位が不自然」は、
> `candidates_to_geojson()` がランキング順を落としていることに起因する同一原因。
>
> **地図表現の方針（A + B + C を採用）:**
> - **A** データ出典・整備時点の注記を常時表示（Step 18-4）
> - **B** 背景 OpenFreeMap/OSM の建物レイヤーを非表示化（Step 18-5）
> - **C** PLATEAU 建物を `measured_height` で 3D 押し出し表示（Step 18-5）
>
> A のみでは「回答が最も高いと言った建物の隣に、背景OSMのより高いビルが
> 描かれる」という**画面上の自己矛盾**が残るため B を採用。
> さらに高さ・方位・日照を推論軸とする本システムでは、高さを平面塗りで
> 表現するのは根拠の可視化を放棄しているため C を採用する。
>
> **事前検証済み（Phase 18 着手前に DB で確認）:**
> - `building_chunks.geometry` は MULTIPOLYGON Z だが **1建物=1パート・全件 zmax=0**
>   → LOD2 の壁面サーフェス集合ではなく平坦なフットプリント。
>     `fill-extrusion` の土台としてそのまま使える。
> - `measured_height` は 2,958 件中 **2,954 件が有効**（中央値 15.1m / 最大 164.4m）、
>   無効値（-9999）は 4 件のみ → クランプ処理のみで足りる。
>
> **設計上の依存関係（重要）:** C を採用すると `fill-extrusion` には outline が
> 存在しないため、現行の `buildings-outline` / `buildings-highlight` レイヤーが
> 機能しなくなる。したがって**「推薦建物の強調表示」は 2D レイヤー追加ではなく
> 3D の色分けとして実装する**。Step 18-2（リストUI）と Step 18-5（地図）で
> 強調表示の設計を分断しないこと。

### Step 18-1: 候補順序バグの修正（最優先）

  - TODO 18-1-1: `src/phase6_app.py::candidates_to_geojson()` の feature 生成
                （現 152〜173 行）を、候補 DataFrame のランキング順に並べ替える。
                `WHERE b.id IN (...)` は DuckDB のスキャン順で返るため、
                現状は GeoJSON の feature 順＝DB 物理行順になっている。
                実装方針（SQL に ORDER BY を足すのではなく Python 側で並べ直す）:
                  1. 既存ループで作った feature を `feat_map: dict[str, dict]` に格納する
                     （キーは `rec["id"]`）。
                  2. 最後に `features = [feat_map[i] for i in ids if i in feat_map]`
                     として `ids`（= `candidates["id"].tolist()`、134 行で取得済み）の
                     順に再構築して返す。
                  3. geometry が None で skip されたレコードは `feat_map` に入らないため、
                     `if i in feat_map` で安全に除外される（既存挙動を維持）。
                  4. properties に順位 `rank`（1始まりの int）を追加する。
                     フロント側で「DBの並び」ではなく「検索順位」であることを
                     明示するために使う。
  - TODO 18-1-2: 同関数のシグネチャを
                `candidates_to_geojson(candidates, recommended_ids: list[str] | None = None)`
                に拡張し、properties に `is_recommended: bool` を付与する
                （`recommended_ids` が None のときは全件 False）。
                **MapLibre の paint 式は JS の配列を動的に参照できないため、
                推薦フラグはサーバ側で feature に埋め込むのが最も単純**という判断。
                Step 18-5 の 3D 色分けがこのフラグを直接読む。
  - TODO 18-1-3: `tests/sanity_checks.py` に `check_phase18_geojson_order()` を追加する。
                LLM API を一切呼ばない構成とする:
                  1. `building_chunks` から任意の 10 件の id を取得し、
                     Python 側でシャッフルした順序の `pd.DataFrame({"id": ids, "score": ...})`
                     を作る。
                  2. `candidates_to_geojson(df)` を呼び、
                     `[f["properties"]["id"] for f in result["features"]]` が
                     入力 `ids` と**完全一致（順序込み）**することを assert する。
                  3. `properties["rank"]` が 1..N の連番であることを assert する。
                  4. シャッフルを 3 パターン試し、すべてで一致することを確認する
                     （偶然一致による見逃し防止）。
                  5. `recommended_ids` に 2 件渡したとき、その 2 件だけ
                     `is_recommended == True` になることを assert する。
  - TODO 18-1-4: `run_phase18_checks()` と `--phase18` CLI 分岐を
                `tests/sanity_checks.py`（現 1386 行以降の分岐群）に追加する。

### Step 18-2: 推薦建物の抽出と候補リストUI

  - TODO 18-2-1: `src/phase6_app.py` に推薦建物IDの抽出処理を追加する。
                LLM 回答本文（`result["answer"]`）から建物IDを正規表現
                `bldg_[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}`
                で抽出し、
                  - 出現順を保ったまま重複排除する（`dict.fromkeys` を使用）
                  - 候補 id 集合との積集合を取る（回答が幻覚したIDを除外）
                として `recommended_ids: list[str]` を得る。
                純粋関数 `extract_recommended_ids(answer, ids)` として切り出す。
  - TODO 18-2-2: `/api/search` エンドポイントの処理順を
                **「回答生成 → 推薦ID抽出 → `candidates_to_geojson(candidates, recommended_ids)`」**
                に組み替える（現状は回答生成後に GeoJSON 変換しているため順序変更は不要だが、
                `recommended_ids` を変換前に確定させる必要がある）。
                `SearchResponse` に `recommended_ids: list[str] = []` を追加して返す。
  - TODO 18-2-3: `frontend/src/api.ts` の `SearchResponse` 型と
                `frontend/src/store.ts` の `Message` インターフェースに
                `recommendedIds?: string[]` を追加し、`main.ts` の
                レスポンス→Message 変換で値を渡す。
                （地図側は feature の `is_recommended` を直接読むため、
                この配列はリストUIの並べ替えとバッジ判定にのみ使う）
  - TODO 18-2-4: `frontend/src/chat.ts::_buildingListHtml()` を改修する。
                  1. 引数に `recommendedIds: string[]` を追加する
                     （`appendAssistantMessage` から渡す。現 66 行付近の呼び出しを更新）。
                  2. 推薦建物の li 要素に `building-item--recommended` クラスと
                     「★ 推薦」バッジ（`span.rec-badge`）を付与する。
                  3. 表示順は「推薦建物 → 残りをランク順」とし、
                     `building-item__rank` には元の順位（`properties.rank`）を表示する。
                     並べ替えても番号が検索順位を指すようにする。
                  4. `aria-label` に「推薦建物」を含める。
                  5. `frontend/src/style.css`（候補建物リスト節・現 264 行付近）に
                     `.building-item--recommended`（`border-color: var(--accent)` +
                     薄い背景）と `.rec-badge` のスタイルを追加する。
                     配色は既存 CSS 変数のみを使い、新規色を定義しない。
  - TODO 18-2-5: 「さらに N 件…」ボタン（`chat.ts` 現 152 行、
                `.building-list__more`）に click ハンドラを実装する。
                現状 CSS のみでハンドラ未実装のため押しても何も起きない。
                  1. `_buildingListHtml()` で全件の li を出力し、
                     6 件目以降に `hidden` 属性を付ける方式にする。
                  2. クリックで `hidden` を外し、ボタン文言を
                     「折りたたむ」にトグルする（再クリックで元に戻る）。
                  3. `aria-expanded` を同期させる。
                  4. 展開後に表示された li にも、既存のホバー連動リスナ
                     （mouseenter / focus / click → `highlightBuilding`）が
                     効くようにする。イベント登録を ul への委譲に変更するか、
                     展開時に再登録するかは実装者判断でよいが、
                     **展開した項目でも地図ハイライトが動くこと**を必ず確認する。
  - TODO 18-2-6: `tests/sanity_checks.py` に `check_phase18_recommended_ids()` を追加する。
                `extract_recommended_ids()` に対し、
                  (a) 回答本文に複数IDが登場するケースで出現順・重複排除が正しいこと、
                  (b) 候補にないID（幻覚）が除外されること、
                  (c) IDが1件も含まれない回答で空配列が返ること
                を assert する（固定文字列でテスト、API 不要）。

### Step 18-3: Markdown レンダリング

  - TODO 18-3-1: `marked` と `dompurify` を frontend に追加する。
                インストール前に `anthropic-skills:supply-chain-audit` の手順に従い、
                `npm install --dry-run` と依存ツリー・既知脆弱性を確認してから実行する。
                実行コマンドは
                `"C:/Program Files/nodejs/npm.cmd" --prefix frontend install marked dompurify`
                （`pixi.toml` の dev/build タスクと同じ npm を使う。
                dompurify は v3 以降で型定義を同梱するため `@types/dompurify` は不要）。
  - TODO 18-3-2: `frontend/src/chat.ts` の AI 回答バブル（現 66 行、
                `msg__bubble` に `_esc(msg.content)` を入れている箇所）を
                Markdown レンダリングに差し替える。
                  1. `_renderMarkdown(md: string): string` を新設し、
                     `DOMPurify.sanitize(marked.parse(md, { async: false }) as string)` を返す。
                  2. `marked` の設定は `gfm: true, breaks: true`（表とソフト改行に対応）。
                  3. **ユーザーメッセージ・エラーメッセージは `_esc` のままとする**
                     （Markdown 化する必要がなく、攻撃面を広げないため）。
                  4. `_esc` は候補リストの属性値生成でも使っているため削除しない。
  - TODO 18-3-3: `frontend/src/style.css` に `.msg__bubble` 配下の
                Markdown 要素スタイルを追加する。
                対象: h1〜h4（サイズを本文比 1.0〜1.3 倍に抑える）、ul / ol（左パディング）、
                strong、code / pre（等幅・背景 `var(--bg-base)`）、hr、
                table（`border-collapse: collapse`・セル境界 `var(--border)`・
                ヘッダ背景 `var(--bg-surface)`・`font-size: 12px`）。
                **比較表は列数が多いため、table を `overflow-x: auto` の
                ラッパで包んで横スクロールさせ、チャットパネル自体が
                横スクロールしないようにする**（現在フッターに横スクロールバーが
                出ている問題の再発防止）。
                新規の色は定義せず既存 CSS 変数のみを使い、ライト/ダーク両テーマで確認する。

### Step 18-4: データ出典・整備時点の明示（方針A）

  - TODO 18-4-1: 背景地図（OpenFreeMap/OSM = 現況）と PLATEAU 建物（整備時点の
                スナップショット）の差異を明示する注記を地図パネルに常時表示する。
                `frontend/index.html` の `.map-overlay`（現 60〜72 行、
                件数表示と閉じるボタンがある領域）に
                `id="map-attribution" class="map-attribution"` の span を追加する。
                **Step 18-5 で背景の建物を消すため、文面は「差異の言い訳」ではなく
                「表示されている建物が何か」の説明にする:**
                「建物: PLATEAU 3D都市モデル（整備時点）／背景地図: OpenStreetMap。
                　整備後の新築建物は表示・検索対象に含まれません。」
                **PLATEAU 広島市データの整備年度が `docs/specification.pdf` または
                元 GPKG のメタデータから特定できた場合は「PLATEAU（YYYY年度整備）」と
                年次を明記する。特定できない場合は年次を書かず「整備時点」のままとする
                （推測で書かない）。**
  - TODO 18-4-2: `frontend/src/style.css` に `.map-attribution` を追加する。
                `font-size: 11px; color: var(--text-muted); line-height: 1.4;`
                とし、モバイル幅（`.map-overlay` の既存メディアクエリに合わせる）では
                2行折り返しを許容する。閉じるボタン・件数表示と重ならないよう
                `.map-overlay` を `flex-wrap: wrap` にする。
  - TODO 18-4-3: 同趣旨の 1 行注記を、チャット初期表示の
                ウェルカムメッセージ（`index.html` の `#welcome-msg`）にも追加する。
                地図を開かないユーザーにも制約が伝わるようにする。

### Step 18-5: 地図の 3D 化と背景建物の抑制（方針 B + C）

> Step 18-2 の推薦強調表示は、このステップの 3D 色分けで実現する。
> 2D の `buildings-highlight` レイヤーを新設してはならない。

  - TODO 18-5-1: **【B】** `frontend/src/map.ts` に `_hideBasemapBuildings()` を新設する。
                OpenFreeMap の建物レイヤー ID は liberty / dark でスタイル定義が
                異なるため **ID の直書きは禁止**。
                  1. `map.getStyle().layers` を走査し、
                     `(l as any)['source-layer'] === 'building'` に該当するレイヤーを収集する。
                  2. 各レイヤーに `map.setLayoutProperty(l.id, 'visibility', 'none')` を適用する。
                  3. 該当が 0 件だった場合は `console.warn` を出す
                     （スタイル側の仕様変更を検知するため。例外は投げない）。
  - TODO 18-5-2: **【B】** `_hideBasemapBuildings()` の呼び出し箇所を 2 つ用意する。
                  1. `initMap()` の `map.on('load')` 内。
                  2. `applyMapTheme()` の `map.once('styledata')` 内
                     — `setStyle()` でスタイルが差し替わると非表示設定は失われるため、
                     **テーマ切替のたびに再適用が必須**。既存の GeoJSON 再セット処理と
                     同じブロックで呼ぶ。
  - TODO 18-5-3: **【C】** `initMap()` の Map 初期化オプションに `pitch: 45` を追加し、
                `NavigationControl` を `{ visualizePitch: true }` で生成する
                （ユーザーがピッチ・ベアリングを操作・把握できるようにする）。
  - TODO 18-5-4: **【C】** GeoJSON ソースを `promoteId: 'id'` 付きで追加するよう
                `setGeojson()` / `_addBuildingLayers()` を修正する。
                ホバー強調を `setFeatureState` で行うために必要
                （`fill-extrusion-opacity` はデータ駆動に対応しないため、
                ホバーもフィルタではなく**色**で表現する）。
  - TODO 18-5-5: **【C】** `_addBuildingLayers()` を書き換える。
                既存の `buildings-fill`（fill）・`buildings-outline`（line）・
                `buildings-highlight`（fill）の 3 レイヤーを廃止し、
                `buildings-3d`（type: `fill-extrusion`）1 枚に統合する。
                paint は以下:
                  - `fill-extrusion-height`:
                    `['max', ['coalesce', ['get', 'measured_height'], 3], 3]`
                    — 無効値（-9999）4 件と NULL を最低 3m にクランプし、
                      地面に潰れて見えなくなるのを防ぐ。
                  - `fill-extrusion-base`: 0
                  - `fill-extrusion-opacity`: 0.85
                  - `fill-extrusion-color`: `case` 式を**この優先順**で構成する。
                      1. ホバー中（`['boolean', ['feature-state', 'hover'], false]`）→ `#ffeb3b`
                         （現行 `buildings-highlight` の色を踏襲）
                      2. 推薦建物（`['get', 'is_recommended']`）→ アクセント色
                      3. 以降は**現行の高潮リスク3段階の色分けをそのまま維持**
                         （`ht_depth_max >= 2.0` → `#c62828`、`>= 0.5` → `#f57c00`、
                          それ以外 → `#2e7d32`）。リスクの色意味を壊さないこと。
  - TODO 18-5-6: **【C】** アクセント色はテーマごとに定数として `map.ts` に持つ
                （MapLibre の paint 式は CSS 変数を解決できないため）。
                `style.css` の定義と一致させる: ライト `#1565c0` / ダーク `#90caf9`。
                `applyMapTheme()` でテーマが変わったら
                `map.setPaintProperty('buildings-3d', 'fill-extrusion-color', ...)` で
                式を再設定する。**色の二重管理になるため、`map.ts` 側に
                「style.css の --accent と同値。変更時は両方直すこと」のコメントを必ず残す。**
  - TODO 18-5-7: **【C】** `highlightBuilding(id)` の実装を
                `setFilter` から `setFeatureState` 方式に置き換える。
                  1. モジュール変数 `hoveredId: string | null` を保持する。
                  2. 直前のホバー対象に `{ hover: false }`、新しい対象に `{ hover: true }` を
                     `map.setFeatureState({ source: SOURCE_ID, id }, ...)` で設定する。
                  3. `id` が null のときは解除のみ行う。
                  4. **呼び出し側（`chat.ts` のホバー連動）のシグネチャは変更しない**
                     ため、Step 18-2-5 の実装と衝突しない。
  - TODO 18-5-8: **【C】** イベントハンドラのレイヤー参照を
                `LAYER_FILL` から `buildings-3d` に付け替える
                （`map.on('click', ...)` / `mouseenter` / `mouseleave`、現 39〜50 行）。
  - TODO 18-5-9: **【C】** `_showPopup()` に推薦建物の表示を追加する。
                `properties.is_recommended` が true のとき、ポップアップ先頭に
                「★ AI 推薦」の行を出す。
  - TODO 18-5-10: **【C】** `setGeojson()` の `fitBounds` を 3D 表示に合わせて調整する。
                `pitch` を維持したまま `padding` を上方向に厚く取り
                （例 `{ top: 120, bottom: 60, left: 60, right: 60 }`）、
                高層建物が画面上端で見切れないようにする。
                `maxZoom: 16` は据え置きでよい。
  - TODO 18-5-11: 3D 化により候補建物が背景に埋もれないことを、ライト/ダーク
                両テーマで確認する。埋もれる場合のみ
                `fill-extrusion-opacity` を 0.9 まで上げて調整する
                （**新規の色は増やさない**）。

### Step 18-6: プロンプト調整

  - TODO 18-6-1: `src/phase4_retrieval.py::build_prompt()`（現 481 行〜）の
                【回答形式】に以下を追記し、ロールプロンプトの復唱を抑制する。
                  - 「『広島市の都市計画・防災アドバイザーとして』のような前置き・
                    自己紹介・質問文の復唱は書かず、推薦内容から直接始めること」
                  - 「見出しは 2 レベル以下（`##` 以降）を使い、最上位見出し（`#`）は
                    使わないこと」（チャットバブル内で巨大化するのを防ぐ）
                システムロール文（「あなたは広島市の都市計画・防災アドバイザーです。」）
                自体は回答品質の基盤なので**削除しない**。
  - TODO 18-6-2: 同じく【回答形式】の推薦件数指定を、クエリ種別に応じて可変にする。
                `build_prompt()` に引数 `sort_by: SortSpec | None = None` を追加し
                （`hybrid_search` から `parsed_query.sort_by` を渡す）、
                  - `sort_by` が指定されている場合（「最も高い」等の最上級クエリ）:
                    「推薦する建物は**1件**とし、次点を最大2件まで
                    『比較のための次点』として簡潔に併記すること」
                  - `sort_by` が None の場合: 従来どおり「最大 5 件」
                とする。既存の呼び出し元（引数なし）は従来動作を維持する。
  - TODO 18-6-3: 比較表の先頭列 `No.` を「検索順位」であると明示する
                （ヘッダを `順位` に変更し、`sort_by` 指定時は
                「この表は指定順に並んでいます」の 1 文を表の直前に出す）。
                TODO 18-1-1 で GeoJSON に付けた `rank` と番号が一致することになる。

### Step 18-7: ビルド・検証・記録

  - TODO 18-7-1: `pixi run build` でフロントエンドを再ビルドし、`src/static/` を更新する。
                （`/c/Users/pikkarin/AppData/Local/pixi/bin/pixi.exe run build`）
  - TODO 18-7-2: `pixi run python tests/sanity_checks.py --phase18` を実行し全項目パスを確認する。
                併せて `--phase17` を再実行して回帰がないことを確認する。
  - TODO 18-7-3: `pixi run app` でアプリを起動し、看板クエリ
                「where is the tallest building around the Hiroshima sta.」を実行して
                以下を目視確認する:
                  (a) 候補リスト 1 位＝回答が推薦した建物IDであること
                  (b) ★推薦バッジが付き、地図でもアクセント色で強調されること
                  (c) 「さらに N 件」で残りが展開され、地図ハイライトも動くこと
                  (d) Markdown（見出し・箇条書き・表）が装飾されて表示されること
                  (e) 回答が「〜として」の前置きから始まらないこと
                  (f) 地図に出典・整備時点の注記が表示されること
                  (g) チャットパネルに横スクロールバーが出ないこと
                  (h) **背景 OSM の建物が消え、PLATEAU 建物のみが 3D で立ち上がること**
                  (i) **推薦された建物が周囲より明らかに高く見え、回答の
                      「最も高い」という主張と画面が矛盾しないこと**
  - TODO 18-7-4: **テーマ切替（☀/☽ ボタン）を押した直後に (h) と推薦色が
                維持されることを確認する。** `setStyle()` 後の再適用漏れは
                このフェーズで最も起きやすいバグ。
  - TODO 18-7-5: 日本語クエリ（例「高潮リスクが低く駅から近い建物は？」）でも
                (a)〜(i) が成立することを確認する（英語クエリ固有の問題でないこと）。
                特に**高潮リスクの3色分けが 3D 化後も維持されている**ことを確認する。
  - TODO 18-7-6: `docs/work_log.md` を Step 単位で更新し、
                Step ごとに git commit する（1 Step = 1 commit）。

---

## Phase 19: 地図配色のクエリ連動動的化（方針C、フォールバックとして方針A内蔵）

> **背景:** Phase 18 の 3D 地図は、常に高潮浸水リスク（`ht_depth_max`）固定の
> 3 段階配色（🟩🟧🟥）で塗られていた。しかしアプリの目的はリスクに限らず
> 方位・日照・静けさ・周辺施設距離など多数の軸を自由に検索することであり、
> 「日当たりの良い建物は？」と聞いても無関係な高潮色で塗られるのは
> 目的と噛み合っていない。さらに旧閾値（0.5m/2.0m）は PLATEAU 公式の
> 高潮ランクコードリスト（`HighTideRiskAttribute_rank`: 1=0.5m未満,
> 2=0.5〜3m未満, 3=3〜5m未満, 4=5〜10m未満, 5=10〜20m未満, 6=20m以上）と
> 無関係な独自閾値だった。
>
> 本フェーズでは、`ParsedQuery`（バックエンドが既に `/api/search` の
> `parsed_query` として返している）から**そのクエリが実際に問うた属性**を
> 優先順位で1つ選び、それに応じて地図の塗り分け対象・凡例を動的に切り替える
> （方針C）。該当する属性が1つも見つからない場合（意味検索のみのクエリ等）は
> 自動的に単色の中立表示（方針A）にフォールバックする。**バックエンド側の
> 変更は不要**（`parsed_query` は Phase 8 から既に `SearchResponse` に
> 含まれている）。候補リストのバッジ動的化は別タスク（前回合意済み、対象外）。

### 配色パレット（新規に固定する色。理由: MapLibre の paint 式は CSS 変数を
参照できないため、既存の `ACCENT_COLOR`/`HOVER_COLOR` と同様に定数で持つ
必要がある。他の意味（リスク・推薦・ホバー）と混同しないよう色相を分ける）

| 用途 | 色 | 備考 |
|---|---|---|
| リスク3段階（🟩） | `#2e7d32` | 既存踏襲 |
| リスク3段階（🟧） | `#f57c00` | 既存踏襲 |
| リスク3段階（🟥） | `#c62828` | 既存踏襲。**閾値のみ変更**（後述） |
| 汎用グラデーション 低 | `#b2dfdb` | ティール系。リスク/推薦/ホバーと色相が被らない |
| 汎用グラデーション 高 | `#00695c` | 同上 |
| 日照 確保 | `#ffb300` | アンバー |
| 日照 未確保 | `#9e9e9e` | グレー |
| 屋根 陸屋根 | `#5c6bc0` | インディゴ |
| 屋根 勾配屋根 | `#8d6e63` | ブラウン |
| 中立（方針A・データ欠損時の共通フォールバック） | `#78909c` | ブルーグレー |
| 推薦（既存 `ACCENT_COLOR`）・ホバー（既存 `HOVER_COLOR`） | 変更なし | 常に最優先で上書き |

### Step 19-1: ParsedQuery のフロントエンドへの型付け・伝搬

  - TODO 19-1-1: `frontend/src/api.ts` に `ParsedQueryDto` インターフェースを
                追加する。`src/phase4_retrieval.py`（637行目 `hybrid_search()`
                内 704〜728行目）の `parsed_query_dict` と**キー名・型を1対1で
                一致**させること（バックエンド変更なしで直接デシリアライズする
                ため）。
                ```ts
                export interface RiskFilterDto { hazard: 'ht' | 'rv' | 'ts'; mode: string; max_depth_m: number | null; }
                export interface DistanceFilterDto { target: string; max_dist_m: number; }
                export interface SortSpecDto { key: string; order: 'asc' | 'desc'; }
                export interface OrientationFilterDto { direction: 'n' | 'e' | 's' | 'w'; mode: string; }

                export interface ParsedQueryDto {
                  location_name: string | null;
                  radius_m: number;
                  height_min: number | null;
                  usage_include: string[];
                  structure_type: string | null;
                  sort_by_height: boolean;
                  clarification_question: string | null;
                  risk_filters: RiskFilterDto[];
                  distance_filters: DistanceFilterDto[];
                  fire_proof: string | null;
                  sort_by: SortSpecDto | null;
                  semantic_residual: string;
                  orientation_filters: OrientationFilterDto[];
                  sunlight: boolean | null;
                  quiet: boolean | null;
                  vertical_evacuation: boolean | null;
                  height_max: number | null;
                  storeys_min: number | null;
                  storeys_max: number | null;
                  usage_exclude: string[];
                  structure_exclude: string[];
                  roof_type: string | null;
                  wooden_dense: boolean | null;
                }
                ```
                `SearchResponse` インターフェース（現 12〜19行目）に
                `parsed_query: ParsedQueryDto | null;` を追加する。
  - TODO 19-1-2: `frontend/src/store.ts` を更新する。
                  - `Message` インターフェース（現3〜11行目）に
                    `parsedQuery?: ParsedQueryDto | null;` を追加する
                    （`./api` から `ParsedQueryDto` を import）。
                  - `AppState` インターフェース（現20〜28行目）に
                    `activeParsedQuery: ParsedQueryDto | null;` を追加する。
                  - `Store` の初期状態（現33〜41行目）に
                    `activeParsedQuery: null,` を追加する。
  - TODO 19-1-3: `frontend/src/main.ts` を更新する。
                  - `openMap()`（現40行目）のシグネチャを
                    `function openMap(geojson: GeoJSON.FeatureCollection, parsedQuery: ParsedQueryDto | null): void`
                    に変更し、`store.set({ activeGeojson: geojson, isMapVisible: true })`
                    （現41行目）に `activeParsedQuery: parsedQuery` を追加する。
                    `setGeojson(geojson)`（現55行目）呼び出しに
                    `setGeojson(geojson, parsedQuery)` として引数を渡す
                    （Step 19-3 で `setGeojson` のシグネチャを変更する）。
                  - `runSearch()` 内の `msg` オブジェクト（現175行目）に
                    `parsedQuery: result.parsed_query ?? null,` を追加する。
                  - `appendAssistantMessage(msg, openMap)`（現186行目）は
                    `onMapOpen` の型変更（Step 19-1-4）に伴い、
                    `openMap` 自体のシグネチャが2引数になるためそのまま渡せる
                    （chat.ts 側で `msg.parsedQuery` を補って呼ぶため、
                    main.ts 側の変更は不要）。
                  - 自動オープン呼び出し（現190行目）
                    `openMap(result.geojson)` を
                    `openMap(result.geojson, result.parsed_query ?? null)` に変更する。
  - TODO 19-1-4: `frontend/src/chat.ts` を更新する。
                  - `appendAssistantMessage` の `onMapOpen` 引数型（現54行目）を
                    `(geojson: GeoJSON.FeatureCollection, parsedQuery: import('./api').ParsedQueryDto | null) => void`
                    に変更する。
                  - 地図ボタンのクリックハンドラ（現93行目）
                    `onMapOpen(geojson)` を
                    `onMapOpen(geojson, msg.parsedQuery ?? null)` に変更する。
                  - 候補リスト項目のクリックハンドラ（現105行目）
                    `onMapOpen(msg.geojson!)` を
                    `onMapOpen(msg.geojson!, msg.parsedQuery ?? null)` に変更する。

### Step 19-2: 動的配色ロジック（新規ファイル）

  - TODO 19-2-1: `frontend/src/mapColor.ts` を新規作成する。
                MapLibre（`maplibregl` import）と `ParsedQueryDto`（`./api`）
                のみに依存する純粋関数群とし、DOM 操作は行わない
                （map.ts から呼ばれる薄いロジック層として分離し、
                map.ts の肥大化を防ぐ）。
  - TODO 19-2-2: `ColorSpec` 型を定義する。
                ```ts
                export type ColorMode =
                  | 'risk' | 'gradient' | 'derived-margin'
                  | 'boolean-sunlight' | 'categorical-roof' | 'neutral';

                export interface ColorSpec {
                  mode: ColorMode;
                  key?: string;              // gradient/risk が参照するプロパティ名
                  domain?: [number, number]; // gradient/derived-margin のみ
                  legendText: string;        // 地図オーバーレイに表示する説明文
                }
                ```
  - TODO 19-2-3: ドメイン計算ヘルパー `_domain()` を実装する。
                ```ts
                function _domain(
                  features: GeoJSON.Feature[],
                  getter: (p: Record<string, unknown>) => number | null,
                ): [number, number] {
                  let min = Infinity, max = -Infinity;
                  for (const f of features) {
                    const v = getter((f.properties ?? {}) as Record<string, unknown>);
                    if (v == null || Number.isNaN(v)) continue;
                    if (v < min) min = v;
                    if (v > max) max = v;
                  }
                  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
                  // MapLibre の interpolate は stop 値が狭義単調増加である必要があるため、
                  // 全件同値（min===max）の場合は max 側を +1 して回避する。
                  if (max <= min) max = min + 1;
                  return [min, max];
                }
                ```
  - TODO 19-2-4: 避難余裕高さの導出関数（MapLibre 式と JS 側で**同じ計算式を
                二重実装**する。ズレを防ぐため、コメントで互いを参照させること）。
                ```ts
                // mlExprForMargin() の case/coalesce/max と必ず同じロジックに保つこと
                function _evacMarginJs(p: Record<string, unknown>): number {
                  const h = p['measured_height'] != null ? Number(p['measured_height']) : 0;
                  const depths = ['ht_depth_max', 'rv_depth_max', 'ts_depth_max']
                    .map(k => (p[k] != null ? Number(p[k]) : 0));
                  return h - Math.max(...depths);
                }
                ```
  - TODO 19-2-5: ラベル辞書と整形ヘルパーを定義する。
                ```ts
                const HAZARD_LABEL: Record<string, string> = { ht: '高潮', rv: '洪水', ts: '津波' };
                const DIR_LABEL: Record<string, string> = { n: '北', e: '東', s: '南', w: '西' };
                const FACILITY_LABEL: Record<string, string> = {
                  station: '駅', shelter: '避難所', park: '公園', emroute: '緊急輸送道路',
                  landmark: 'ランドマーク', school: '学校', hospital: '病院',
                  police: '警察署', fire: '消防署', post: '郵便局',
                };
                const SORT_KEY_LABEL: Record<string, { label: string; unit: string }> = {
                  measured_height:   { label: '建物高さ', unit: 'm' },
                  storeys:           { label: '階数', unit: '階' },
                  ground_elev_m:     { label: '地面標高', unit: 'm' },
                  prominence_m:      { label: '周囲との高低差（突出度）', unit: 'm' },
                  roof_area_m2:      { label: '屋根面積', unit: 'm2' },
                  volume_m3:         { label: '建物体積', unit: 'm3' },
                  footprint_area_m2: { label: '敷地（底面積）', unit: 'm2' },
                  slenderness:       { label: '細長さ指数', unit: '' },
                };
                function _sortKeyLabel(key: string): { label: string; unit: string } {
                  if (SORT_KEY_LABEL[key]) return SORT_KEY_LABEL[key];
                  const m = /^nearest_(\w+)_dist_m$/.exec(key);
                  if (m) return { label: `${FACILITY_LABEL[m[1]] ?? m[1]}までの距離`, unit: 'm' };
                  return { label: key, unit: '' };  // 未知キーの保険（将来カラム追加時）
                }
                function _fmt(n: number): string {
                  const r = Math.round(n * 10) / 10;
                  return Number.isInteger(r) ? String(r) : r.toFixed(1);
                }
                ```
  - TODO 19-2-6: `determineColorSpec(pq, features)` を優先順位テーブルの通りに
                実装する。**この順序を変更しないこと**（上位ほど「クエリが
                明示的に問うた具体的条件」、下位ほど「補助的なソート指定」の
                優先度になっている）。
                ```ts
                export function determineColorSpec(
                  pq: ParsedQueryDto | null,
                  features: GeoJSON.Feature[],
                ): ColorSpec {
                  const NEUTRAL: ColorSpec = {
                    mode: 'neutral',
                    legendText: '色分けなし（推薦建物のみアクセント色で強調表示）',
                  };
                  if (!pq) return NEUTRAL;

                  // 1. リスク条件（risk_filters優先、なければ sort_by が *_depth_max）
                  const riskFromFilters = pq.risk_filters[0]?.hazard;
                  const riskFromSort = /^(ht|rv|ts)_depth_max$/
                    .exec(pq.sort_by?.key ?? '')?.[1] as 'ht' | 'rv' | 'ts' | undefined;
                  const hazard = riskFromFilters ?? riskFromSort;
                  if (hazard) {
                    return {
                      mode: 'risk',
                      key: `${hazard}_depth_max`,
                      legendText: `色: ${HAZARD_LABEL[hazard]}浸水リスク（🟩0.5m未満 🟧0.5〜5m未満 🟥5m以上）`,
                    };
                  }

                  // 2. sort_by（リスク以外）→ 汎用グラデーション
                  if (pq.sort_by?.key) {
                    const key = pq.sort_by.key;
                    const { label, unit } = _sortKeyLabel(key);
                    const domain = _domain(features, p => (p[key] != null ? Number(p[key]) : null));
                    return {
                      mode: 'gradient', key, domain,
                      legendText: `色: ${label}（${_fmt(domain[0])}${unit}〜${_fmt(domain[1])}${unit}）`,
                    };
                  }

                  // 3. 方位フィルタ
                  if (pq.orientation_filters.length > 0) {
                    const dir = pq.orientation_filters[0].direction;
                    return {
                      mode: 'gradient', key: `wall_ratio_${dir}`, domain: [0, 1],
                      legendText: `色: ${DIR_LABEL[dir]}向き壁面の比率（薄い=低い 濃い=高い）`,
                    };
                  }

                  // 4. 日当たり
                  if (pq.sunlight === true) {
                    return { mode: 'boolean-sunlight', legendText: '色: 冬の日当たり確保（🟡確保 ⬜未確保）' };
                  }

                  // 5. 静けさ
                  if (pq.quiet === true) {
                    const domain = _domain(features, p =>
                      (p['nearest_major_road_dist_m'] != null ? Number(p['nearest_major_road_dist_m']) : null));
                    return {
                      mode: 'gradient', key: 'nearest_major_road_dist_m', domain,
                      legendText: `色: 幹線道路までの距離／静けさの目安（${_fmt(domain[0])}m〜${_fmt(domain[1])}m）`,
                    };
                  }

                  // 6. 垂直避難
                  if (pq.vertical_evacuation === true) {
                    const domain = _domain(features, p => _evacMarginJs(p));
                    return {
                      mode: 'derived-margin', domain,
                      legendText: `色: 浸水深に対する高さの余裕（${_fmt(domain[0])}m〜${_fmt(domain[1])}m）`,
                    };
                  }

                  // 7. 木造密集
                  if (pq.wooden_dense === true) {
                    return {
                      mode: 'gradient', key: 'wooden_density_ratio', domain: [0, 1],
                      legendText: '色: 周辺100m圏の木造建物比率（薄い=低い 濃い=高い）',
                    };
                  }

                  // 8. 屋根種別
                  if (pq.roof_type) {
                    return { mode: 'categorical-roof', legendText: '色: 屋根種別（■陸屋根 ■勾配屋根）' };
                  }

                  // 9. 該当なし（意味検索のみ等）→ 方針Aへの自動フォールバック
                  return NEUTRAL;
                }
                ```
                補足（実装者向け注記）:
                  - `risk_filters` は複数指定されうる（例:「高潮も洪水も低リスク」）が、
                    地図の塗り分けは1属性に限定するため**最初の1件のみ**を採用する。
                    複数ハザードの合成表示は本フェーズのスコープ外（過剰設計を避ける）。
                  - `pq.risk_filters[0]?.hazard` は `mode`（"none"/"max_depth"）を
                    問わず採用する。除外条件（"none"）であっても、クエリが
                    その災害種別に言及している以上、地図上で可視化する価値がある。
  - TODO 19-2-7: `colorExprFor(spec)` を実装する。`ColorMode` ごとに
                MapLibre の Expression を返す（`maplibregl.ExpressionSpecification`
                の型キャストは既存の `_fillExtrusionColorExpr` に倣う）。
                ```ts
                const GRADIENT_LOW = '#b2dfdb';
                const GRADIENT_HIGH = '#00695c';
                const SUNLIT_COLOR = '#ffb300';
                const NOT_SUNLIT_COLOR = '#9e9e9e';
                const ROOF_FLAT_COLOR = '#5c6bc0';
                const ROOF_SLOPED_COLOR = '#8d6e63';
                export const NEUTRAL_COLOR = '#78909c';

                export function colorExprFor(spec: ColorSpec): unknown {
                  switch (spec.mode) {
                    case 'risk': {
                      const key = spec.key!;
                      return ['case',
                        ['>=', ['coalesce', ['get', key], 0], 5.0], '#c62828',
                        ['>=', ['coalesce', ['get', key], 0], 0.5], '#f57c00',
                        '#2e7d32',
                      ];
                    }
                    case 'gradient': {
                      const key = spec.key!;
                      const [min, max] = spec.domain!;
                      return ['case',
                        ['==', ['get', key], null], NEUTRAL_COLOR,
                        ['interpolate', ['linear'], ['get', key], min, GRADIENT_LOW, max, GRADIENT_HIGH],
                      ];
                    }
                    case 'derived-margin': {
                      const [min, max] = spec.domain!;
                      // _evacMarginJs() と同じロジック（coalesce → max → 引き算）
                      const marginExpr = ['-',
                        ['coalesce', ['get', 'measured_height'], 0],
                        ['max',
                          ['coalesce', ['get', 'ht_depth_max'], 0],
                          ['coalesce', ['get', 'rv_depth_max'], 0],
                          ['coalesce', ['get', 'ts_depth_max'], 0],
                        ],
                      ];
                      return ['interpolate', ['linear'], marginExpr, min, GRADIENT_LOW, max, GRADIENT_HIGH];
                    }
                    case 'boolean-sunlight':
                      return ['case',
                        ['==', ['get', 'winter_sunlit'], true], SUNLIT_COLOR,
                        ['==', ['get', 'winter_sunlit'], false], NOT_SUNLIT_COLOR,
                        NEUTRAL_COLOR,
                      ];
                    case 'categorical-roof':
                      return ['match', ['coalesce', ['get', 'roof_type_est'], ''],
                        '陸屋根', ROOF_FLAT_COLOR,
                        '勾配屋根', ROOF_SLOPED_COLOR,
                        NEUTRAL_COLOR,
                      ];
                    case 'neutral':
                    default:
                      return NEUTRAL_COLOR;
                  }
                }
                ```
                旧実装からの変更点（要注意）: リスクの閾値を `2.0`→`5.0` に変更した
                （PLATEAU公式ランクコードリスト基準への統一。ランク4「5m以上10m未満」
                以上を「高リスク」とする従来の候補リストバッジ判定と整合させるため）。

### Step 19-3: map.ts への適用

  - TODO 19-3-1: [map.ts](frontend/src/map.ts) 冒頭に
                `import { determineColorSpec, colorExprFor, type ColorSpec } from './mapColor';`
                と `import type { ParsedQueryDto } from './api';` を追加する。
                モジュール変数（現16〜19行目付近）に以下を追加する。
                ```ts
                let currentColorSpec: ColorSpec = { mode: 'neutral', legendText: '色分けなし' };
                let pendingParsedQuery: ParsedQueryDto | null = null;
                ```
  - TODO 19-3-2: `_fillExtrusionColorExpr()`（現157〜166行目）を書き換える。
                固定の高潮リスク3段判定（現162〜164行目）を削除し、
                `colorExprFor(currentColorSpec)` の呼び出しに置き換える。
                ```ts
                function _fillExtrusionColorExpr(accentColor: string): maplibregl.ExpressionSpecification {
                  return [
                    'case',
                    ['boolean', ['feature-state', 'hover'], false], HOVER_COLOR,
                    ['boolean', ['get', 'is_recommended'], false], accentColor,
                    colorExprFor(currentColorSpec),
                  ] as unknown as maplibregl.ExpressionSpecification;
                }
                ```
  - TODO 19-3-3: `setGeojson()`（現61行目）のシグネチャを
                `export function setGeojson(geojson: GeoJSON.FeatureCollection, parsedQuery: ParsedQueryDto | null = null): void`
                に変更する。関数の先頭付近（`pendingGeojson` に積む分岐、現62〜65行目）で
                `pendingParsedQuery = parsedQuery;` も併せて積む。
                データを実際にセットする直前（現67〜76行目のsrc取得より前）で
                `currentColorSpec = determineColorSpec(parsedQuery, geojson.features);`
                を計算し、レイヤーが既に存在する場合は
                `map.setPaintProperty(LAYER_3D, 'fill-extrusion-color', _fillExtrusionColorExpr(ACCENT_COLOR[store.get().theme]))`
                で塗り直す（`_addBuildingLayers()` 経由の新規作成時は
                `currentColorSpec` が既に更新済みのため自動的に反映される）。
                件数表示（現100〜101行目）の直後に凡例テキストの更新を追加する。
                ```ts
                const legendEl = document.getElementById('map-color-legend');
                if (legendEl) legendEl.textContent = currentColorSpec.legendText;
                ```
  - TODO 19-3-4: `map.on('load', ...)`（現36〜43行目）で
                `pendingGeojson` を流し込む際、`pendingParsedQuery` も
                `setGeojson(pendingGeojson, pendingParsedQuery)` として渡すよう変更する。
  - TODO 19-3-5: `applyMapTheme()`（現124〜141行目）の `styledata` ハンドラで、
                `pendingGeojson` がない場合に `store.get().activeGeojson` を
                再セットする分岐（現135〜138行目）に、
                `store.get().activeParsedQuery` も渡すよう変更する。
                ```ts
                const current = store.get().activeGeojson;
                const currentPq = store.get().activeParsedQuery;
                if (current) setGeojson(current, currentPq);
                ```
                `pendingGeojson` 側の分岐（現132〜135行目）も同様に
                `pendingParsedQuery` を渡し、使用後は `pendingGeojson` と同様に
                `pendingParsedQuery = null;` でクリアする。

### Step 19-4: 凡例UIの追加

  - TODO 19-4-1: [frontend/index.html](frontend/index.html) の `.map-overlay`
                （現60〜72行目）内、`#map-result-count` の直後・
                `#map-attribution` の直前に凡例用の要素を追加する。
                ```html
                <span id="map-color-legend" class="map-color-legend" aria-live="polite"></span>
                ```
  - TODO 19-4-2: [frontend/src/style.css](frontend/src/style.css) の
                `.map-attribution` 定義（現178〜181行目）の近くに追加する。
                ```css
                .map-color-legend {
                  font-size: 12px; font-weight: 600; color: var(--text-secondary);
                  flex: 1 1 100%; order: 2;
                }
                ```
                `.map-attribution` の `order: 3` はそのまま維持し、
                件数表示（`#map-result-count`、order指定なし=デフォルト0）→
                凡例（order:2）→ 出典注記（order:3）の縦並び順にする
                （`.map-overlay` は既に `flex-wrap: wrap` 設定済み、現168行目）。

### Step 19-5: ビルド・検証・記録

  - TODO 19-5-1: `pixi run build` でフロントエンドを再ビルドし、`src/static/` を更新する。
  - TODO 19-5-2: 型チェック（`tsc`、`npm run build` に含まれる）が
                エラーなく通ることを確認する。
  - TODO 19-5-3: `pixi run app` + `pixi run dev`（または `pixi run build` 後の
                本番サーブ）で以下のクエリを順に実行し、都度地図の色と
                凡例テキストが対応する意味に切り替わることを目視確認する。
                  (a) 「広島駅周辺で一番高い建物は？」→ 高さのグラデーション表示
                      （凡例に実際の高さレンジが出ること）
                  (b) 「高潮リスクが低い建物は？」→ リスク3段階表示
                      （閾値0.5m/5mで塗り分けられていること）
                  (c) 「冬でも日当たりの良い建物は？」→ 日照2色表示
                  (d) 「幹線道路から離れた静かな建物は？」→ 距離グラデーション
                  (e) 「広島駅の近くの雰囲気の良い建物は？」のような意味検索のみの
                      クエリ → 中立色（単色）にフォールバックすること
                  (f) 各クエリで推薦建物・ホバー時の強調色が、上記の意味色より
                      常に優先して表示されること
  - TODO 19-5-4: テーマ切り替え（ライト/ダーク）を各クエリ実行後に行い、
                色分け・凡例が保持されたまま再適用されることを確認する
                （`applyMapTheme` 経由の再描画パス）。
  - TODO 19-5-5: `docs/work_log.md` に Step 単位で記録し、
                Step ごとに git commit する（1 Step = 1 commit）。
                Phase 19 総括として、Phase18で残っていた「地図色の意味が
                クエリと無関係」という限界が解消されたことを明記する。

---

## Phase 20: フットプリント形状指標（円形・矩形・L字型・十字型・星形など）の追加

承認日: 2026-08-26

> **背景:** ユーザーが「円形や星形に近い建物を探して」と指示したところ「形状に関する情報がない」
> という回答が返った。`building_geom_meta`（Phase 9/13）には壁面方位・屋根形状・体積近似・
> 細長さ（`slenderness`）までは前計算済みだが、フットプリント（底面）の輪郭形状を表す指標が
> 一切存在しなかったことが原因。輪郭形状は `hiroshima_sample.gpkg` のフットプリントポリゴンから
> 追加データなしで算出可能。
> ユーザーの追加要望により、円形・星形だけでなく L字型・コの字型・十字型・矩形にも対応する。
>
> **精度に関する制約:** 凹角（へこんだ頂点）の数だけでは L字・T字・十字を厳密には区別できない。
> 本 Phase では凹角数と凸性比（凸包面積との比）を組み合わせたヒューリスティックな推定にとどめ、
> 完全な形状認識（テンプレート照合等）は行わない。この限界は `shape_type_est` カラムの
> コメント・README に明記する。
>
> 既存の「Phase 9（幾何解析）→ Phase 15（query_parser/router 配線）」パターン
> （`roof_type_est` の実装が最も近い先例）に倣う。再埋め込みは不要
> （`roof_type` と同じく SQL のみで確定判定する構造化フィルタとして実装）。

**形状分類の設計:**

幾何指標（`building_geom_meta` に追加するカラム）:

| カラム | 意味 |
|---|---|
| `footprint_perimeter_m` | フットプリント周長（m） |
| `convex_hull_area_m2` | 凸包面積（m²） |
| `footprint_vertex_count` | 頂点数 |
| `concave_vertex_count` | 凹角（へこんだ頂点）の数 |
| `circularity` | 真円度 = `4π・面積 / 周長²`（1.0=真円） |
| `convexity_ratio` | 凸性比 = `面積 / 凸包面積`（1.0=凸形状） |
| `shape_type_est` | 下表ルールによる推定分類（VARCHAR） |

`shape_type_est` 分類ルール（仮閾値。Step 20-1-5 で実データ分布を確認し確定）:

| 条件（上から順に判定） | 分類 |
|---|---|
| `circularity >= 0.75` | 円形に近い |
| `concave_vertex_count == 0` | 矩形・単純形状 |
| `concave_vertex_count == 1` | L字型 |
| `concave_vertex_count == 2` | コの字型・T字型 |
| `concave_vertex_count in (3, 4)` かつ `convexity_ratio >= 0.6` | 十字型・複雑形状 |
| それ以外（`concave_vertex_count >= 3` かつ `convexity_ratio < 0.6`、または `concave_vertex_count >= 5`） | 星形・複雑形状 |

凹角の判定方法: フットプリントの外周リングについて、隣接エッジベクトルの外積（2Dなので符号のみ）を
頂点ごとに計算し、ポリゴン全体の回転方向（符号の多数決）と逆符号になる頂点を凹角と数える。
新規ライブラリ不要・既存コード（`newell_normal()`）と同系統の手法で実装する。

### Step 20-1: フットプリント形状指標の計算（`src/phase9_geometry.py` 拡張）

  - TODO 20-1-1: `fetch_footprint_areas()` を `fetch_footprint_shape()` にリネーム・拡張し、
                `hiroshima_sample.gpkg` の `bldg:Building.geometry` から
                `footprint_area_m2` / `footprint_perimeter_m`（`ST_Perimeter`）/
                `convex_hull_area_m2`（`ST_Area(ST_ConvexHull(...))`）/
                `footprint_vertex_count`（`ST_NPoints`）と、外周リングの WKT
                （凹角計算用。`ST_AsText(ST_ExteriorRing(ST_Force2D(geometry)))`）を取得する。
                実装前に DuckDB spatial 拡張で `ST_Perimeter` / `ST_ConvexHull` / `ST_NPoints` /
                `ST_ExteriorRing` が実際に解決できるか最小サンプルで確認済み（2026-08-26 確認: 全関数解決可）。
  - TODO 20-1-2: `count_concave_vertices(ring_wkt: str) -> int | None` を実装する。
                リング頂点列（始点=終点を除去）について各頂点で隣接エッジの外積 z 成分の符号を
                求め、多数派の符号と異なる頂点数を返す（頂点数 3 未満は None）。
  - TODO 20-1-3: `circularity` / `convexity_ratio` を計算する（面積・周長・凸包面積が 0 または
                NULL の場合は None）。
  - TODO 20-1-4: `estimate_shape_type(circularity, convexity_ratio, concave_vertex_count) ->
                str | None` を「形状分類の設計」表のルールで実装する。モジュール定数として
                閾値を定義する: `_CIRCULAR_THRESHOLD = 0.75`, `_CROSS_CONVEXITY_MIN = 0.6`。
  - TODO 20-1-5: `extract_geom_meta()` で新指標を LEFT JOIN し、`circularity` / `convexity_ratio` /
                `concave_vertex_count` / `shape_type_est.value_counts()` の実データ分布を確認する。
                矩形建物が大半を占める実データで分類が極端に偏らないか検証し、必要なら閾値を
                調整して work_log に確定理由を記録する（Phase 10 G09/G11/G16、Phase 13 の
                閾値確定と同じ手順）。
  - TODO 20-1-6: `create_geom_meta_table()` に新カラム 7 種を追加する（`footprint_perimeter_m`,
                `convex_hull_area_m2`, `footprint_vertex_count`, `concave_vertex_count`,
                `circularity`, `convexity_ratio`, `shape_type_est`）。`shape_type_est` の
                カラムコメントに「凹角数ベースのヒューリスティック推定であり、L字・T字・十字の
                厳密な区別は保証しない」旨を明記する。
  - TODO 20-1-7: `pixi run python src/phase9_geometry.py` を再実行し `building_geom_meta` を
                DROP → 再作成する。統計サマリー print に `shape_type_est.value_counts()` を追加する。

### Step 20-2: `query_parser.py` 拡張

  - TODO 20-2-1: `ParsedQuery` に `footprint_shape: str | None = None` を追加する
                （値は `"円形に近い"` / `"矩形・単純形状"` / `"L字型"` / `"コの字型・T字型"` /
                `"十字型・複雑形状"` / `"星形・複雑形状"` のいずれか、または `null`）。
  - TODO 20-2-2: `_SYSTEM_PROMPT` に抽出ルールを追加する:
                「円形」「丸い」「円柱状」「曲線的」→ `"円形に近い"`／
                「矩形」「四角い」「シンプルな形状」「長方形」「正方形」→ `"矩形・単純形状"`／
                「L字型」「L字」「かぎ型」→ `"L字型"`／
                「コの字型」「U字型」「馬蹄形」→ `"コの字型・T字型"`／
                「十字型」「クロス型」「T字型」→ `"十字型・複雑形状"`／
                「星形」「星型」「ギザギザ」「複雑な形状」「凹凸のある形状」→ `"星形・複雑形状"`。
                上記いずれにも当てはまらない曖昧な形状表現は `footprint_shape=null` のまま
                `semantic_residual` に原文を残す（既知の限界として README に記載）。
  - TODO 20-2-3: `_SORT_KEYS` に `circularity` を追加し、「最も円形に近い建物」→
                `sort_by={"key":"circularity","order":"desc"}` のルールを追記する。
  - TODO 20-2-4: `response_schema` に `footprint_shape` を追加する。
  - TODO 20-2-5: `__main__` のテストケースに「円形に近い建物を教えて」「L字型の建物はある？」
                「コの字型や十字型の建物を探して」を追加し、期待値をコメント併記する。

### Step 20-3: `phase10_router.py` 配線

  - TODO 20-3-1: `COLUMN_SOURCE` に `circularity`, `convexity_ratio`, `concave_vertex_count`,
                `footprint_vertex_count`, `shape_type_est` を `"g"` として追加する。
  - TODO 20-3-2: `classify_route()` の `has_structured` 判定に `or pq.footprint_shape` を追加する。
  - TODO 20-3-3: `build_filter_clauses()` に `roof_type` と同じパターンで追加する
                （`shape_type_est = ?`）。
  - TODO 20-3-4: `verify_candidates()` に同様の検証を追加する（`shape_type_est` の不一致を検出）。
  - TODO 20-3-5: `build_order_clause()` は既存の汎用ロジックで `circularity` にも対応済みのはずだが、
                `NULLS LAST` 等の扱いに問題がないことを確認する。

### Step 20-4: `phase4_retrieval.py` 比較表・プロンプト拡張

  - TODO 20-4-1: `vector_search()` の SELECT 句（`g.roof_area_m2, g.roof_type_est` と同じ並び）に
                `g.shape_type_est` を追加する（structured/hybrid/semantic 全経路）。
  - TODO 20-4-2: `build_prompt()` の比較表に「形状」列を追加し、`row.get('shape_type_est')` を
                `_fmt_unknown()` で表示する。
  - TODO 20-4-3: `hybrid_search()` の戻り値 dict に `"footprint_shape": pq.footprint_shape` を追加する。

### Step 20-5: 評価・サニティチェック・コミット

  - TODO 20-5-1: `tests/gold_set.py` に構造化クエリを 3 件追加する（円形／L字型／星形・複雑形状の
                それぞれについて `shape_type_est` 一致条件の `gold_sql`）。
  - TODO 20-5-2: `tests/sanity_checks.py` に Phase 20 用チェックを追加する:
                `check_phase20_shape_columns()`（新カラムの存在・`circularity` の非NULL件数 > 0）、
                `check_phase20_shape_filter()`（「円形に近い建物を教えて」で `route="structured"`
                かつ全候補 `shape_type_est == "円形に近い"`）、
                `run_phase20_checks()` と `--phase20` CLI 分岐を追加する。
  - TODO 20-5-3: `pixi run python tests/eval_retrieval.py` を再実行し、既存カテゴリの
                recall/precision に回帰がないことを確認する。
  - TODO 20-5-4: `docs/work_log.md` に Step 20-1〜20-5 の実施内容・分布確認結果・閾値確定理由・
                コミットハッシュを記録する。分類の限界（L/T/十字の厳密区別不可）も明記する。
  - TODO 20-5-5: Step 単位で git commit する（コミット規則: `feat(phase20): <日本語概要>`）。

---

## Phase 21: RURI v3 310m 埋め込みモデルのベンチマーク検証

承認日: 2026-08-27

> **背景:** FOSS4G（オープン&フリーなGIS国際会議）での発表に向け、埋め込みモデルを現行の
> `gemini-embedding-001`（クローズドAPI）から、日本語特化のオープンモデル **RURI v3 310m**
> （`cl-nagoya/ruri-v3-310m`, Apache 2.0, 315Mパラメータ, 768次元）へ切り替える検討を進めている。
>
> 選定理由:
> - オープン&フリー精神との親和性（FOSS4Gのテーマに合致）
> - 日本語特化で精度が期待できる
> - ローカル実行可能（APIキー不要、オフラインデモに強い）
>
> ユーザーの実行環境はGPU非搭載ノートPC（メモリ16GB、空き約8GB）。モデルカード確認の結果、
> 315Mパラメータ・fp32で約1.2GB程度のメモリ消費と見積もられ、CPU推論・空き8GBの環境でも
> 動作可能と判断しているが、**実測での検証がまだ行われていない**。
>
> 再埋め込み自体はいずれ実施予定であるため躊躇はないが、本Phaseはその前段として
> 「実際にこのノートPCで動くか」「速度・メモリはどの程度か」を先に確認する**ベンチマークのみ**
> に範囲を限定する。全件（2,958件）の本番再埋め込み・DuckDBスキーマ変更・
> `vector_search()`等の検索ロジック改修は含まない（結果を見て次Phaseで判断）。
>
> **将来検討事項（本Phaseのスコープ外）: Reranker導入**
> `cl-nagoya/ruri-v3-reranker-310m`（ModernBERT-Jaベース、Apache 2.0）が公式に存在する。
> Phase 10背景にあった「埋め込みのみでは候補間の識別力が低い」という課題への対策として
> 有効な可能性があるが、Cross-Encoder方式のため候補数分の追加推論コストがかかり、
> CPU環境ではレイテンシへの影響が大きい。RURI埋め込み本採用後、実際の識別力を
> 再評価したうえで別Phaseとして検討する。

### Step 21-1: pixi環境へのローカル埋め込みモデル依存追加

  - TODO 21-1-1: CPU版PyTorchとsentence-transformersをpixiに追加する。
                `/c/Users/pikkarin/AppData/Local/pixi/bin/pixi.exe add pytorch-cpu sentence-transformers`
                を試し、conda-forgeで解決できない場合は `pixi.toml` の
                `[pypi-dependencies]` に `sentence-transformers = ">=3.0"` を追記して
                `pixi.exe install` する（Phase 12のSudachiPy追加時と同じ手順に倣う。
                どちらの経路を採ったか work_log.md に記録）。
  - TODO 21-1-2: `pixi.exe run python -c "from sentence_transformers import SentenceTransformer;
                m = SentenceTransformer('cl-nagoya/ruri-v3-310m'); print(m.encode(['テスト文']).shape)"`
                を実行し、初回ダウンロード（HuggingFace Hubキャッシュ）が完了することと
                出力ベクトルが768次元であることを確認する。
  - TODO 21-1-3: RURI v3の「1+3プレフィックス方式」を確認する。
                本プロジェクトでの割り当ては次の通り（モデルカード仕様に基づく確定事項）:
                ・building_chunks側（text_card）→ `"検索文書: "` を先頭に付与
                ・ユーザークエリ側 → `"検索クエリ: "` を先頭に付与
                この対応を次StepのベンチマークスクリプトにTODO 21-2-1で明示的に組み込む
                （プレフィックスなしでの誤ったベンチマークを避けるため）。

### Step 21-2: ベンチマークスクリプト実装

  - TODO 21-2-1: `tests/benchmark_ruri.py` を新規作成する。
                `src/phase3_enrichment.py` の `build_text_card()` と同じデータソース
                （`load_building_attributes()` の出力）からテキストカルテを取得し、
                件数を引数で指定可能にする（デフォルト100件、`--full`で全2,958件）。
                エンコード時は必ず `"検索文書: " + text_card` の形でプレフィックスを
                付与する（TODO 21-1-3のプレフィックス方式に従う。付与有無でベクトルが
                変わるため、ベンチマーク自体もこの形で統一する）。
  - TODO 21-2-2: 計測関数 `run_benchmark(texts: list[str], batch_size: int) -> dict` を実装する。
                計測項目:
                ・総処理時間・1件あたり平均時間（`time.perf_counter()`）
                ・ピークメモリ使用量（`psutil.Process().memory_info().rss` の
                  実行前後差分。`psutil` が未導入ならpixiに追加）
                ・出力ベクトルの次元数（期待値768との一致確認）
                バッチサイズは `[8, 32]` の2パターンで比較する。
  - TODO 21-2-3: `__main__` で100件サブセットのベンチマークを実行できるようにし、
                結果を `output/benchmark_ruri_{YYYYMMDD_HHMM}.json` に保存する
                （項目: サンプル件数・バッチサイズ・総時間・1件あたり時間・ピークメモリMB・次元数）。

### Step 21-3: 実測・記録・判断

  - TODO 21-3-1: `pixi.exe run python tests/benchmark_ruri.py` を実行し、
                100件サブセットの結果を確認する。極端な遅延・メモリ不足エラーが
                なければ `--full` で全2,958件のベンチマークも実行する。
  - TODO 21-3-2: 結果を `docs/work_log.md` に記録する。Phase 3実測値
                （`gemini-embedding-001`、API呼び出し・Free Tier日次クォータ制限あり）
                と定性的に比較し、実行時間・メモリ・次元数の違いを整理する。
  - TODO 21-3-3: 実用可否について、計測結果に基づきユーザーに判断を仰ぐ
                （全件再埋め込みへ進むか、バッチサイズ調整が必要か等）。
                本Stepの完了をもってPhase 21終了とし、全件再埋め込み・
                DuckDBスキーマ変更・検索ロジック改修は次Phaseとして別途計画する。

**検証方法:**
- `pixi.exe run python tests/benchmark_ruri.py`（100件）→ 出力JSONと標準出力の
  時間・メモリ・次元数を確認
- `pixi.exe run python tests/benchmark_ruri.py --full`（全件、100件の結果が良好な場合のみ）
- 既存のサニティチェック体系（`tests/sanity_checks.py`）への追加は本Phaseでは不要
  （ベンチマークは検索パイプラインを変更しないため）

---

## Phase 22: RURI v3 310m 全件ベンチマーク＋精度比較

承認日: 2026-08-27

> **背景:** Phase 21で100件サンプルのベンチマークを実施し、RURI v3 310mが速度面
> （約1.2秒/件、全件で推定約60分）・メモリ面（約1.1GB、空き8GB環境で問題なし）で
> 実行可能であることを確認した。ただしこれだけでは「本採用してよいか」を判断できない。
> ユーザーから以下2点の指摘があった:
> 1. 100件サンプルだけでなく全件（2,958件）を実際に流し、長時間実行でメモリが
>    増え続けないか・極端に長いtext_cardで詰まらないかを確認すべき
> 2. 速度・メモリだけでなく、現行の`gemini-embedding-001`と比較した**検索精度**が
>    分からないと本採用の判断ができない
>
> 本Phaseはこの2点に応え、「全件実行→精度比較→判断」までを完了させる。**本番の切り替え**
> **（`building_chunks`のスキーマ変更・検索ロジックの恒久的な改修・複数モデル切り替え機構）は**
> **含めない**。精度比較の結果を見てから、必要であれば別Phase（23）として改めて計画・
> 承認を得る（Phase 10〜20で踏襲してきた「実測→判断→次Phase計画」のパターンに倣う）。
>
> **設計方針（重要な判断）:** 精度比較には、既存の評価基盤（`tests/gold_set.py` /
> `tests/eval_retrieval.py`）と検索ルーティング（`src/phase10_router.py`の
> classify_route/build_filter_clauses等、`src/query_parser.py`のparse_query）を
> そのまま再利用する。これらは埋め込みモデルに依存しないロジック（構造化条件のSQL変換・
> クエリ解析）のため、RURI版でも無改修で使える。
>
> 埋め込みが関わる部分（`vector_search()` / `hybrid_search()` / `evaluate()`）は、
> 新規に丸ごと複製せず、`embedding_source: str = "gemini"`という追加の省略可能引数を
> 挿す形の最小差分で対応する。理由: `vector_search()`は`building_geom_meta`/
> `building_context_meta`とのJOIN分岐が複雑（Phase 9/13/15で積み上げた分岐）であり、
> これを別ファイルに複製すると将来の改修で2箇所が食い違うリスクが高い。追加引数による
> アプローチなら、デフォルト値（`"gemini"`）で既存動作は完全に変わらず、ロールバックも
> 「追加した数行を削除 + 新規テーブルをDROP + 新規モジュールを削除」のみで完了する。
>
> RURI埋め込みの保存先は、本番DB（`output/plateau_rag.duckdb`）に**追加テーブル**
> `building_chunks_ruri_embed(id, embedding FLOAT[768])`として持たせる。既存の
> `building_chunks`テーブル・そのHNSWインデックスには一切触れない。

### Step 22-1: 全件RURI埋め込み生成

  - TODO 22-1-1: `src/phase22_ruri_embed.py` を新規作成する。
                `DOC_PREFIX = "検索文書: "` / `QUERY_PREFIX = "検索クエリ: "`
                （RURI v3の1+3プレフィックス方式、Phase21で確定済み仕様）。
                `_get_model()`: `SentenceTransformer('cl-nagoya/ruri-v3-310m')` を
                モジュールレベルで遅延キャッシュ（呼び出しごとの再ロードを防ぐ）。
                `embed_query_ruri(text: str) -> list[float]`: `QUERY_PREFIX + text` を
                エンコードして返す。
                `build_ruri_index(batch_size: int = 32) -> None`: `connect_rag()`
                （`src/phase3_enrichment.py`を再利用）で本番DBに接続し、
                `SELECT id, text_card FROM building_chunks` を全件取得 →
                `DOC_PREFIX + text_card` でエンコード → `building_chunks_ruri_embed` を
                DROP → CREATE → 一括 INSERT（Phase9/13の「毎回DROP→再作成」の
                流儀を踏襲）。`__main__` で `build_ruri_index()` を実行し、
                開始・終了時刻と所要時間、挿入件数を表示する。
  - TODO 22-1-2: `pixi.exe run python src/phase22_ruri_embed.py` を実行し、
                全2,958件のRURI埋め込みを生成する（推定所要時間: 約60分）。
                実行中にメモリ不足やエラーが発生しないこと、
                `building_chunks_ruri_embed` の件数が `building_chunks` と
                一致することを確認する。

### Step 22-2: 検索経路へのRURI組み込み（最小差分）

  - TODO 22-2-1: `src/phase4_retrieval.py` の `vector_search()` に
                `embedding_source: str = "gemini"` を追加する。
                `embedding_source == "ruri"` かつ `use_vector` の場合のみ、
                `from_clause` に `LEFT JOIN building_chunks_ruri_embed r ON
                {alias}id = r.id` を追加し、`score_expr` の埋め込み参照を
                `b.embedding`/`embedding` から `r.embedding` に差し替える
                （`dim` は `len(query_vec)` から自動的に768になるため変更不要）。
                デフォルト値 `"gemini"` 時は既存コードパスと完全に同一であることを
                確認する。
  - TODO 22-2-2: `hybrid_search()` に `embedding_source: str = "gemini"` を追加する。
                `route != "structured"` かつ `embedding_source == "ruri"` の場合、
                `embed_query(embed_text)` の代わりに
                `phase22_ruri_embed.embed_query_ruri(embed_text)` を呼ぶ
                （`use_hyde`との組み合わせ順序は既存のGemini経路と同じ:
                HyDE書き換え後のテキストをRURIでエンコード）。
                `vector_search()` 呼び出しに `embedding_source=embedding_source` を
                伝播し、戻り値dictに `"embedding_source": embedding_source` を追加する。
  - TODO 22-2-3: `tests/eval_retrieval.py` の `evaluate()` / `main()` に
                `embedding_source: str = "gemini"` パラメータと `--ruri` CLIオプションを
                追加し、`hybrid_search()` へ伝播する（既存の `--fts` / `--hyde` と
                同じパターン）。出力ファイル名のsuffixにも `_ruri` を追加する。
  - TODO 22-2-4: 回帰確認として、「広島市で最も高い建物は？」（structuredカテゴリ、
                G01）を `embedding_source="gemini"` と `"ruri"` の両方で実行し、
                **完全に同一の結果**になることを確認する（structured経路は埋め込みを
                使わないため、実装が正しければ埋め込みモデルの違いは結果に影響
                しないはずであり、これが実装ミスの検出にもなる）。

### Step 22-3: 精度比較・記録・判断

  - TODO 22-3-1: `pixi.exe run python tests/eval_retrieval.py --ruri` を実行し、
                現行の全ゴールドクエリ（`output/gold_set.json`、structured/hybrid/
                geometric/robustness/semantic）で recall@k・precision@k・hit@1 を
                計測する。結果は `output/eval_result_{YYYYMMDD_HHMM}_ruri.csv` に
                保存される。
  - TODO 22-3-2: 直近のGeminiベースライン（`output/eval_result_20260826_0557.csv`、
                Phase20時点）とcategory別マクロ平均をBefore/After表にまとめる。
                semanticカテゴリはrecall計測対象外のため、`retrieved_ids`列を
                目視比較して定性的な傾向（候補の入れ替わり方など）を記録する。
  - TODO 22-3-3: structuredカテゴリの数値が完全一致することを確認し、Step 22-2の
                実装が正しいことの裏付けとして記録する（一致しない場合はStep 22-2の
                実装ミスを疑い、原因を特定してから先に進む）。
  - TODO 22-3-4: `docs/work_log.md` にStep 22-1〜22-3の実施内容・実測値・比較表・
                考察を記録する。
  - TODO 22-3-5: 比較結果をユーザーに報告し、本採用（Phase 23: `building_chunks`の
                スキーマ変更・検索ロジックの恒久的改修・Gemini/RURIの切り替え機構
                実装）に進むかどうかの判断を仰ぐ。本TODOの完了をもってPhase 22を
                終了とする。

> **Step 22-3実施後の追加判明事項:** `tests/eval_retrieval.py --ruri` を実行した結果、
> 39件中36件でGemini/RURIの候補IDが完全一致した。原因は`gemini`用・`ruri`用を
> 別々に実行しており、それぞれの実行内部で`hybrid_search()`が`parse_query()`
> （非決定性あり、Phase11既知）を呼び直すため、`classify_route()`の判定結果が
> 実行ごとにブレ、本来hybrid/semanticに分類されるべきクエリの大半がstructured
> （埋め込み非依存）に落ちてしまっていた。ユーザーと協議の上、`parse_query()`
> 自体を直す（LLM出力の完全な決定性は本質的に困難）のではなく、**評価方法を
> 「同一クエリでparse_query()を1回だけ呼び、そのParsedQueryをGemini/RURI両方の
> 実行で使い回す」形に修正**する方針とし、Step 22-4〜22-6として追加する。

### Step 22-4: hybrid_search() に ParsedQuery 注入口を追加

  - TODO 22-4-1: `src/phase4_retrieval.py` の `hybrid_search()` に
                `parsed_query_override: "ParsedQuery" | None = None` を追加する。
                `use_query_parser=True` の内部で
                `pq = parsed_query_override if parsed_query_override is not None
                else parse_query(query)` に変更する（それ以外の処理——
                `parsed_query_dict`構築・clarification判定・geocode・
                `classify_route(pq)`・以降のembedding/vector_search呼び出し——は
                すべて`pq`を参照しているため無改修で動く）。デフォルト値`None`時は
                既存動作と完全に同一。

### Step 22-5: ペア比較評価関数の実装

  - TODO 22-5-1: `tests/eval_retrieval.py` に `evaluate_paired(top_k: int = 10,
                ids: list[str] | None = None) -> pd.DataFrame` を新規追加する。
                既存の`_recall_precision()`をそのまま再利用する。処理内容:
                gold_set.json の各クエリについて `parse_query(query)` を
                **1回だけ**呼ぶ（`from query_parser import parse_query` を追加
                インポート）。同じ`pq`を使い、`hybrid_search(query=gq["query"],
                top_k=top_k, skip_answer=True, parsed_query_override=pq,
                embedding_source="gemini")` と `embedding_source="ruri"` の
                両方を呼ぶ。各embedding_sourceについて`_recall_precision()`と
                hit1を算出し、1行に `id, category, route, recall_gemini,
                recall_ruri, precision_gemini, precision_ruri, hit1_gemini,
                hit1_ruri, n_gold, retrieved_ids_gemini, retrieved_ids_ruri` を
                持つDataFrameとして返す（semanticカテゴリはNaN、既存`evaluate()`
                と同じ扱い）。category別マクロ平均をgemini/ruri両方について
                表示する（既存`evaluate()`のサマリー表示パターンを踏襲）。
  - TODO 22-5-2: `main()` に `--paired` CLIオプションを追加する。指定時は
                `evaluate_paired()` を実行し、結果を
                `output/eval_result_{ts}_paired.csv` に保存する。

### Step 22-6: 実行・比較・記録

  - TODO 22-6-1: `pixi.exe run python tests/eval_retrieval.py --paired` を実行する。
  - TODO 22-6-2: 出力されたrouteの分布を確認し、Step 22-3で見つかった「大半が
                structuredに落ちる」問題が解消され、gold_set.json本来の
                category（hybrid/semantic）に近い分布でルーティングされている
                ことを確認する。
  - TODO 22-6-3: structured/hybrid/geometric/robustnessカテゴリのcategory別
                マクロ平均をGemini/RURIで比較する（recall_gemini vs recall_ruri
                等）。今回は同一route・同一フィルタ条件のため、差分があれば
                純粋に埋め込みモデルの違いに起因すると解釈できる。
  - TODO 22-6-4: `docs/work_log.md` にStep 22-4〜22-6の実施内容・route分布の
                改善確認・Gemini/RURIの比較表・考察を記録する。
  - TODO 22-6-5: 比較結果をユーザーに報告し、本採用（Phase 23）に進むかどうかの
                判断を仰ぐ。semanticカテゴリ（正解データなし）の扱いは今回も
                スコープ外とし、必要であれば別途相談する。

**検証方法（Step 22-4〜22-6）:**
- Step 22-4: `hybrid_search(query, parsed_query_override=None, ...)` が既存の
  `pixi run python tests/eval_retrieval.py`（無印、gemini）で従来と同じ結果に
  なることを簡単に確認（回帰確認）
- Step 22-5/22-6: `pixi.exe run python tests/eval_retrieval.py --paired` の
  実行結果CSVとcategory別マクロ平均の比較表

**検証方法:**
- Step 22-1: `pixi.exe run python src/phase22_ruri_embed.py` の完了、
  `SELECT COUNT(*) FROM building_chunks_ruri_embed` が2,958件であることを確認
- Step 22-2: TODO 22-2-4の回帰確認（gemini/ruriでstructured結果が完全一致）
- Step 22-3: `pixi.exe run python tests/eval_retrieval.py --ruri` の実行結果CSVと
  Before/After比較表
- 本Phase全体を通じて `tests/sanity_checks.py` の既存チェック（`--phase10`等）に
  回帰がないことを流して確認する

---

## Phase 23: Gemini/RURI 埋め込み切り替え機能（Web UIまで対応）

承認日: 2026-08-28

> **背景:** Phase 22で「全件実行→精度比較→判断」を完了した。structured/robustness系
> （実クエリの大半）はGemini・RURIで完全に同一の精度、semantic系（ごく一部）は
> 定量比較が原理的に不可能と判明し、優劣を客観的に決着させる材料は出尽くした。
> ユーザーと相談の結果、残りは「実際に使ってみて判断する」方針となり、そのために
> **Web UIを含めてGemini/RURIをその場で切り替えられる機能**を実装する。
>
> Phase 22で実装した`embedding_source`パラメータ（`vector_search()` / `hybrid_search()`）と
> 追加テーブル`building_chunks_ruri_embed`は、既存コードへの影響が小さい追加のみの設計
> （デフォルト`"gemini"`で既存動作と完全に同一）であり、そのまま本番機能に昇格させて
> 問題ない。**スキーマの作り直しは行わない**——Phase22の設計時点で「本番相当のクリーンな
> 追加」を意識していたため、再構築のコストをかける理由がない。本Phaseでやることは
> (1) FastAPI層への配線、(2) フロントエンドのチャットUIに選択UIを追加、
> (3) RURI未生成時のエラーハンドリング、の3点に限定する。

### Step 23-1: バックエンド（FastAPI）への配線

  - TODO 23-1-1: `src/phase4_retrieval.py`の`vector_search()`に、`use_ruri`がTrueなのに
                `building_chunks_ruri_embed`テーブルが存在しない場合の明示的エラーを
                追加する（Phase15の`needs_geom`/`needs_context`チェックと同じパターン）。
                エラーメッセージには`pixi run python src/phase22_ruri_embed.py`の
                実行を促す文言を含める。
  - TODO 23-1-2: `src/phase6_app.py`の`SearchRequest`に`embedding_source: str = "gemini"`
                を追加し、`search()`エンドポイント内の`hybrid_search(...)`呼び出しに
                `embedding_source=req.embedding_source`を渡す。`SearchResponse`にも
                `embedding_source: str`を追加し、`result.get("embedding_source",
                "gemini")`を返す（`model_provider`/`route`と同じ「実際に使われた値を
                レスポンスに含める」慣習を踏襲）。

### Step 23-2: フロントエンドUIへの配線

  - TODO 23-2-1: `frontend/index.html`の`.input-options`内、既存の`model-select`と
                同じ構造で`embedding-select`を追加する（`<option value="gemini">
                Gemini Embedding</option>` / `<option value="ruri">RURI v3 310m
                （ローカル）</option>`）。
  - TODO 23-2-2: `frontend/src/store.ts`の`Settings`インターフェースに
                `embeddingSource: string`を追加し、初期値`'gemini'`を設定する。
  - TODO 23-2-3: `frontend/src/api.ts`の`SearchRequest`に`embedding_source?: string`、
                `SearchResponse`に`embedding_source: string`を追加する。
  - TODO 23-2-4: `frontend/src/main.ts`で、`model-select`と同じパターンで
                `embedding-select`の`change`イベントを購読し`store.set({settings:
                {..., embeddingSource: embeddingSelect.value}})`を行う。
                `runSearch()`内の`search({...})`呼び出しに
                `embedding_source: settings.embeddingSource`を追加する。
  - TODO 23-2-5: `pixi run build`でビルドし、`pixi run app`でFastAPI経由の本番相当配信を
                確認する（Phase6の確認手順を踏襲）。

### Step 23-3: 動作確認・記録

  - TODO 23-3-1: ブラウザで実際にチャットUIから「埋め込み: RURI v3 310m」を選択し、
                構造化クエリ（例:「広島市で最も高い建物は？」）と意味的クエリ
                （例:「日当たりのよい建物」）の両方を試し、エラーなく回答・地図表示まで
                完走することを確認する。Gemini選択時と結果を見比べる（速度・回答内容を
                目視確認）。
  - TODO 23-3-2: `building_chunks_ruri_embed`が存在しない状態を想定し、RURI選択時に
                TODO 23-1-1のエラーメッセージが適切に表示されることを確認する
                （一時的にテーブル名を変えてテストし、確認後に戻す等）。
  - TODO 23-3-3: `docs/work_log.md`にStep 23-1〜23-3の実施内容を記録し、Step単位で
                git commitする（コミット規則: `feat(phase23): <日本語概要>`）。

**検証方法:**
- Step 23-1: `pixi run python -c "..."` で`embedding_source="ruri"`を明示的に指定した
  `hybrid_search()`呼び出しが従来通り動くことを確認（Phase22で確認済みの動作の回帰確認）
- Step 23-2/23-3: `pixi run dev`（開発サーバ）または`pixi run build && pixi run app`
  （本番相当）でブラウザから実際にUIを操作し、Gemini/RURI両方で検索が完走することを
  目視確認する

---

## Phase 24: UI日英切り替え対応（チャット・地図凡例・ポップアップ・LLM回答）

承認日: 2026-08-28

> **背景:** FOSS4G（国際会議）での発表に向け、現状日本語のみのUIを英語話者にも
> 伝わる形にする。ユーザーとの相談の結果、対応範囲は以下に確定した:
> チャットUIの静的テキスト（ヘッダー・ウェルカムメッセージ・入力エリア・
> オプション選択）、動的UI文言（announce()の読み上げメッセージ・候補件数表示・
> エラーメッセージ等）、**地図の凡例・ポップアップ**（用途・階数・壁面方位・
> 冬日照・屋根種別等のラベル）、候補建物リストの属性表示、LLM回答本文の英語化。
>
> **既知の制限（対応範囲外）:** 建物データ自体（駅名・避難所名・学校名等の固有名詞）は
> DBに日本語で保存されているため翻訳しない。DB由来の**列挙値**（用途・構造・耐火・
> 浸水ランク・屋根種別・形状分類）は実データで確認した有限集合を翻訳辞書として
> 持つが、固有名詞（施設名）は対象外とする。
>
> DBの実データから確認した翻訳対象の列挙値（`output/plateau_rag.duckdb`で実測）:
> - usage: その他/不明/住宅/供給処理施設/共同住宅/商業施設/商業系複合施設/官公庁施設/
>   宿泊施設/店舗等併用住宅/店舗等併用共同住宅/文教厚生施設/業務施設/運輸倉庫施設
> - structure_type: レンガ造・コンクリートブロック造・石造/不明/木造・土蔵造/軽量鉄骨造/
>   鉄筋コンクリート造/鉄骨造/鉄骨鉄筋コンクリート造
> - fire_proof: その他/不明/準耐火造/耐火
> - ht/rv/ts_rank_worst: 0.5m未満/0.5m以上3m未満/3m以上5m未満/5m以上10m未満
> - roof_type_est: 勾配屋根/陸屋根
> - shape_type_est: L字型/コの字型・T字型/円形に近い/十字型・複雑形状/星形・複雑形状/
>   楕円形/矩形・単純形状
>
> **設計方針:** フロントエンド（vanilla TS）に軽量なi18n基盤を追加する。既存の
> `theme.ts`（ダークモード切り替え）と同じ「トグルボタン + 属性/テキストの
> 一括更新」パターンを踏襲する。静的UI文言は`data-i18n`属性の一括更新、
> 動的生成コンテンツ（チャットバブル・地図凡例・ポップアップ）は生成時に
> `store.get().language`を引数として渡す方式とする。**言語トグル時に既存の
> 会話履歴・既存の地図表示は再翻訳しない**（次の検索から新しい言語が反映される。
> シンプルさを優先した既知の制限）。LLM回答の言語はUIの言語設定と連動させる。
> `query_parser.py`（クエリ解析）やDBスキーマには一切手を入れない。

### Step 24-1: i18n基盤の実装

  - TODO 24-1-1: `frontend/src/i18n.ts`を新規作成する。
                `type Lang = 'ja' | 'en'`、`UI_STRINGS: Record<Lang, Record<string,
                string>>`（`t(lang, key, params?): string`ヘルパー付き）、
                `VALUE_LABELS: Record<Lang, Record<string, string>>`
                （上記の列挙値翻訳辞書。方角・施設カテゴリ・災害種別のラベルも
                含める）、`translateValue(lang, ja: string): string`
                （`VALUE_LABELS[lang][ja] ?? ja`でフォールバック）を実装する。
  - TODO 24-1-2: `frontend/src/store.ts`の`AppState`に`language: 'ja' | 'en'`
                を追加し初期値`'ja'`とする。
  - TODO 24-1-3: `frontend/index.html`のヘッダーに`theme-toggle`と同じ構造で
                `lang-toggle`ボタンを追加する。既存の静的テキスト要素に
                `data-i18n`/`data-i18n-placeholder`/`data-i18n-aria-label`
                属性を付与する。
  - TODO 24-1-4: `frontend/src/main.ts`に`applyStaticTranslations(lang: Lang):
                void`を実装し、初期化時と`lang-toggle`の`click`イベント時に
                呼び出す（`theme.ts`の`applyTheme()`と同じ配線パターン）。

### Step 24-2: 動的UI文言・announce()メッセージの多言語化

  - TODO 24-2-1: `frontend/src/main.ts`内の`announce()`呼び出し・エラー
                メッセージ・候補件数表示等を`UI_STRINGS`経由に置き換える。
  - TODO 24-2-2: `frontend/src/chat.ts`のメッセージバブル生成関数に`lang: Lang`
                引数を追加し、aria-label・「さらにN件」等を`t()`経由にする。
  - TODO 24-2-3: `frontend/src/chat.ts`の候補建物リスト内の属性表示に
                `translateValue()`を適用する。

### Step 24-3: 地図凡例・ポップアップの多言語化

  - TODO 24-3-1: `frontend/src/mapColor.ts`の`HAZARD_LABEL` / `DIR_LABEL` /
                `FACILITY_LABEL` / フィールドラベル / 屋根種別ラベル / 凡例文言を
                `Record<Lang, ...>`形式に拡張し、凡例構築関数に`lang`引数を追加する。
  - TODO 24-3-2: `frontend/src/map.ts`のポップアップHTML生成部分のラベルを
                `i18n.ts`辞書経由、DB値は`translateValue()`経由にする。
  - TODO 24-3-3: `frontend/src/map.ts`の候補件数表示を`t()`経由にする。

### Step 24-4: LLM回答の英語化（バックエンド）

  - TODO 24-4-1: `src/phase4_retrieval.py`の`build_prompt()`に
                `response_language: str = "ja"`引数を追加し、末尾の回答言語
                指示を切り替える（比較表・詳細カルテ自体は日本語のままでよい）。
  - TODO 24-4-2: `generate_answer()`/`hybrid_search()`に同様に追加・伝播し、
                戻り値dictに`"response_language"`を追加する（Phase22/23の
                `embedding_source`と同じ慣習）。
  - TODO 24-4-3: `src/phase6_app.py`の`SearchRequest`/`SearchResponse`に
                `response_language`を追加し配線する（Phase23と同じパターン）。

### Step 24-5: フロントエンド最終配線・動作確認・記録

  - TODO 24-5-1: `frontend/src/api.ts`に`response_language`を追加し、
                `main.ts`の`runSearch()`で`store.get().language`を渡す。
  - TODO 24-5-2: `pixi run build`でビルド成功を確認する。
  - TODO 24-5-3: `pixi run dev` + `pixi run app`でブラウザから動作確認する
                （lang-toggle・地図凡例/ポップアップ・LLM回答英語化・
                日本語モード回帰なしを確認）。
  - TODO 24-5-4: 既知の制限をREADME.mdに追記する。
  - TODO 24-5-5: `docs/work_log.md`に記録しStep単位でgit commitする
                （コミット規則: `feat(phase24): <日本語概要>`）。

**検証方法:**
- Step 24-4: `response_language="en"`を指定した`hybrid_search()`呼び出しで
  回答が英語で返ることを確認
- Step 24-5: ブラウザから`lang-toggle`を操作し、静的UI・地図凡例・ポップアップ・
  候補建物リスト・LLM回答のすべてが英語表示に切り替わることを目視確認する

---

## Phase 25: 楕円形（オーバル）分類の追加とあいまい「円形」クエリの複数形状マッチ対応

承認日: 2026-08-28

> **背景:** ユーザーから「広島駅付近に楕円のような形状のビルがあったはず」との指摘があり、
> 実データで確認したところ、真円度（circularity）0.78〜0.82程度の丸みを帯びた convex な
> footprint（頂点数5〜6、convexity_ratio=1.0）が軒並み「矩形・単純形状」に誤分類されている
> ことが判明した。`circularity`（Phase20, `phase9_geometry.py:43`）は離心率の上昇に敏感な
> 指標のため、単一閾値では真円しか捉えられない（アスペクト比2:1の楕円で理論値0.84程度まで
> 低下する）。ユーザーとの合意により、「円形」「丸い」というあいまいな問い合わせは真円・
> 楕円の両方にヒットし、「真円」「正円」は真円のみ、「楕円」「オーバル」「小判型」は楕円の
> みに絞れるよう対応する。Phase20の`circularity>=0.85`判定ロジックは変更せず、楕円形
> カテゴリを追加する形で回帰リスクを避ける。

### 楕円判定の設計

新指標 `box_fill_ratio = footprint_area_m2 / bbox_area_m2` を追加する。`bbox_area_m2` は
`ST_MinimumRotatedRectangle`（DuckDB spatial に存在確認済み）による最小回転外接矩形の面積。
真円・楕円はアスペクト比に関わらず理論値 `π/4 ≈ 0.785` に収束し（離心率に依存しない）、矩形は
`box_fill_ratio ≈ 1.0` になる。`circularity`（離心率に敏感）では取れない「細長いが丸い」形状を、
`box_fill_ratio`（離心率に鈍感）で安定して拾う。Phase20の`circularity>=0.85`分岐より後に評価
するため、既存の「円形に近い」判定結果は変わらない。

### Step 25-1: 楕円形状判定ロジックの追加（`src/phase9_geometry.py`）
  - TODO 25-1-1: `fetch_footprint_shape()` に `ST_Area(ST_MinimumRotatedRectangle(...))
                 AS bbox_area_m2` を追加
  - TODO 25-1-2: `box_fill_ratio` を計算し `building_geom_meta` に `bbox_area_m2` /
                 `box_fill_ratio` カラムを追加保存
  - TODO 25-1-3: `estimate_shape_type()` に楕円形分岐を追加
                 （`circularity>=0.85` の直後、`concave_vertex_count==0` 判定の前）
  - TODO 25-1-4: `extract_geom_meta()` 再実行、`box_fill_ratio` 分布を確認して
                 `_OVAL_BOX_FILL_MIN`/`MAX`（仮値0.70〜0.85）を確定。既存「円形に近い」9件が
                 不変であることを確認

### Step 25-2: クエリ解析・SQLフィルタの複数形状対応
  - TODO 25-2-1: `query_parser.py` の `ParsedQuery.footprint_shape` を `str|None` →
                 `list[str]` に変更、`_SHAPE_VALUES` に「楕円形」追加
  - TODO 25-2-2: `_RESPONSE_SCHEMA["footprint_shape"]` を配列型に変更
  - TODO 25-2-3: `_SHAPE_RULES` 更新（「真円/正円」→["円形に近い"]、
                 「円形/丸い」→["円形に近い","楕円形"]、「楕円/オーバル/小判型」→["楕円形"]）
  - TODO 25-2-4: `phase10_router.py` の `build_filter_clauses()` を
                 `shape_type_est = ?` → `IN (...)` に変更
  - TODO 25-2-5: `verify_candidates()` を `isin()` ベースに変更

### Step 25-3: テスト・サニティチェックの更新
  - TODO 25-3-1: `tests/gold_set.py` に G40（楕円形）・G41（丸い＝複数マッチ）を追加
                 （既存 G37〜G39 は変更なし＝回帰確認用）
  - TODO 25-3-2: `tests/sanity_checks.py` に `check_phase21_ellipse_shape()` /
                 `run_phase21_checks()`（`--phase21`）を追加

### Step 25-4: 動作確認
  - TODO 25-4-1: `pixi run python src/phase9_geometry.py` で再構築、
                 `--phase20`/`--phase21` サニティチェック実行
  - TODO 25-4-2: `pixi run dev` + `pixi run app` でUIから
                 「広島駅付近で円形の建物を探して」（楕円もヒット）、
                 「広島駅付近で真円の建物を探して」（従来通り0件）、
                 「楕円形の建物を教えて」を確認

---

## Phase 26: 視覚デザイン刷新（改名・レスポンシブ改善込み）

承認日: 2026-08-28

> **背景:** FOSS4G向けにチャットUIのスクリーンショットを見たユーザーから、以下の
> フィードバックがあった: (1) 言語トグルボタン（「日本語」）がアイコン用の正方形
> ボタンに収まらず2行に折り返され切り替え方法が分かりにくい（Phase24のCSS不具合）、
> (2) アプリ名を「City RAG Example」に統一したい（日英とも同じ表記）、
> (3) デザイン全体が「微妙」——チャット画面全体の視覚デザインを見直したい（大規模）、
> (4) スマホでも見やすい/分かりやすいUI/UXにしたい。
>
> 現状のUIはMaterial Design風の量産型デザイン（角丸8-16px、青#1565c0アクセント、
> システムフォント）で、FOSS4G（GIS専門家向け国際会議）の場で「量産AIチャット感」に
> 見えてしまうリスクがある。`frontend-design`スキルの指針に従い、被写体（広島の
> PLATEAU 3D建物データ×災害リスク×測位）に根ざした固有のビジュアルアイデンティティを
> 与える。

> **デザイン方針（トークンシステム）:**
>
> 方向性は「測量機器・地図計測器」——このアプリが実際にやっていること
> （距離・浸水深・高さを測る）をそのままビジュアルの語彙にする。クリシェ的な
> AI御三家（クリーム+セリフ+テラコッタ／黒背景+ネオンアクセント／新聞風罫線）は
> 避け、"計測の道具"としての質感（モノスペース数値、目盛り、罫線）を意味のある
> 構造として使う。
>
> カラー（ライトモード。ダークモードは反転トークンを用意）:
> `--ink: #12222B`（本文）、`--paper: #F2F5F4`（背景、寒色寄りのペーパーグレー）、
> `--paper-raised: #FFFFFF`（浮き上がり面）、`--depth: #0E7C86`（プライマリ
> アクセント、浸水深を想起するティール）、`--depth-strong: #075E66`
> （hover/active）、`--flag: #E8862B`（推薦バッジ等、測量旗の温色アクセント）。
> リスク色（高潮/洪水/津波）は現行の役割を維持しつつパレットと調和する色相に微調整。
>
> タイポグラフィ（Google Fonts）: 見出し・ブランドワードマーク（英語のみ）は
> **Space Grotesk**、本文・日本語見出しは**Zen Kaku Gothic New**、データ表示
> （建物ID・距離・スコア・座標・件数）は**JetBrains Mono**。
>
> シグネチャ要素は「目盛り（スケールバー）」モチーフ——ウェルカム画面の見出し下の
> 区切り線と、言語/テーマ切り替えのセグメントコントロールに適用する唯一の
> ビジュアル的な冒険とし、他の要素は抑制的に整える。
>
> レイアウト構造（チャット+地図の分割パネル、768px/1024pxブレークポイント）は
> 機能的に妥当なため維持し、配色・タイポ・間隔・角丸・ボーダーとモバイルでの
> 詰まり・折り返し不具合を見直す。

### Step 26-1: デザイントークン刷新（style.css）

  - TODO 26-1-1: `frontend/src/style.css`の`:root`/`[data-theme="light"]`/
                `[data-theme="dark"]`カラートークンを上記パレットに置き換える。
                `--accent`系変数名はそのまま維持し値のみ変更する
                （呼び出し側の変数名変更を避け、影響範囲を限定する）。
                ダークモードは`--ink`/`--paper`を反転させた等価トークンを設計する
                （既存のコントラスト比要件・WCAG AA基準を維持すること）。
  - TODO 26-1-2: `frontend/index.html`の`<head>`にGoogle Fontsの`<link>`
                （Space Grotesk / Zen Kaku Gothic New / JetBrains Mono、
                日本語ウェイト400/500/700・英語ウェイト400/500/700を選択的に
                指定）を追加する。`preconnect`も付与する。
  - TODO 26-1-3: `body`のフォントスタックを`"Zen Kaku Gothic New", "Hiragino
                Sans", "Noto Sans JP", sans-serif`に変更する。`.app-title`・
                見出し系（`welcome-msg__title`等）に`font-family: "Space
                Grotesk", ...`を適用する対象を洗い出し、英語表記のみの要素
                （ブランド名等）に限定して適用する。建物ID・距離・座標・
                スコア等の既存`font-family: monospace`指定箇所を
                `"JetBrains Mono", ui-monospace, monospace`に置き換える。

### Step 26-2: 言語/テーマ切り替えの不具合修正とヘッダー再構成

  - TODO 26-2-1: `frontend/index.html`の`lang-toggle`/`theme-toggle`を、
                `.btn--icon`（44×44px固定）ではなく可変幅の新クラス
                `.btn--toggle`に変更する（`width: auto`, `white-space:
                nowrap`, 適切なpadding）。両ボタンをセグメントコントロール風の
                グループ（`.toggle-group`）にまとめ、シグネチャ要素の目盛り
                モチーフ（区切りの縦罫線+小さな目盛り装飾）を適用する。
  - TODO 26-2-2: `frontend/src/style.css`にこれらのスタイルを実装する。
                モバイル幅（375px相当）でボタン群が折り返さずヘッダー内に
                収まることを確認する（必要ならヘッダー高さ可変・タイトル
                省略表示を調整）。
  - TODO 26-2-3: ヘッダーに小さなアイキャプション（例:
                "HIROSHIMA · PLATEAU 3D BUILDING SEARCH"、モノスペース・
                トラッキング広め・小さいサイズ）を追加する。単なる装飾ではなく
                データソースと対象範囲を示す実用的なラベルとする。
                `data-i18n`で日英切り替え対応する。

### Step 26-3: アプリ名の変更

  - TODO 26-3-1: `frontend/src/i18n.ts`の`appTitle`キーを`ja`/`en`とも
                「City RAG Example」に統一する（絵文字は付けず、Space
                Groteskのワードマークのみで見せる。既存の🏢絵文字は削除し、
                タイポグラフィそのものをブランドの顔にする）。
  - TODO 26-3-2: `frontend/index.html`の`<title>`タグ・`<meta
                name="description">`を更新する。`src/phase6_app.py`の
                `FastAPI(title="PLATEAU RAG API", ...)`は内部API仕様名であり
                ユーザー向け表示名ではないため変更対象外とする。

### Step 26-4: ウェルカム画面・メッセージ・入力エリアの再デザイン

  - TODO 26-4-1: `.welcome-msg`を再デザインする。見出し下にシグネチャの
                目盛り区切り線（`.scale-divider`、CSS `linear-gradient`や
                疑似要素で目盛りを表現、装飾のみでDOM要素追加は最小限にする）
                を追加する。サンプル質問ボタン（`.example-btn`）の角丸・
                ボーダー・ホバー色を新トークンに合わせて整える。
  - TODO 26-4-2: メッセージバブル（`.msg__bubble`等）・地図ボタン
                （`.btn--map-toggle`）・候補建物リスト（`.building-item`）・
                リスクバッジ（`.risk-badge--*`）の配色・角丸・ボーダーを
                新トークンに統一する（ユーザーバブルの水色→ティール系に変更等）。
  - TODO 26-4-3: 入力エリアのオプション行（`.input-options`、モデル/件数/
                埋め込み選択）をモバイル幅でも詰まらないよう再構成する
                （ラベルを大文字small-caps・モノスペースにする、狭幅では
                2行グループ化するflex-wrap調整、各selectのタップ領域を
                44px以上確保）。
  - TODO 26-4-4: 地図オーバーレイ（`.map-overlay`・凡例・出典表記）・
                MapLibreポップアップの配色を新トークンに統一する。

### Step 26-5: レスポンシブ確認・記録

  - TODO 26-5-1: `pixi run build`でビルド成功を確認する。
  - TODO 26-5-2: `pixi run build && pixi run app`でブラウザから確認する
                （resize_windowで375px/768px/1280px幅、ライト/ダーク、
                日本語/英語の組み合わせを一通りチェックし、折り返し・
                はみ出し・タップ領域不足がないことを確認する）。
  - TODO 26-5-3: `docs/work_log.md`に記録し、Step単位でgit commitする
                （コミット規則: `feat(phase26): <日本語概要>`）。

**検証方法:**
- Step 26-1〜26-4: `pixi run build`でビルド成功
- Step 26-5: `resize_window`で375px（モバイル）・768px（タブレット）・
  1280px（デスクトップ）× ライト/ダーク × 日本語/英語 の組み合わせで
  スクリーンショットを撮り、折り返し・はみ出し・コントラストを目視確認する

---

## Phase 27: モバイル地図のボトムシート化

承認日: 2026-08-28

> **背景:** PC（左: 地図、右: チャット）は現状維持でよいとのユーザー確認が
> 得られた。一方モバイル（<768px）は現状、地図を「フルスクリーンへの画面遷移」
> （`.panel-map.fullscreen`、`position:fixed;inset:0`、`history.pushState`で
> 戻るボタン連動）として実装しており、チャットと地図を同時に見比べられず、
> 地図の存在にも気づきにくい。これを、チャットを見ながら下からのぞける
> 「ボトムシート」パターンに置き換える。対象は**モバイル幅（<768px）のみ**。
> タブレット（768–1023px、地図をインライン300pxで展開）・デスクトップ
> （左右分割）は変更しない。
>
> **設計議論（重要）:** 「チャットを土台・地図をボトムシート」と「地図を
> 土台・チャットをボトムシート」の2案を比較検討した。後者はFOSS4G
> （GIS系カンファレンス）のデモとして見栄えが良い一方、検索前は地図に
> 表示するものがなく、かつ最初にすべき操作（質問入力）がシートの奥に
> 隠れて気づきにくいという欠点がある。本アプリの主操作は「自然言語で
> 質問する」ことであり、地図はその結果を確認する副次的手段（RAGの実現に
> 比べれば優先度は低い）という位置づけであるため、**「チャットを土台・
> 地図をボトムシート」を採用する**。

> **設計方針:**
> - 3段階のスナップ高さ: `peek`（つまみ+件数のみ、約72px）／`half`
>   （画面高の50%）／`full`（画面高の90%）。`hidden`（非表示、初期状態）を
>   加えた4状態を`store.ts`の`mapSheetState`で管理する。
> - 自動peek表示: モバイルで検索結果（候補>0件）が得られたとき、シートが
>   `hidden`であれば自動的に`peek`状態で表示する。**ただしユーザーが既に
>   シートを`peek`より広げている場合（`half`/`full`）は、その状態を維持し
>   `peek`に戻さない**——地図を開いたまま追加で質問する使い方を妨げないため。
> - peek帯全体をタップ可能にする: つまみ単体（小さい）だけをタップ領域に
>   すると狙いにくいため、peek状態の帯全体（44px以上の高さ）をタップで
>   `half`へ展開できるようにする。
> - チャット内の「🗺 地図でN件を確認」ボタンは、シートを`half`まで展開する
>   動作に変更する（現行のfullscreen遷移をやめる）。
> - ドラッグ操作: つまみをPointer Eventsでドラッグすると自由な高さに追従し、
>   指を離すと最も近いスナップポイントへスナップする。
> - 非ドラッグ操作（アクセシビリティ）: つまみのタップで`peek⇔half`を
>   トグルし、明示的な展開/格納ボタンも併設する。既存の`map-close-btn`は
>   「シートを`hidden`に戻す」動作を維持する。
> - 高さ変更のたびに`resizeMap()`を呼ぶ（ドラッグ中はrAFでスロットル、
>   スナップの`transitionend`でも1回呼ぶ）。
> - 既存のfullscreen/pushState/popstateは撤去する（ボトムシートは画面遷移
>   ではなく同一画面内のUI状態変化のため、ブラウザ履歴との連動は不要）。

### Step 27-1: ボトムシートのHTML/CSS実装

  - TODO 27-1-1: `frontend/index.html`の`map-mobile-header`を、モバイル用の
                シートヘッダー（つまみ`.map-sheet__handle` + 件数表示 +
                展開/格納ボタン + 既存の閉じるボタン）を含む構造に拡張する
                （`map-back-btn`の「← 戻る」は撤去し、格納ボタンに統合する）。
  - TODO 27-1-2: `frontend/src/style.css`の`@media (max-width: 767px)`
                ブロック内で、`.panel-map`を`fullscreen`固定オーバーレイ
                から`position: fixed; left:0; right:0; bottom:0;`かつ
                `height`を状態別（`--sheet-peek: 72px`, `--sheet-half: 50vh`,
                `--sheet-full: 90vh`）に切り替えるボトムシートスタイルに
                変更する。`transition: height 0.25s`、角丸上部・box-shadowで
                シートらしい見た目にする。`mapSheetState==='hidden'`時は
                `height:0`にする。
  - TODO 27-1-3: つまみ（`.map-sheet__handle`）の見た目（中央の横棒
                グラバー）と、展開/格納ボタンのスタイルを実装する。
                `peek`状態の帯全体（`.map-sheet__peek-bar`、高さ44px以上）を
                クリック/タップ領域とし、クリックで`half`へ展開する。

### Step 27-2: ドラッグ操作とスナップの実装

  - TODO 27-2-1: `frontend/src/map.ts`または新規`frontend/src/sheet.ts`に
                ドラッグロジックを実装する: `pointerdown`でドラッグ開始・
                現在の高さを記録、`pointermove`で`clientY`の差分から
                高さを直接更新（`requestAnimationFrame`でスロットルし
                `resizeMap()`を呼ぶ）、`pointerup`で3スナップポイント
                （peek/half/full）のうち最も近い高さへ`mapSheetState`を
                確定し、CSS transitionでアニメーションさせる。
                `touch-action: none`をつまみに指定しスクロールとの
                競合を防ぐ。
  - TODO 27-2-2: スナップ確定後の`transitionend`イベントで`resizeMap()`を
                もう一度呼ぶ。

### Step 27-3: 検索結果との連動・状態管理の置き換え

  - TODO 27-3-1: `frontend/src/store.ts`の`AppState`に
                `mapSheetState: 'hidden' | 'peek' | 'half' | 'full'`を追加し
                初期値`'hidden'`とする。
  - TODO 27-3-2: `frontend/src/main.ts`の`openMap()`を、モバイル分岐で
                「`mapSheetState`を指定状態にする」新規関数
                `setMapSheetState(state)`呼び出しに置き換える。
                `history.pushState`・`popstate`関連の既存コードを撤去する
                （タブレット/デスクトップ分岐の`.visible`トグルは無改修）。
  - TODO 27-3-3: `runSearch()`内、検索結果取得後
                （`result.candidate_count > 0`）にモバイル判定を追加し、
                **現在の`mapSheetState`が`'hidden'`の場合のみ**
                `setMapSheetState('peek')`を呼ぶ。
  - TODO 27-3-4: チャット内の`.btn--map-toggle-top`（`chat.ts`）のクリック
                ハンドラを、モバイルでは`setMapSheetState('half')`、
                PC/タブレットでは既存の`openMap()`を呼ぶよう分岐させる。

### Step 27-4: アクセシビリティ・多言語対応

  - TODO 27-4-1: つまみには複雑なslider相当のセマンティクスを付与せず、
                独立した展開/格納ボタン（`aria-label`で「地図を広げる/
                縮める」）を実装し、キーボード・スクリーンリーダーの
                主経路とする。`aria-expanded`をシート状態に応じて更新する。
  - TODO 27-4-2: `frontend/src/i18n.ts`に新規文言を追加する:
                シート状態変更のannounceメッセージ、展開/格納ボタンの
                aria-label、つまみのaria-label。日英両方定義する。

### Step 27-5: 動作確認・記録

  - TODO 27-5-1: `pixi run build`でビルド成功を確認する。
  - TODO 27-5-2: `resize_window`でモバイル幅（375px）に設定し、
                `pixi run app`で実際に検索を実行して、検索後の自動peek
                表示・地図ボタンでのhalf展開・つまみドラッグでの
                スナップ・格納ボタンでの`hidden`復帰・`resizeMap()`連動を
                確認する。
  - TODO 27-5-3: タブレット（768px）・デスクトップ（1280px）で既存動作に
                回帰がないことを確認する。
  - TODO 27-5-4: `docs/work_log.md`に記録しStep単位でgit commitする
                （コミット規則: `feat(phase27): <日本語概要>`）。

**検証方法:**
- Step 27-1〜27-4: `pixi run build`でビルド成功
- Step 27-5: `pixi run dev` + `pixi run app`でブラウザから実際に検索を行い、
  モバイル幅（375px）でボトムシートの自動peek表示・ドラッグ・スナップ・
  格納ボタンの動作を確認する。タブレット・デスクトップ幅での回帰がないことも
  確認する。

---

## Phase 28: 最上級クエリ（一番高い等）の推薦をコード側で確定させる

承認日: 2026-08-28

> **背景（不具合報告）:**
> 「What is the tallest building around Hiroshima Station?」で、検索候補の1位
> （97.4m、`ORDER BY measured_height DESC`で確定済み）ではなく2位（90.9m）が
> LLMの回答として推薦される不具合が発生した。
>
> 調査の結果、`query_parser.py`の解析（`sort_by={key: measured_height, order: desc}`）
> と `phase10_router.py` の SQL `ORDER BY` 構築（292〜314行目）はいずれも正しく、
> `hybrid_search()` に渡る `candidates` DataFrame は常に正しい降順であることを
> 直接実行で確認済み。原因は `build_prompt()`（`src/phase4_retrieval.py:414`）が
> 「表がその順に並んでいる」旨を伝える `sort_note` を付けるのみで、
> 「表の1位を推薦せよ」という確定的な指示になっておらず、プロンプト本文も
> 「ユーザーの質問に最も合致する建物を**選定**し」とLLMの自由裁量に委ねる
> 書き方だったため。CLAUDE.mdの設計方針（構造化条件はSQLで確定判定し、LLMの
> 推論に委ねない）に反する抜け穴だった。
>
> **方針:** `sort_by` が設定されている場合に限り、推薦対象をコード側
> （比較表の1位）で確定し、LLMの役割は「その建物についての理由説明」に限定する。

### Step 28-1: プロンプト改修（sort_by時に1位建物を確定指示）

  - TODO 28-1-1: `build_prompt()`（`src/phase4_retrieval.py`）で、`sort_by is not None`
                の場合に `candidates.iloc[0]` のIDを `top_id` として取得し、
                プロンプト本文に「必ず比較表1位（`{top_id}`）を推薦すること。
                他の建物を推薦してはならない」という確定的な指示を追加する。
                次点2件（2位・3位）のID・順位もコード側で明示する。
  - TODO 28-1-2: 既存の `sort_note` ・ `recommend_count_rule` は残しつつ、
                「1位を確定的に選ぶ」指示を明確に追加する形で統合する。
  - TODO 28-1-3: `sort_by` 指定時、LLM回答冒頭で言及された建物IDが `top_id` と
                一致するかを確認するログ出力（不一致ならワーニングのみ、
                回答は改変しない）を追加する。

### Step 28-2: 検証

  - TODO 28-2-1: `tests/sanity_checks.py` に、`sort_by` が設定される代表クエリ
                （日本語「広島駅付近で一番高い建物を教えて」、英語
                "What is the tallest building around Hiroshima Station?"）で
                `hybrid_search()` をフル実行し、LLM回答冒頭の建物IDが候補1位の
                IDと一致することを確認する関数を追加する。
  - TODO 28-2-2: 上記テストを実行しパスすることを確認する。
  - TODO 28-2-3: `tests/eval_retrieval.py` の既存gold_setクエリ（G01等、
                sort_by系）で回帰がないことを確認する。

### Step 28-3: 記録・コミット

  - TODO 28-3-1: `docs/work_log.md` に不具合の原因・対応内容・検証結果を記録する。
  - TODO 28-3-2: `git commit -m "fix(phase28): 最上級クエリの推薦をコード側で1位に確定"`

**検証方法:**
- `tests/sanity_checks.py` の新規関数を実行し、日英の再現クエリで正しい建物
  （比較表1位）が推薦されることを確認する。
- `tests/eval_retrieval.py` のsort_by系gold queryで回帰がないことを確認する。

### Step 28-5: その他の言語連動漏れの一括修正

  - TODO 28-5-1: `phase4_retrieval.py`の候補0件時メッセージ
                （「候補建物が見つかりませんでした。クエリや検索範囲を
                変更してください。」）を`response_language`で切り替える。
  - TODO 28-5-2: `validate_answer()`にハルシネーション検知注記の英語版を追加し、
                `response_language`引数を追加、`hybrid_search()`の呼び出しに
                `response_language`を渡す。
  - TODO 28-5-3: `query_parser.py`の`parse_query()`に`response_language: str
                = "ja"`引数を追加し、`response_language=="en"`の場合のみ
                「clarification_questionを設定する場合は英語で記述すること」
                という追加指示をプロンプトに付与する。`hybrid_search()`から
                `parse_query(query, response_language=response_language)`
                で呼び出す。
  - TODO 28-5-4: `phase6_app.py`の空クエリ400エラーメッセージも
                `req.response_language`で切り替える（現状フロントエンドで
                未到達だが同種の修正として揃える）。
  - TODO 28-5-5: 日英それぞれで、0件クエリ・確認質問誘発クエリ・
                ハルシネーション模擬（候補外IDを含む回答を手動構築）を
                実行し、すべて指定言語で出力されることを確認する。
  - TODO 28-5-6: `docs/work_log.md`に記録し、
                `git commit -m "fix(phase28): 候補0件・確認質問・幻覚注記の英語UI未対応を修正"`

---

## Phase 29: レイテンシ改善（リトライ短縮 + 回答生成・クエリ解析モデル軽量化）

承認日: 2026-08-29

> **背景（調査結果）:**
> 質問から回答までが遅いという指摘を受け、Explore調査を実施。
> `/api/search` → `hybrid_search()`（`src/phase4_retrieval.py:703`）の処理は
> クエリ解析(LLM) → ジオコーディング → ルート分類 → クエリ埋め込み(API) →
> DuckDB検索 → 候補検証 → 回答生成(LLM) → バリデーションの順に**完全に直列**
> 実行されている。ボトルネックは影響度順に
> ①LLM呼び出しの直列化（クエリ解析・回答生成で最低2回）、
> ②リトライの指数バックオフ（埋め込み10s→20s、回答生成15s→30s、
> クエリ解析5s→10s。API不調時にワーストケースが数十秒〜1分超）、
> ③Nominatim外部APIキャッシュなし、④埋め込みAPIキャッシュなし、と特定した。
> 本Phaseでは費用対効果が高く低リスクな「リトライ短縮」と「回答生成・クエリ
> 解析モデルの軽量化（`gemini-3.5-flash-lite`）」に着手する。embeddingの
> RURI軽量版デフォルト化・並列化は別Phaseで対応する。

### Step 29-1: リトライ待機時間の短縮
  - TODO 29-1-1: `src/query_parser.py:526`の`wait = 5 * (attempt + 1)`を
                `wait = 2 * (attempt + 1)`に短縮する（`parse_query()`）。
  - TODO 29-1-2: `src/phase4_retrieval.py:102`の`wait = 10 * (attempt + 1)`を
                `wait = 3 * (attempt + 1)`に短縮する（`embed_query()`）。
  - TODO 29-1-3: `src/phase4_retrieval.py:620`の`wait = 15 * (attempt + 1)`を
                `wait = 3 * (attempt + 1)`に短縮する（`generate_answer()`）。
  - TODO 29-1-4: 変更後、通常時（API成功時）のレイテンシに影響がないこと
                （リトライは失敗時のみ発火するロジックであること）をコード
                レビューで確認する。

### Step 29-2: 回答生成・クエリ解析モデルを gemini-3.5-flash-lite に切替
  - TODO 29-2-1: `src/phase4_retrieval.py:636`の`_generate_with_gemini()`内、
                `model="gemini-2.5-flash"`を`model="gemini-3.5-flash-lite"`
                に変更する。
  - TODO 29-2-2: `src/query_parser.py:442`の`parse_query()`内、
                `model="gemini-2.5-flash"`を`model="gemini-3.5-flash-lite"`
                に変更する。
  - TODO 29-2-3: `tests/eval_retrieval.py`の既存ゴールドセットで切替前後の
                回答品質（数値引用精度・幻覚率・JSON解析成功率）を比較する。
  - TODO 29-2-4: 切替前後のレイテンシ（クエリ解析・回答生成それぞれの所要
                時間）を実測し、`docs/work_log.md`に記録する。

### Step 29-3: サニティチェック・記録
  - TODO 29-3-1: 変更後、通常クエリ（例:「広島駅周辺で一番高い建物は？」）
                1件で動作確認し、タイムアウト・回答内容・建物ID引用が
                正常であることを確認する。
  - TODO 29-3-2: `docs/work_log.md`にStep 29-1〜29-2の結果とコミットハッシュ
                を記録し、`git commit -m "perf(phase29): リトライ短縮と
                gemini-3.5-flash-lite化でレイテンシを改善"`する。

**検証方法:**
- Step 29-1: コードレビューで通常時レイテンシに影響しないことを確認
- Step 29-2: `tests/eval_retrieval.py`実行結果（品質）+ 実測レイテンシ比較
- Step 29-3: 実クエリでの動作確認

---

## Phase 30: クエリ側embeddingの高速化（RURIデフォルト化）+ スマホ実機デモ対応

承認日: 2026-08-29

> **背景:** ユーザーからスマホでの実機デモ要望を受け、クエリ側embeddingの
> 高速化を検討。実測比較の結果、`gemini-embedding-001`（API）が1.254秒/件
> なのに対し、`ruri-v3-310m`（ローカル、ウォーム後）は0.085秒/件と約15倍
> 高速であることを確認した（Phase21のベンチマーク記録1.2秒/件はドキュメント
> 側の長文バッチエンコードの数値であり、短いクエリ単発推論とは条件が異なる
> ことも判明）。ドキュメント側（`building_chunks_ruri_embed`、2,958件）は
> Phase22で既にRURI v3 310mで構築済みのため、再埋め込みは不要。ただし
> クエリ側とドキュメント側は同一モデルサイズ（310m）で統一する必要がある
> （異なるサイズは別のベクトル空間になるため混在不可）。また、モデルの
> コールドスタート（サーバー起動後の初回ロード）に約11秒かかることを確認、
> デモでの初回ユーザー体験を損なわないようプリウォーム対応が必要。
> アーキテクチャ上、スマホはブラウザでサーバー（PC上のFastAPI）にアクセス
> するのみで、RURIモデル自体はスマホ上では動作しない（サーバー側で完結）。
> デプロイ先（クラウド/ローカルネットワーク等）の検討は別途後日行う。

### Step 30-1: デフォルトをRURIに変更
  - TODO 30-1-1: `src/phase4_retrieval.py`の`hybrid_search()`の
                `embedding_source: str = "gemini"`を`"ruri"`に変更する。
  - TODO 30-1-2: `src/phase6_app.py`の`SearchRequest.embedding_source`の
                デフォルトを`"gemini"`から`"ruri"`に変更する。
  - TODO 30-1-3: `frontend/src/store.ts`の`settings`初期値
                `embeddingSource: 'gemini'`を`'ruri'`に変更する。

### Step 30-2: サーバー起動時プリウォーム
  - TODO 30-2-1: `src/phase6_app.py`にFastAPIの`startup`イベントハンドラを
                追加し、`embed_query_ruri()`をダミーテキストで1回呼び出して
                モデルロード（約11秒）をサーバー起動時に完了させる
                （デモ本番中の初回クエリで11秒待たされることを防ぐ）。

### Step 30-3: 検証
  - TODO 30-3-1: `pixi run python tests/eval_retrieval.py --ruri`を実行し、
                Phase29時点の結果と比較して回帰がないことを確認する
                （structured経路が大半のため数値上の変化はほぼないはずだが、
                念のため確認する）。
  - TODO 30-3-2: semantic/hybrid経路を通る実クエリ（例:「日当たりのよい
                建物」「公園に隣接していて眺めのよい高い建物」）を
                `embedding_source`未指定（デフォルト値）で実行し、
                速度・回答品質を確認する。
  - TODO 30-3-3: `pixi run dev` + `pixi run app`でフロントエンドを起動し、
                `resize_window`でモバイル幅（375px）にして実際に検索を行い、
                デフォルトでRURIが使われていること・地図表示に問題がない
                ことを確認する。

### Step 30-4: サニティチェック・記録
  - TODO 30-4-1: `docs/work_log.md`にStep 30-1〜30-3の結果とコミット
                ハッシュを記録し、`git commit -m "perf(phase30): クエリ
                embeddingをRURIデフォルト化しプリウォームを追加"`する。

**検証方法:**
- Step 30-1/30-2: コードレビューで変更箇所を確認
- Step 30-3: `eval_retrieval.py --ruri`の回帰確認 + 実クエリでの速度・
  品質確認 + モバイル幅ブラウザでの実機相当確認

---

## Phase 31: 未使用のClaude Sonnet選択機能を削除

承認日: 2026-08-29

> **背景:** ユーザーから「モデルは`Gemini 3.5 Flash Lite`しか使っていないと
> 思うが、モデル選択処理・UIは不要では」との指摘。調査の結果、
> `model_provider="claude"`はUIのドロップダウン以外（eval/testスクリプト・
> FOSS4G発表資料）から一切呼ばれておらず、実質未使用と判明。完全削除する
> 方針で合意（UI・バックエンドパラメータ・`_generate_with_claude()`関数・
> `ANTHROPIC_API_KEY`依存を全て削除し、gemini固定にする）。

### Step 31-1: バックエンドの削除
  - TODO 31-1-1: `src/phase4_retrieval.py`の`generate_answer()`から
                `model_provider`引数を削除し、常に`_generate_with_gemini()`
                を呼ぶよう簡素化する。`_generate_with_claude()`関数を削除する。
  - TODO 31-1-2: `hybrid_search()`から`model_provider`引数を削除し、
                返却dictの`"model_provider"`キーも削除する（またはgemini固定
                文字列に簡素化。呼び出し元への影響を確認して判断）。
  - TODO 31-1-3: `src/phase6_app.py`の`SearchRequest.model_provider`・
                `SearchResponse.model_provider`フィールドを削除し、
                `hybrid_search()`呼び出し・レスポンス構築から該当箇所を除去する。

### Step 31-2: フロントエンドの削除
  - TODO 31-2-1: `frontend/index.html`の`model-select`（ラベル+セレクト）
                の`<div class="input-options__group">`ブロックを削除する。
  - TODO 31-2-2: `frontend/src/store.ts`の`Settings.modelProvider`
                フィールドと初期値を削除する。
  - TODO 31-2-3: `frontend/src/api.ts`の`model_provider`フィールド
                （リクエスト・レスポンス型）を削除する。
  - TODO 31-2-4: `frontend/src/main.ts`の`modelSelect`要素取得・
                changeイベントリスナー・`search()`呼び出しの
                `model_provider`引数を削除する。
  - TODO 31-2-5: `frontend/src/i18n.ts`の`modelLabel`・
                `modelSelectAriaLabel`キー（日英両方）を削除する。

### Step 31-3: 周辺ファイルの整合性修正
  - TODO 31-3-1: `tests/sanity_checks.py`の`model_provider="gemini"`引数を
                削除する（`hybrid_search()`のシグネチャ変更に追従）。
  - TODO 31-3-2: `README.md`のClaude Sonnet言及箇所（パイプライン図・
                設定表・curl例・レスポンス例・技術スタック表）を
                gemini固定の記述に更新する。
  - TODO 31-3-3: `.env`の`ANTHROPIC_API_KEY`は削除せず残す（他の目的で
                将来必要になる可能性があり、CLAUDE.mdの環境変数定義を
                勝手に変更しない）。

### Step 31-4: 検証・記録
  - TODO 31-4-1: `pixi run python tests/sanity_checks.py`
                （関連フェーズ分）を実行し、`model_provider`引数削除後も
                回帰がないことを確認する。
  - TODO 31-4-2: `pixi run build`でフロントエンドを再ビルドし、
                型エラーがないことを確認する。
  - TODO 31-4-3: `resize_window`でモバイル幅にし、実際に検索を実行して
                モデル選択UIが表示されないこと・検索が正常動作すること
                を確認する。
  - TODO 31-4-4: `docs/work_log.md`に記録し、`git commit -m "refactor
                (phase31): 未使用のClaude Sonnet選択機能を削除"`する。

**検証方法:**
- Step 31-1〜31-3: コードレビューで削除漏れがないことを確認
- Step 31-4: サニティチェック・ビルド成功・モバイル幅ブラウザでの動作確認

---

## Phase 32: ディレクトリ再編成 + Cloudflare Containers デプロイ対応

承認日: 2026-08-29

> **背景:** 現在のソースコードは`src/phase1_investigate.py`〜`src/phase22_ruri_embed.py`のように、
> CLAUDE.mdの開発プロセス(Phase>Step>TODO)由来のフェーズ番号がファイル名にそのまま残っており、
> 本番運用するプロダクトのモジュール名としては読みにくい。ユーザーから「全体的にリファクタリング
> したい」との要望があり、あわせてスマホ実機デモを常時公開できるようデプロイ先を検討した結果、
> **Cloudflare Containers**(Docker基盤、月$5〜、予算$10以内)に決定した。Vercel(Python Functions)
> も比較検討したが、①DuckDB接続が書き込み前提(mkdir・HNSW永続化設定)でVercelの読み取り専用
> ファイルシステムと相性が悪い、②Phase30のlifespanプリウォームがサーバーレスのコールドスタート
> モデルでは実質機能しない、という2つの本質的なアーキテクチャ不一致が判明したため。Cloudflare
> Containersは「普通の永続コンテナ」なのでこの2問題が発生せず、現アーキテクチャをほぼ活かせる。
> あわせてユーザー要望により、コード内コメント・docstringの英語化(Googleスタイル)、循環的複雑度
> 10〜15/認知的複雑度10程度を目安とした関数分割も本Phaseで実施する。
> 詳細計画: `C:\Users\pikkarin\.claude\plans\hashed-purring-rocket.md`(plan mode 作成)

### Step 32-1: 共通DB接続モジュールの切り出し
  - TODO 32-1-1: `src/common/db.py`を新規作成し、`phase3_enrichment.py`の
                `RAG_DB_PATH`・`connect_rag()`、`phase2_spatial.py`の
                `wgs84_to_epsg6671()`を移設する。
  - TODO 32-1-2: 移設した関数のdocstringをGoogleスタイル英語に書き直す。

### Step 32-2: パイプライン系モジュールの移動・リネーム
  - TODO 32-2-1: `src/pipeline/`ディレクトリを新規作成し、以下の対応で
                ファイルを移動する:
                `phase1_investigate.py→pipeline/investigate.py`,
                `phase2_spatial.py→pipeline/gpkg.py`(db.pyに移した関数を除く),
                `phase3_enrichment.py→pipeline/enrichment.py`(同上),
                `phase9_geometry.py→pipeline/geometry.py`,
                `phase13_context.py→pipeline/context.py`,
                `phase22_ruri_embed.py`の`build_ruri_index()`→
                `pipeline/ruri_embed.py`,
                `codelist_loader.py→pipeline/codelist_loader.py`。
  - TODO 32-2-2: 各ファイルのdocstring・コメントを英語Googleスタイルに
                書き直す。`radon cc -s`で循環的複雑度を計測し、15を超える
                関数があれば分割する。

### Step 32-3: ランタイムAPI系モジュールの移動・リネーム
  - TODO 32-3-1: `src/app/`ディレクトリを新規作成し、以下の対応で
                ファイルを移動する:
                `phase6_app.py→app/main.py`,
                `phase4_retrieval.py→app/retrieval.py`,
                `phase10_router.py→app/router.py`,
                `phase11_hybrid_search.py→app/search_fusion.py`
                (retrieval.hybrid_search()との名前衝突回避のため改名),
                `query_parser.py→app/query_parser.py`,
                `geocoder.py→app/geocoder.py`,
                `phase22_ruri_embed.py`の`embed_query_ruri()`→
                `app/ruri_query.py`。
  - TODO 32-3-2: 各ファイルのdocstring・コメントを英語Googleスタイルに
                書き直す。`radon cc -s`で循環的複雑度を計測し、15を超える
                関数があれば分割する(`hybrid_search()`等、外部呼び出し
                関数のシグネチャは変更しない)。

### Step 32-4: import解決方式の統一
  - TODO 32-4-1: `sys.path.insert` + try/except の二重import形式を廃止し、
                `src/`・`src/common/`・`src/pipeline/`・`src/app/`に
                `__init__.py`を追加してパッケージ化する。
  - TODO 32-4-2: 全ファイルのimport文を`from src.app.retrieval import
                hybrid_search`のような一貫した絶対importに書き換える。

### Step 32-5: 周辺ファイルの追従
  - TODO 32-5-1: `pixi.toml`の5タスク定義(`investigate`/`spatial`/
                `enrich`/`search`/`app`)を新パスに更新する
                (`app`タスクは`uvicorn src.app.main:app`)。
  - TODO 32-5-2: `tests/sanity_checks.py`・`tests/eval_retrieval.py`・
                `tests/gold_set.py`・`tests/benchmark_ruri.py`の
                import文を新パスに更新する。
  - TODO 32-5-3: `frontend/src/api.ts`内の古いコメント(Phase19 TODO
                コメントで`src/phase4_retrieval.py`を参照している箇所)を
                新パスに修正する。
  - TODO 32-5-4: `frontend/src/`配下の全TypeScriptファイルのコメントを
                英語JSDoc形式に書き直す。
  - TODO 32-5-5: `docs/work_log.md`・`docs/plan.md`の過去ログは無変更で
                残す(履歴の正確性を優先)。本Phaseの新規work_logエントリ
                に新旧ファイル名の対応表を記載する。

### Step 32-6: 動作検証
  - TODO 32-6-1: `pixi run python tests/sanity_checks.py`の主要フェーズ
                (Phase1/2/3/8/9/10/13/18)を実行し回帰がないことを確認する。
  - TODO 32-6-2: `pixi run build`でフロントエンドビルドが通ることを
                確認する。
  - TODO 32-6-3: `radon cc src/ -s`で全関数が循環的複雑度15以内に
                収まっていることを確認する。

### Step 32-7: Dockerfile・Cloudflare Containers設定の作成
  - TODO 32-7-1: リポジトリルートに`Dockerfile`を新規作成する。pixi公式の
                Docker対応で依存関係をインストールし、`src/`・
                `output/plateau_rag.duckdb`(140MB)・`pixi run build`済みの
                `src/static/`を含めてイメージ化し、
                `uvicorn src.app.main:app --host 0.0.0.0 --port 8000`を
                実行する。
  - TODO 32-7-2: `.dockerignore`を新規作成し、`.git/`・`.pixi/`・
                `node_modules/`・`docs/foss4g/`等を除外する。
  - TODO 32-7-3: `wrangler.toml`(Cloudflare Containers用設定)を新規作成
                する。
  - TODO 32-7-4: `src/app/main.py`のCORS設定に本番Cloudflareドメイン用の
                プレースホルダを用意する。
  - TODO 32-7-5: `GEMINI_API_KEY`をCloudflareのシークレット機能で設定する
                手順を整理する(コードには直接書かない、CLAUDE.md R-10準拠)。

### Step 32-8: デプロイ・動作確認
  - TODO 32-8-1: ローカルで`docker build`→`docker run`し、
                `curl http://localhost:8000/api/health`と実際のクエリ
                実行がPCネイティブ実行時と同じ結果になることを確認する。
  - TODO 32-8-2: Cloudflare Containersに実際にデプロイし、外部
                (スマホ含む)からアクセスして動作確認する。
  - TODO 32-8-3: 発行されたCloudflareドメインをCORS許可リストに反映する。
  - TODO 32-8-4: `docs/work_log.md`に記録し、
                `git commit -m "refactor(phase32): ディレクトリ再編成と
                Cloudflare Containersデプロイ対応"`する。

**検証方法:**
- Step 32-1〜32-6: サニティチェック・ビルド成功・radonによる複雑度確認
- Step 32-7〜32-8: ローカルDocker動作確認 → Cloudflare Containers実機
  デプロイ確認(スマホ含む外部アクセス)

---

## Phase 33: データパスのCLI引数化・環境変数対応

### Step 33-1: 共通パス定義の一元化（`src/common/db.py`）
  - TODO 33-1-1: `db.py`に全パス定数を集約する — `GPKG_PATH`・`MAXLOD_GPKG_PATH`・
                `LANDUSE_GPKG_PATH`・`URF_GPKG_PATH`・`RELATED_DATA_DIR`・`CITY_PREFIX`・
                `SHELTER_PATH`/`STATION_PATH`/`EMROUTE_PATH`/`PARK_PATH`/`LANDMARK_PATH`・
                `RAG_DB_PATH`。現在3ファイルに重複している`GPKG_PATH`定義もここへ統一する。
  - TODO 33-1-2: 各定数は「環境変数（例: `PLATEAU_GPKG_PATH`）→未設定ならデフォルト値
                （現状の広島データパス）」の優先順で解決するようにする。
  - TODO 33-1-3: 関連GeoJSON5種は`RELATED_DATA_DIR`＋`CITY_PREFIX`（デフォルト
                `34100_hiroshima-shi_city_2022`）から
                `{CITY_PREFIX}_{shelter,station,emergency_route,park,landmark}.geojson`
                を組み立てる関数にする（他都市はprefixごと差し替え）。
  - TODO 33-1-4: `connect_rag()`に`db_path`省略可能引数を追加する（省略時は
                `RAG_DB_PATH`を使用、後方互換維持）。

### Step 33-2: パイプラインCLIスクリプトへのargparse追加
  - TODO 33-2-1: `investigate.py` — `--gpkg-path`
  - TODO 33-2-2: `gpkg.py` — `--gpkg-path`
  - TODO 33-2-3: `enrichment.py` — `--gpkg-path` `--landuse-path` `--urf-path`
                `--data-dir` `--city-prefix` `--db-path`
  - TODO 33-2-4: `geometry.py` — `--maxlod-gpkg-path` `--gpkg-path` `--db-path`
  - TODO 33-2-5: `context.py` — `--data-dir` `--city-prefix` `--db-path`
  - TODO 33-2-6: `src/app/retrieval.py`（`pixi run search`） — `--db-path`
                （既存のクエリ文字列位置引数と両立させる）
  - TODO 33-2-7: 各スクリプトの重複`GPKG_PATH`等の定義を`src.common.db`からの
                importに置き換える。

### Step 33-3: FastAPIランタイム側の環境変数対応
  - TODO 33-3-1: `geocoder.py`の`_STATION_PATH`・`_LANDMARK_PATH`を`src.common.db`の
                （環境変数対応済みの）`STATION_PATH`・`LANDMARK_PATH`に置き換える。
  - TODO 33-3-2: `main.py`・`retrieval.py`は既に`RAG_DB_PATH`経由のため、db.py側の
                対応で自動的に反映されることを確認する。
  - TODO 33-3-3: `.env.example`に新しい環境変数をコメント付きで追記する
                （すべて任意設定、未設定時は広島データがデフォルト）。

### Step 33-4: 動作確認
  - TODO 33-4-1: 引数なし・環境変数なしで全pixiコマンドが従来と同じ結果になることを
                回帰確認する。
  - TODO 33-4-2: `pixi run investigate -- --gpkg-path <別パス>`のような追加引数指定が
                実際に効くことを確認する。
  - TODO 33-4-3: `tests/sanity_checks.py`一式を実行し全件パスを確認する。
  - TODO 33-4-4: FastAPIアプリを環境変数なしで起動し、従来通り動作することを確認する。

### Step 33-5: ドキュメント更新
  - TODO 33-5-1: README.md/README_ja.mdの「データの準備」節を、CLI引数・環境変数での
                差し替え方法に即した正確な説明に更新する。
  - TODO 33-5-2: `docs/work_log.md`に記録、Step単位でコミットする。
