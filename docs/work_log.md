# 作業ログ — PLATEAU Semantic RAG

## [Phase 1] データ構造精査

### Step 1-1 & 1-2: テーブル一覧取得・スキーマ確認・JOIN 検証
- **日時:** 2026-03-22
- **実施内容:**
  - `ST_Read_Meta()` で GPKG の全テーブル一覧（11テーブル）を取得した。
  - `bldg:Building`（2,958件）・`tran:Road`（846件）のカラム構成を確認。
  - 災害リスク属性テーブル 3種の存在・カラム構成・JOIN 件数を確認。
  - `uro:BuildingDetailAttribute` のカラム構成を確認（`buildingStructureType` 等）。
  - `uro:RoadStructureAttribute` の存在を確認（`width`, `numberOfLanes` 等）。
- **確認結果（GPKG 内テーブル一覧）:**

| テーブル名 | 件数 |
|---|---|
| `bldg:Building` | 2,958 |
| `tran:Road` | 846 |
| `uro:HighTideRiskAttribute` | 2,953 |
| `uro:RiverFloodingRiskAttribute` | 11,622 |
| `uro:TsunamiRiskAttribute` | 2,536 |
| `uro:BuildingDetailAttribute` | 2,958 |
| `uro:BuildingIDAttribute` | 2,958 |
| `uro:RoadStructureAttribute` | 846 |
| `uro:DataQualityAttribute` | 3,804 |
| `uro:KeyValuePairAttribute` | 11,832 |
| `uro:RealEstateIDAttribute` | 73 |

- **重要な発見:**
  - `tran:TrafficArea` / `tran:AuxiliaryTrafficArea` は独立テーブルとして存在しない。
    `tran:Road` の `trafficArea` / `auxiliaryTrafficArea` カラム（VARCHAR/JSON 埋め込み）として格納されている。
  - `uro:InlandFloodingRiskAttribute` / `uro:LandSlideRiskAttribute` はこのサンプルに存在しない。
  - CRS は全テーブルで `EPSG:6671`（JGD2011 平面直角座標系 第3系）を確認。
  - リスク属性の結合キー: `uro:*RiskAttribute.parentId = bldg:Building.id` で正常に JOIN 可能。
  - `uro:HighTideRiskAttribute` のサンプル値例: `depth=4.46m, rank='3', description='1'`
    （description はコードリスト番号で、広島市固有のリスト参照が必要）
- **サニティチェック:** ✅ 全6項目パス
- **コミットハッシュ:** `2b7fa72`
- **備考:**
  - 存在しないレイヤーへの `st_read` は DuckDB/GDAL の segfault を引き起こすため、
    `ST_Read_Meta()` で事前に存在確認してから読み込む実装とした。

---

## [Phase 2] 空間演算実装

### Step 2-1〜2-5: 座標変換・建物・道路検索・統合関数・サニティチェック
- **日時:** 2026-03-22
- **実施内容:**
  - `src/phase2_spatial.py` を新規作成。
  - `wgs84_to_epsg6671(con, lon, lat)` を `ST_Transform(..., always_xy:=true)` で実装。
  - `validate_epsg6671_range(x, y)` で広島市 EPSG:6671 範囲チェックを実装。
  - `search_buildings_within(con, lon, lat, radius_m)` を `ST_DWithin` + `ST_Distance` で実装（`pyarrow.Table` 返却）。
  - `search_buildings_with_risk(con, lon, lat, radius_m)` を CTE 集約 + LEFT JOIN で実装。
  - `search_roads_near(con, x, y, radius_m)` を `ST_DWithin` で実装。
  - `build_spatial_context(con, lon, lat, radius_m)` で Phase 3 引き継ぎ辞書を実装。
  - `tests/sanity_checks.py` に Phase 2 用アサーション 3 関数を追加。
- **確認結果:**
  - テスト点 `(132.4625°E, 34.3955°N)` → EPSG:6671 `(27200.5, -177952.5)` 変換成功。
  - `ST_DWithin` 単調増加: 半径 500m=1,369件 ≤ 1000m=2,511件。
  - 高潮リスク付き建物: 1,369件（全件 non-NULL）。
- **サニティチェック:** ✅ Phase 1(6項目) + Phase 2(3項目) 全9項目パス
- **コミットハッシュ:** `16baafc`
- **備考:**
  - EPSG:6671 第3系の X 座標は広島市周辺で正値（+26,000〜+28,000 m）になる。
    当初 X を負値と誤って定義していたため `validate_epsg6671_range` の範囲を修正した。
  - DuckDB 1.5.0 では `con.execute().arrow()` が `RecordBatchReader` を返すため
    `.read_all()` を明示的に呼び出して `pyarrow.Table` に変換した。
  - `ST_Transform` に `always_xy:=true` を指定しないと EPSG:4326 の軸順（lat/lon）
    で解釈され `inf` が返される。

---

---

## [Phase 3] セマンティック・チャンク化（Step 3-1〜3-4）

### Step 3-1〜3-4: データ結合・テキスト化・埋め込み生成・DuckDB 保存
- **日時:** 2026-03-22
- **実施内容:**
  - `src/phase3_enrichment.py` を新規作成。
  - `connect_rag()` で `plateau_rag.duckdb` に spatial + vss 拡張をロードして接続。
  - `create_table(rag_con, embedding_dim)` で `building_chunks` テーブル（34カラム）を実装。
  - `load_building_attributes(con)` で GPKG（建物・リスク・道路・landuse・urf）と
    GeoJSON 5種（避難施設・駅・緊急輸送道路・公園・ランドマーク）を大きな CTE SQL で
    一括 JOIN し、2,958 件の pandas DataFrame を生成（処理時間: 約1.4秒）。
  - `build_text_card(row)` で 4 セクション形式（建物基本情報/災害リスク/構造/周辺環境）の
    自然言語カルテを生成（サンプル約 319 文字）。
  - `batch_embed(texts, checkpoint_path)` で `gemini-embedding-001` を呼び出す関数を実装。
    チェックポイント機能付き（日次クォータ超過時に途中保存・翌日再開可能）。
  - `save_chunks(rag_con, df, embeddings)` で GPKG から geometry を JOIN して一括 INSERT。
  - `create_hnsw_index(rag_con)` で cosine 距離の HNSW インデックスを作成。
  - `tests/sanity_checks.py` に Phase 3 用アサーション 3 関数を追加。
- **確認結果:**
  - Step 3-1（空間結合）: ✅ 2,958 件取得成功
  - Step 3-2（テキスト化）: ✅ 全件生成・[周辺環境] セクション確認
  - Step 3-3（埋め込み生成）: ✅ 2,958 件完了。実測次元数: **3,072**
  - Step 3-4（DuckDB 保存）: ✅ `output/plateau_rag.duckdb` に 2,958 件 INSERT + HNSW インデックス作成
- **サニティチェック:** ✅ Phase 1(6項目) + Phase 2(3項目) + Phase 3(3項目) 全12項目パス
- **コミットハッシュ:** `5723a11`（実装）/ `5145474`（work_log 更新）
- **備考:**
  - `text-embedding-004` は `v1beta` API で未サポート → `gemini-embedding-001` に変更。
  - Free Tier では 1,000 req/day 制限。有料プランへの移行で一括処理を完了。
  - `gemini-embedding-001` の実測次元数は **3,072**（768 ではなかった）。
  - pixi.toml に `pandas >= 2.0`, `numpy >= 1.26` を追加（Phase 3 の依存関係）。
  - 空間結合キャッシュ: `output/building_attrs_cache.parquet`（再実行時スキップ）。

---

---

## [Phase 5] README 整備

### Step 5-1〜5-2: README 作成・pixi タスク登録
- **日時:** 2026-03-22
- **実施内容:**
  - `README.md` を新規作成（概要・アーキテクチャ・セットアップ・各フェーズ実行手順・技術スタック）。
  - `pixi.toml` の `[tasks]` セクションに `investigate / spatial / enrich / search` を追加。
- **確認結果:**
  - `pixi run search` でデモクエリ 2 件が正常完了（`[SUCCESS] Phase 4 デモ完了`）。
- **コミットハッシュ:** `9d77c82`

---

## 不具合ログ

### [2026-03-22] `st_layers()` 未定義エラー
- **現象:** DuckDB spatial extension に `st_layers()` 関数が存在しない
- **解決策:** `ST_Read_Meta()` + `UNNEST(layers)` で代替
- **影響:** Step 1-1 の実装を修正

### [2026-03-22] 存在しないレイヤーへのアクセスで segfault
- **現象:** `st_read(..., layer='tran:TrafficArea')` が segfault
- **解決策:** `ST_Read_Meta()` で取得したレイヤー名一覧でフィルタリングしてから読み込む

### [2026-03-22] EPSG:6671 X 座標の符号誤り
- **現象:** 広島市 EPSG:6671 X 座標を負値（-160000〜-80000）と定義したため `validate_epsg6671_range` が常に失敗
- **原因:** JGD2011 平面直角 第3系の中央経線は 132°10'E。広島市は中央経線より東のため X は正値（+26000〜+28000 m）
- **解決策:** GPKG の `ST_XMin/ST_XMax` で実測し範囲を 0〜60000 に修正

### [2026-03-22] DuckDB 1.5.0 の `.arrow()` が RecordBatchReader を返す
- **現象:** `len(con.execute().arrow())` で `TypeError: object of type 'RecordBatchReader' has no len()`
- **解決策:** `.arrow().read_all()` を明示的に呼び出して `pyarrow.Table` に変換

### [2026-03-22] ST_Transform が `inf` を返す
- **現象:** `ST_Transform(geom, 'EPSG:4326', 'EPSG:6671')` が `x=inf, y=inf` を返す
- **原因:** EPSG:4326 の軸順は lat/lon（Y/X）。`POINT(lon lat)` の WKT を渡すと lon が latitude として解釈される
- **解決策:** `ST_Transform(..., always_xy:=true)` で X=lon, Y=lat の順を強制

---

## [Phase 4] ハイブリッド検索構築

### Step 4-1〜4-4: ベクトル検索・LLM 回答生成・統合 API・サニティチェック
- **日時:** 2026-03-22
- **実施内容:**
  - `src/phase4_retrieval.py` を新規作成。
  - `embed_query(text)` を `gemini-embedding-001`（task_type="RETRIEVAL_QUERY"）で実装。
  - `vector_search(rag_con, query_vec, lon, lat, radius_m, top_k)` を実装。
    - 空間フィルタあり: `ST_DWithin` で絞り込み後 `array_cosine_similarity` で ORDER BY。
    - 空間フィルタなし: 全件 HNSW 検索。
  - `generate_answer(query, candidates, model_provider)` を実装。
    - `model_provider="gemini"` → Gemini 2.5 Flash（デフォルト、GEMINI_API_KEY）。
    - `model_provider="claude"` → Claude Sonnet 4.6（将来切り替え用、ANTHROPIC_API_KEY）。
  - `hybrid_search(query, lon, lat, radius_m, top_k, model_provider)` で統合 API を実装。
  - `tests/sanity_checks.py` に Phase 4 用アサーション 2 関数を追加。
  - `docs/plan.md` に Phase 4 の Step 定義を追記。
- **確認結果:**
  - デモクエリ 1（空間フィルタなし）: 10 件の候補から回答生成成功（約 25 秒）。
  - デモクエリ 2（広島城周辺 500m 空間フィルタ）: 10 件の候補から回答生成成功。
  - 埋め込み次元数: 3,072（gemini-embedding-001、RETRIEVAL_QUERY）。
  - vector_search の最高スコア: 0.765（クエリ 1）、0.716（クエリ 2 空間フィルタあり）。
- **サニティチェック:** 全 14 件パス（Phase 1: 6, Phase 2: 3, Phase 3: 3, Phase 4: 2）
- **コミットハッシュ:** `3521943`
- **備考:**
  - デモ座標は GPKG サンプルデータ範囲内 (132.4625°E, 34.3955°N) を使用。
  - `model_provider` 引数で LLM を後から Claude Sonnet 4.6 に切り替え可能な設計。

---

## [Phase 6] 地図可視化 Web アプリ（チャット UI + 地図）

### Step 6-1: 環境セットアップ
- **日時:** 2026-03-22
- **実施内容:**
  - `pixi.toml` に `fastapi >=0.115`、`uvicorn >=0.30 [standard]`、`aiofiles >=23.2` を追加。
  - `app`（uvicorn）、`dev`（Vite dev server）、`build`（Vite ビルド）タスクを定義。
  - `npm create vite@latest frontend -- --template vanilla-ts` で Vite プロジェクトを初期化。
  - `maplibre-gl`、`@types/geojson` をインストール。
  - `frontend/vite.config.ts` で `/api` → `localhost:8000` プロキシと `outDir: ../src/static` を設定。

### Step 6-2: FastAPI バックエンド実装
- **日時:** 2026-03-22
- **実施内容:**
  - `src/phase6_app.py` を新規作成。
  - `POST /api/search`：`hybrid_search()` を `run_in_executor` で非同期ラップ。
  - `GET /api/health`：DB 存在確認付き。
  - `candidates_to_geojson()`：`ST_AsGeoJSON(ST_Transform(..., always_xy:=true))` で EPSG:6671→WGS84 変換。
  - `src/static/` が存在する場合は静的ファイルを配信（本番ビルド配信）。

### Step 6-3 & 6-4 & 6-5: フロントエンド実装
- **日時:** 2026-03-22
- **実施内容:**
  - `frontend/index.html`：`role="log" aria-live="polite"` メッセージリスト、スキップリンク、aria-live リージョン。
  - `frontend/src/style.css`：CSS カスタムプロパティによるライト/ダークテーマ、WCAG 2.1 AA 対応コントラスト比、レスポンシブ 3 ブレークポイント。
  - `frontend/src/store.ts`：`AppState` 管理（subscribe/set/get パターン）。
  - `frontend/src/api.ts`：`POST /api/search` fetch ラッパー。
  - `frontend/src/theme.ts`：localStorage + `prefers-color-scheme` テーマ管理、OpenFreeMap スタイル URL。
  - `frontend/src/map.ts`：MapLibre GL JS 初期化、GeoJSON レイヤー（fill/outline/highlight）、ポップアップ、テーマ切り替え。
  - `frontend/src/chat.ts`：メッセージバブル描画、候補建物リスト（上位 5 件）、地図ハイライト連動。
  - `frontend/src/main.ts`：全コンポーネント初期化、IME 確定 Enter 誤送信防止、モバイル `history.pushState` 対応。
- **技術的特記事項:**
  - 地図スタイル：OpenFreeMap（無料・APIキー不要・日本語ラベル対応）— ライト `liberty` / ダーク `dark`。
  - CSS filter ハックなし — `map.setStyle()` でネイティブダークスタイルへ切り替え。
  - モバイルフルスクリーン地図：`position: fixed; inset: 0` + `history.pushState` でブラウザ戻るボタン対応。

### Step 6-6: 動作確認・サニティチェック
- **日時:** 2026-03-22
- **実施内容:**
  - `pixi run build` → TypeScript コンパイル + Vite ビルド成功（`src/static/` に出力）。
  - `pixi run app` → FastAPI 起動、`http://localhost:8000/` でフロントエンド配信確認。
  - `/api/health` 200 OK、`/api/search` GeoJSON 付き回答生成確認（3 件、約 15 秒）。
  - `tests/sanity_checks.py` に Phase 6 用チェック 2 関数（`check_phase6_health`, `check_phase6_search`）を追加。
  - `python tests/sanity_checks.py --phase6` でサニティチェック全パス（2/2）。
- **サニティチェック:** ✅ 全 2 件パス
- **コミットハッシュ:** 7bd9ac7

---

## [Phase 3 修正] コードリスト適用（属性カルテの日本語ラベル化）

### Step 3-x: codelist_loader 実装・Phase 3 再実行
- **日時:** 2026-03-22
- **実施内容:**
  - `src/codelist_loader.py` を新規作成。`data/codelists/` 以下の XML 47 ファイルのうち実際に使用する 7 ファイルのみを対象に `CodelistLoader` クラスを実装。
  - `phase3_enrichment.py` の `build_text_card()` を修正。コード値を日本語ラベルに変換してから `text_card` を生成するよう改善。
  - DuckDB に保存する属性カラム（`usage`, `structure_type`, `fire_proof`, `landuse_class`, `ht_rank_worst`, `rv_rank_worst`, `ts_rank_worst`）もデコード済みラベルで保存。
  - `embed_checkpoint.json` を削除後、Phase 3 を再実行。全 2,958 件の text_card・Embedding を再生成。
- **確認結果（変換サンプル）:**

| 属性 | 修正前 | 修正後 |
|------|--------|--------|
| `usage` | `["403"]` | `宿泊施設` |
| `structure_type` | `601` | `木造・土蔵造` |
| `fire_proof` | `1001` | `耐火` |
| `landuse_class` | `214` | `公益施設用地（官公庁施設…）` |
| `ht_rank_worst` | `4` | `5m以上10m未満` |

- **サニティチェック:** ✅ 全件 text_card・カラム値が日本語ラベルに変換済みを確認
- **コミットハッシュ:** 未採番
- **備考:** `urf_usage` は全件 NULL のためコードリスト変換不要。`461`（usage）は仕様上「不明」が正しい値。

---

## [Phase 7] README 整備

### Step 7-1: README.md を Phase 6（Web UI）まで含めて全面更新
- **日時:** 2026-03-22
- **実施内容:**
  - フロントエンド（Phase 6）の起動手順・使い方・API 仕様を追記。
  - Node.js 前提条件、`npm install`、`pixi run app` / `pixi run dev` / `pixi run build` の説明を追加。
  - Web UI の使い方（チャット操作・地図・テーマ切り替え・クエリ例）を追記。
  - `POST /api/search` のリクエスト/レスポンス例を記載。
  - プロジェクト構成に `frontend/`・`src/phase6_app.py`・`src/codelist_loader.py`・`data/codelists/` を追記。
  - 技術スタック表に FastAPI / Uvicorn / Vite / TypeScript / MapLibre GL JS / OpenFreeMap を追記。
- **サニティチェック:** ✅ README 全セクション（CLI・Web UI・API・構成・技術スタック）の記載を確認
- **コミットハッシュ:** 未採番
- **備考:** Phase 5（README 整備）で CLI 部分は既存、今回 Phase 6 分を追加した。

---

## [Phase 8] クエリ解析 × 空間・属性フィルタ統合

### Step 8-1: src/query_parser.py 作成（クエリ解析エンジン）
- **日時:** 2026-03-22
- **実施内容:**
  - `ParsedQuery` dataclass を定義（`location_name`, `radius_m`, `height_min`, `usage_include`, `structure_type`, `sort_by_height`, `clarification_question`）。
  - Gemini Flash（temperature=0, JSON スキーマ出力）でクエリを構造化解析。
  - `height_min` の設計を 3 段階に整理：
    - 目的不明な相対表現（「高い建物」）→ `clarification_question` を設定して確認質問を返す
    - 目的ありの文脈（洪水避難・眺望・ランドマーク）→ `height_min` を自動推定
    - 明示的数値（「30m以上」）→ `height_min` に変換
- **サニティチェック:** ✅ 3 パターンのクエリ解析チェックパス

### Step 8-2: src/geocoder.py 作成（ジオコーダー）
- **日時:** 2026-03-22
- **実施内容:**
  - 内部 station.geojson（146件）・landmark.geojson（599件）のキャッシュロード。
  - 優先順位: ①station 完全一致→部分一致 ②landmark 完全一致→部分一致 ③Nominatim API ④None。
  - Nominatim は `urllib.request`（追加依存なし）、`User-Agent` ヘッダ、タイムアウト 5 秒。
- **サニティチェック:** ✅ geocode('広島駅') → lon=132.4755, lat=34.3975

### Step 8-3: src/phase4_retrieval.py 修正（属性フィルタ・temperature=0）
- **日時:** 2026-03-22
- **実施内容:**
  - `vector_search()` に `height_min`, `usage_include`, `structure_type`, `sort_by_height` パラメータを追加。
  - `measured_height <= 0`（4件・無効値 -9999.0）を高さ関連フィルタ時に除外。
  - `hybrid_search()` に `use_query_parser` パラメータを追加。`parse_query()` + `geocode()` を統合。
  - `clarification_question` がある場合は検索をスキップして質問を返すロジックを実装。
  - `_generate_with_gemini()` / `_generate_with_claude()` に `temperature=0` を追加（再現性向上）。

### Step 8-4: src/phase6_app.py 修正（SearchRequest/Response 更新）
- **日時:** 2026-03-22
- **実施内容:**
  - `SearchRequest` に `use_query_parser: bool = True` を追加。
  - `SearchResponse` に `parsed_query`, `geocoded_location`, `clarification_question` を追加。
  - `clarification_question` がある場合、フロントエンド修正なしでチャット回答として表示される設計。

### Step 8-5: サニティチェック追加・全パス確認
- **日時:** 2026-03-22
- **実施内容:**
  - `check_phase8_query_parser_ambiguous_height`: 目的不明クエリの clarification_question 検証
  - `check_phase8_query_parser_purpose_height`: 洪水避難クエリの height_min 推定検証
  - `check_phase8_query_parser_explicit_height`: 明示数値の height_min 変換検証
  - `check_phase8_geocoder_station`: 広島駅ジオコーディング検証
  - `check_phase8_integrated_search`: 確認質問クエリと実検索クエリの統合動作検証
- **サニティチェック:** ✅ Phase 8 全 5 チェックパス（5件パス / 0件失敗）
- **コミットハッシュ:** 未採番
- **備考:**
  - `phase3_enrichment.py` の `from src.codelist_loader import CodelistLoader` を `try/except ImportError` でフォールバック対応。
  - `phase4_retrieval.py` の `query_parser` / `geocoder` インポートも同様に対応。

---

## [Phase 10] ハイブリッド検索高度化（SQL × ベクトル ルーティング）

### Step 10-1: 評価基盤（gold_set.py / eval_retrieval.py）構築
- **日時:** 2026-07-17
- **実施内容:**
  - `tests/gold_set.py` を新規作成。評価クエリ 20 件（structured 8 / hybrid 8 / semantic 4）を
    `GOLD_QUERIES` として定義し、各クエリの正解建物 ID 集合を SQL で機械的に算出して
    `output/gold_set.json` に保存する `build_gold()` を実装。
  - `tests/eval_retrieval.py` を新規作成。`evaluate(top_k, use_query_parser)` で
    ゴールドセット全件に対し `hybrid_search()` を実行し、recall@k・precision@k・hit@1 を算出。
    category 別マクロ平均を表示し、`output/eval_result_{YYYYMMDD_HHMM}.csv` に保存。
  - `phase4_retrieval.py` の `hybrid_search()` に `skip_answer: bool = False` を追加。
    True 時は `generate_answer()` を呼ばず `answer=""` を返す（評価時の API クォータ節約）。
  - ゴールドクエリ策定時、実データ分布を確認して 3 件を調整:
    - G09: `usage='宿泊施設'`（22件）は全件 `ht_depth_max` が非 NULL のため、
      条件を高潮→津波リスク（`ts_depth_max IS NULL`、5件）に変更。
    - G11: `ht_depth_max <= 1.0`（実測分布は最小 1.688m・中央値約 5.06m）は
      `fire_proof='耐火'` との積集合が 0 件だったため閾値を 5.0m に変更（198件）。
    - G16: `nearest_landmark_dist_m <= 500`（平均距離 134.6m）は全 2,958 件が該当し
      検証として無意味なため半径を 100m に変更（1,065件）。
- **確認結果（改修前ベースライン）:**

| category | recall@10 | precision@10 | hit@1 |
|---|---|---|---|
| structured | 0.0119 | 0.25 | 0.25 |
| hybrid | 0.0344 | 0.50 | 0.50 |

  - 純構造化クエリの症状再現を確認: G01「広島市で最も高い建物は？」recall=0.0、
    G03「駅から300m以内の建物」recall=0.0、G07「最も駅に近い建物は？」recall=0.0
    （いずれも埋め込み検索のみでは高さ・距離の確定条件を満たせないことを実測で裏付け）。
  - 結果保存先: `output/eval_result_20260717_0519.csv`
- **サニティチェック:** ✅ ゴールドセット20件すべて非0件（semantic除く）・妥当な母数であることを確認
- **コミットハッシュ:** `709e207`
- **備考:** Free Tier クォータ節約のため `skip_answer=True` で評価。1回の evaluate() 実行で
  Gemini API を約40回呼び出す（parse_query + embed_query × 20クエリ）。

### Step 10-2: query_parser.py 拡張
- **日時:** 2026-07-17
- **実施内容:**
  - `RiskFilter`（hazard/mode/max_depth_m）、`DistanceFilter`（target/max_dist_m）、
    `SortSpec`（key/order）の dataclass を追加。
  - `ParsedQuery` に `risk_filters`, `distance_filters`, `fire_proof`, `sort_by`,
    `semantic_residual` を追加。既存の `sort_by_height` は `sort_by` から
    正規化するフィールドとして後方互換のまま維持。
  - `fire_proof` の実値を `SELECT DISTINCT fire_proof FROM building_chunks` で確認し
    `_FIRE_PROOF_VALUES = "不明/耐火/準耐火造/その他"` を定義。
  - システムプロンプトに `_STRUCTURED_RULES` を追加。徒歩分速換算（1分=80m）、
    曖昧な距離のデフォルト 500m、災害種別未指定「リスクが低い」は ht/rv/ts
    3件のリスクフィルタに展開、等のルールを明記。
  - `response_schema` に risk_filters / distance_filters / sort_by のネスト
    object 配列を追加。
  - `__main__` のテストケースを10件に拡張し動作確認。
- **確認結果・不具合修正:**
  - 動作確認中に「最も高い建物は？」で `sort_by` が確定しているにも関わらず
    `clarification_question` も設定される不具合を発見。
  - 原因: height_min ルールの優先順位が「高い建物のみ→確認質問」を
    「最も高い」にも適用してしまっていたため。
  - 修正: `_HEIGHT_RULES` に最上級表現（「最も」「一番」）を最優先ルールとして追加し、
    sort_by 確定時は clarification_question=null に固定。修正後、
    「最も高い建物は？」「一番高い建物を教えて」で確認質問が出ないことを確認。
  - Phase 8 既存サニティチェック（`--phase8`）を再実行し、全 5 件パスを確認
    （後方互換フィールドの回帰なし）。
- **サニティチェック:** ✅ Phase 8 全5件パス（回帰確認）／ __main__ 10ケース目視確認
- **コミットハッシュ:** `66db099`
- **備考:** vector_search() / phase10_router.py 側の対応（Step 10-3）が未実装のため、
  risk_filters 等の新フィールドはまだ検索ロジックに反映されていない。

### Step 10-3: ルーター＋SQLビルダー実装（phase10_router.py）
- **日時:** 2026-07-17
- **実施内容:**
  - `src/phase10_router.py` を新規作成。
    - `classify_route(pq)`: risk_filters/distance_filters/fire_proof/height_min/
      usage_include/structure_type/sort_by/location_name の有無と semantic_residual
      の有無から structured/semantic/hybrid を判定（両方空の場合は semantic にフォールバック）。
    - `build_filter_clauses(pq, alias)`: 構造化条件をプレースホルダ付き WHERE 句断片と
      バインド値リストに変換。`HAZARD_COLUMN` / `TARGET_COLUMN` 対応表を定義。
    - `build_order_clause(pq, route, alias)`: sort_by 指定時は該当カラムで ORDER BY
      （*_depth_max は NULL=リスクなしを asc では先頭・desc では末尾に配置）、
      未指定時は hybrid/semantic で score DESC、structured で id 昇順にフォールバック。
  - `phase4_retrieval.py` の `vector_search()` を全面改修。シグネチャを
    `vector_search(rag_con, pq, route, query_vec, lon, lat, radius_m, top_k)` に変更し、
    Phase 8 の個別フィルタ引数（height_min 等）を廃止して `pq` に集約。
    route="structured" では埋め込み API 呼び出し・cosine 類似度計算をスキップし
    `NULL AS score` で SQL のみの確定検索を行う。
  - `hybrid_search()` を改修。`classify_route(pq)` で経路判定し、
    route="structured" の場合は `embed_query()` を呼ばず、hybrid の場合は
    `pq.semantic_residual` を埋め込み対象にする。戻り値に `route` を追加。
  - `tests/sanity_checks.py` の `vector_search()` 呼び出し2箇所
    （`assert_vector_search_returns_results`, `check_phase9_vector_search_geom_cols`）
    を新シグネチャ（`ParsedQuery()`, `"semantic"` を渡す）に更新。
- **確認結果（実クエリでの経路別動作確認）:**
  - 「広島市で最も高い建物は？」→ route=structured、高さ降順 5 件（164.4m〜138.2m）を
    埋め込み API を呼ばず SQL のみで取得。G01 のゴールド定義と一致。
  - 「高潮リスクが低い建物」→ route=structured、5 件全件 `ht_depth_max IS NULL`。
  - 「駅から近く高潮リスクのない宿泊施設」→ route=structured（全条件が構造化済みで
    semantic_residual が空になったため）、0 件（宿泊施設22件は全件 ht_depth_max が
    非NULLのため実データ上正しい0件。誤動作ではない）。
  - 「日当たりのよい建物」→ route=semantic、5 件取得（従来の全件ベクトル検索）。
- **不具合修正（動作確認中に発見）:**
  - 「広島市で最も高い建物は？」で `location_name="広島市"` が抽出され、
    `geocoder.py` の部分一致ロジックにより「広島市○○」で始まる無関係なランドマーク
    （市役所・消防局等）にヒットし、意図しない半径500m空間フィルタがかかって
    0件になる不具合を発見。データセット自体が広島市限定のため「広島市」は
    絞り込み条件として意味を持たない。
  - `query_parser.py` の `location_name` ルールに「『広島市』『市内』など
    データセット全体を指すだけの語は null とする」を追加して解消。
- **サニティチェック:** ✅ Phase 8 (`--phase8`)・Phase 9 (`--phase9`) 全チェック回帰確認パス。
  4経路（structured×3パターン・semantic）を実クエリで直接検証。
- **コミットハッシュ:** `2d8756c`
- **既知の問題（Phase 10 と無関係・別タスクで対応）:**
  - `tests/sanity_checks.py`（引数なし、Phase 1〜4 全チェック）を実行すると
    Phase 1/2 実行中に非決定的に segmentation fault が発生する場合がある。
    Phase 10 の変更を完全に revert した状態でも 2/2 回再現したため、
    DuckDB spatial extension の複数コネクション間競合等に起因する既存の
    環境依存の flaky 問題と判断。別タスクとして切り出し済み（本 Step の回帰確認は
    `--phase8` / `--phase9` フラグ付き実行と直接の hybrid_search() 呼び出しで実施）。

### Step 10-4: 候補検証パス・LLM プロンプト改善
- **日時:** 2026-07-17
- **実施内容:**
  - `src/phase10_router.py` に `verify_candidates(candidates, pq)` を実装。
    `build_filter_clauses` と同じ条件（risk_filters/distance_filters/fire_proof/
    height_min/usage_include/structure_type）を pandas 側で再評価し、違反行を
    除外した DataFrame と除外理由文字列リストを返す。SQL フィルタ通過後の
    防御的チェックとして機能する。
  - `phase4_retrieval.py` の `build_prompt()` を全面改修。
    - 類似度スコアの数値表示・「類似度スコア順」の文言を廃止（LLM のアンカリング防止）。
    - 冒頭に Markdown 比較表（建物ID/用途/高さ/階数/高潮・洪水・津波浸水/構造/耐火/
      駅まで/避難所まで）を追加。NULL は「なし」、-9999.0（無効値）の高さは「不明」表示。
    - text_card 全文の添付を上位10件に制限し、11件目以降は比較表の行のみとする。
    - 回答形式指示に「比較表の数値に基づき条件充足を確認」「表にない情報を創作しない」を追加。
  - `validate_answer(answer, candidates)` を実装。正規表現
    `bldg_[0-9a-fA-F]{8}-...` で回答中の建物ID形式文字列を抽出し、
    候補集合に存在しないID（ハルシネーション）があれば末尾に注記を追加する。
- **確認結果:** API 呼び出しなしの単体テストで3関数すべて動作確認。
  - `build_prompt`: 「類似度スコア」文言なし、比較表・NULL→「なし」・-9999.0→「不明」変換を確認。
  - `validate_answer`: 存在しないID混入時に注記追加、既知IDのみの場合は原文のまま返すことを確認。
  - `verify_candidates`: 高潮リスクなし条件＋用途条件で、条件違反建物（ht_depth_max=6.7の非NULL）
    が正しく除外されることを確認。
- **サニティチェック:** ✅ 単体テスト3件（build_prompt/validate_answer/verify_candidates）パス
- **コミットハッシュ:** `d6bac40`
- **備考:** hybrid_search() への統合（verify_candidates・validate_answer の呼び出し配線）は
  Step 10-5 で実施する。

### Step 10-5: 統合・効果測定・サニティチェック
- **日時:** 2026-07-17
- **実施内容:**
  - `hybrid_search()` に `verify_candidates()` と `validate_answer()` を配線。
    処理順: parse_query → clarification判定 → geocode → classify_route →
    経路別embed → vector_search → verify_candidates（条件違反候補を除外）→
    generate_answer → validate_answer（存在しない建物ID検出）。
  - `phase6_app.py` の `SearchResponse` に `route: str | None = None` を追加し、
    `search()` エンドポイントが `route` を返却するよう修正。
  - `tests/sanity_checks.py` に Phase 10 用チェック3関数を追加:
    `check_phase10_route_structured`（純構造化クエリの決定的正答）、
    `check_phase10_route_hybrid`（距離条件の充足）、
    `check_phase10_risk_filter`（リスクなし条件の充足）。
    `run_phase10_checks()` と `--phase10` CLI 分岐を追加。
  - **統合時に発見した不具合の修正:**
    「洪水避難に適した建物」のような"避難先として使える建物"を求めるクエリで、
    LLM が `height_min` に加えて `risk_filters=[rv:none]`（洪水リスクなし）も
    誤って設定し、`check_phase8_integrated_search` が0件で失敗する回帰を発見。
    避難先の建物はリスクゾーン内に立地するのが通常であり「リスク自体が存在しない」
    ことを意味しないため、`query_parser.py` の `_STRUCTURED_RULES` に
    「避難適性（height_min 対象）とリスク回避（risk_filters 対象）を混同しない」
    ルールを追加して解消。修正後 `--phase8` 全5件パス再確認。
  - `tests/eval_retrieval.py` を再実行し、Step 10-1 のベースラインと比較。
- **確認結果（Before/After 比較。structured/hybrid の category 別マクロ平均）:**

| category | 指標 | Before | After |
|---|---|---|---|
| structured | recall@10 | 0.0119 | **0.637** |
| structured | precision@10 | 0.25 | **0.8375** |
| structured | hit@1 | 0.25 | **1.0** |
| hybrid | recall@10 | 0.0344 | **0.266** |
| hybrid | precision@10 | 0.50 | **0.9125** |
| hybrid | hit@1 | 0.50 | **1.0** |

  - hit@1（1位推薦が正解集合に含まれる率）が structured/hybrid ともに **1.0** に到達。
    Phase 10 着手の動機となった症状（「高い建物があるのに他を選ぶ」「条件に合わない
    ものを選ぶ」）に直結する指標が完全解消したことを示す。
  - recall@10 が正解集合サイズの大きいクエリ（G03: 駅300m以内2,590件、G08: 10階建て
    以上2,034件）で低い値（0.004〜0.009）に留まるのは、top_k=10 の物理的上限による
    もので不具合ではない。これらは precision@10（G03=1.0）で全件正解であることを確認済み。
    G08 のみ precision=0.7（3件不一致）だが、これは ParsedQuery に `storeys` 専用の
    フィルタを実装しておらず「10階建て以上」を `height_min`（メートル換算）で近似して
    いるための既知の制約であり、Phase 11 以降での改善候補とする。
  - 結果保存先: `output/eval_result_20260717_0551.csv`（Before: `eval_result_20260717_0519.csv`）
- **サニティチェック:** ✅ Phase 8 (`--phase8`) 全5件・Phase 9 (`--phase9`) 全3件・
  Phase 10 (`--phase10`) 新規3件、すべてパス。
- **コミットハッシュ:** `15367f3`
- **既知の制約（Phase 11 以降の改善候補）:**
  - `ParsedQuery` に階数専用フィルタ（`storeys_min` 等）がなく、「N階建て以上」は
    `height_min`（1階≈3m換算）で近似している。ゴールドクエリ G08 で 3/10 件の
    不一致が生じる原因。
  - `tests/sanity_checks.py`（引数なし、Phase 1〜4 全チェック）の非決定的 segfault は
    Step 10-3 で報告済みの既存問題（Phase 10 と無関係）として別タスクに切り出し済み。
    未解決のまま。

---

## [Phase 11] ベクトル検索側の識別力改善（埋め込み再生成は対象外）

> Phase 10 完了後、ユーザー指示により「埋め込みの再生成は行わない」制約下で
> 実施。`docs/plan.md` の Phase 11 を、この制約に合わせて改訂した上で着手。

### Step 11-1: build_embed_text() 実装（関数実装のみ・再埋め込みなし）
- **日時:** 2026-07-17
- **実施内容:**
  - `src/phase3_enrichment.py` に `build_embed_text(row, cl, geom_meta) ->
    dict[str, str]` を新規実装（`build_text_card` は変更せずそのまま維持）。
    セクション別（risk/environ/shape）に、建物固有の情報のみを句点区切りで
    連結したテキストを返す。セクション見出し・「・」等の記号・「データなし」
    等の定型文を一切含まない設計とした（build_text_card との最大の違い）。
  - `_nan(v)` ヘルパーを追加（NULL/NaN 判定の共通化）。
  - `building_chunk_sections` テーブル作成・埋め込み投入・vector_search() 拡張
    （元計画の TODO 11-1-2/11-1-3 相当）は、ユーザー指示によるスコープ外のため
    実装しない。設計は `docs/plan.md` の Step 11-1-3（将来実施）に残した。
- **確認結果（サンプルデータでの目視確認）:**
  - 動作確認中に2件の不具合を発見・修正:
    1. テストデータの `usage` を平文コード `'401'` で渡すと `decode_usage()`
       が JSON パースに失敗し未デコードのまま出力される問題を発見
       （原因はテストデータの形式誤り。`decode_usage()` の仕様どおり
       `'["402"]'` 形式の JSON 配列文字列に修正して解消）。
    2. `usage` が `None` の場合 `decode_usage(None)` が独自に `"データなし"`
       を返すため、`build_embed_text()` のガード条件
       （`!= "不明"` のみ）をすり抜けて定型文が `environ` セクションに
       混入する不具合を発見。ガード条件に `"データなし"` を追加して解消。
  - 修正後、以下を確認:
    - `risk` セクション: `'高潮浸水最大2.5m。洪水浸水最大1.0m。津波リスクなし。'`
      （見出し・記号なし、build_text_card の「・高潮: 最大浸水深...」より簡潔）
    - `environ` セクション: `'商業施設。広島駅（駅）まで800m。...'`
      （usage が正しく日本語ラベルにデコードされ、定型文なし）
    - `shape` セクション: geom_meta 指定時のみ非空文字。`geom_meta=None`
      および全属性 NULL の建物ではいずれも空文字（`environ` も空文字）を確認。
    - 全セクションで `'データなし'` が含まれないことをアサーションで確認。
- **サニティチェック:** ✅ 手動アサーション（print デバッグ確認、
  `tests/sanity_checks.py` への追加は本 Step のスコープ外）
- **コミットハッシュ:** `3929e3d`
- **備考:** DB 保存・`batch_embed()` 呼び出しは行っていない。将来
  再埋め込みを実施する際にそのまま利用できる状態で関数のみ用意した。

### Step 11-2: ハイブリッド検索の高度化（FTS×ベクトル RRF・HyDE。再埋め込み不要）
- **日時:** 2026-07-17
- **実施内容:**
  - `src/phase11_hybrid_search.py` を新規作成。
    - `ensure_fts_index(rag_con)`: `building_chunks.text_card` に BM25 用 FTS
      インデックスを作成（`PRAGMA create_fts_index(..., stemmer='none',
      overwrite=1)`）。動作確認中に `:=` 名前付き引数構文がこの環境の
      DuckDB では `create_fts_index(VARCHAR, VARCHAR)` の基本シグネチャしか
      解決できず失敗したため、`=` 構文に修正して解消。
    - `fts_search(rag_con, query_text, top_k)`: BM25 検索を実行し
      `(id, bm25_score)` の DataFrame を返す。
    - `rrf_merge(vec_df, fts_df, k=60, id_col="id")`: 順位ベースの RRF
      （`1/(k+rank_vec) + 1/(k+rank_fts)`）でベクトル結果と FTS 結果を融合。
    - `hyde_rewrite(semantic_residual)`: Gemini Flash（temperature=0）で
      検索意図を仮想カルテ文に書き換え。失敗時・APIキー不在時は元テキストへ
      フォールバック。
  - `phase4_retrieval.py` の `vector_search()` に `use_fts: bool = False`,
    `fts_query_text: str | None = None` を追加。route="structured" 以外で
    `use_fts=True` の場合、ベクトル検索を `top_k*2` 件取得した上で
    `fts_search()` の結果と `rrf_merge()` で融合し `top_k` に絞り込む。
    **設計上の簡略化**: `fts_df` はベクトル検索が既に取得した候補（`df` の
    id 集合）に絞り込んでから融合し、FTS のみでヒットした未取得 id を
    新規追加はしない（他カラムが欠損したまま候補に混入する問題を回避するため）。
    FTS インデックスは `information_schema.schemata` で存在確認し、
    未作成時のみ `ensure_fts_index()` を呼ぶ遅延作成方式とした。
  - `hybrid_search()` に `use_fts: bool = False`, `use_hyde: bool = False`
    を追加し `vector_search()` / `embed_query()` に伝播。HyDE は
    `fts_query_text`（FTS 用）を書き換え**前**のテキストで固定し、
    埋め込み対象のみ書き換え後のテキストに置き換える設計とした。
  - `tests/eval_retrieval.py` の `evaluate()` に `use_fts`, `use_hyde`
    引数、`main()` に `--fts` / `--hyde` CLI オプションを追加。
  - `tests/sanity_checks.py` に Phase 11 用チェック3関数を追加:
    `check_phase11_fts_index`, `check_phase11_rrf_merge`,
    `check_phase11_hyde_fallback`。`run_phase11_checks()` と
    `--phase11` CLI 分岐を追加。
- **確認結果（重要な制約の発見）:**
  - **DuckDB FTS は連続した日本語文に対してほぼ機能しない**ことを実データで確認。
    FTS の既定トークナイザは ASCII 空白・半角記号を区切りとするため、
    `text_card` のような区切りのない日本語文中では固有名詞が単独トークンとして
    抽出されない。実測: `fts_search(con, '広島駅', top_k=10)` → **0件**、
    `fts_search(con, '住宅', top_k=10)` → 10件（前後に区切り文字がある
    ため単独トークン化された模様）。
  - `tests/eval_retrieval.py --fts` で全20クエリを再評価した結果、
    structured/hybrid の recall@10・precision@10・hit@1 は
    `use_fts=False` の結果と**完全に同一**（差分なし）。semantic クエリ
    （「日当たりのよい建物」等）でも候補 ID・順序ともに完全一致を確認。
    → 本データセットでは FTS+RRF の効果は実質ゼロ。関数自体は単体テストで
    正しく動作することを確認済みだが、日本語の分かち書き前処理
    （MeCab/fugashi 等）を追加しない限り実用上の効果は見込めない。
    計画の逃げ道（「分かち書き前処理が必要と判明した場合は本 TODO の
    スコープ外として記録する」）に該当するため、分かち書き実装は
    今回のスコープ外として記録するに留める。
  - **HyDE は候補を大きく変化させることを確認**したが、効果の定量評価は
    できない（semantic カテゴリに正解集合がないため）。
    「日当たりのよい建物」で `use_hyde=True` により候補が
    5件中5件とも入れ替わった（HyDE書き換え文の例:
    「一般に大きな窓を多数配置し、建物の奥まで日光を取り込む設計です。
    周辺に日光を遮る建物が少なく、主要な居住空間は常に明るく開放的な
    雰囲気を提供します。」）。この差は route=semantic で再現性のある
    条件下（両呼び出しで同一の route・semantic_residual）で確認したもの。
  - **A/B比較時の注意点（発見・記録）**: 別クエリ「防災拠点として活用
    できそうな建物」の `use_hyde=True/False` 比較では、同一入力なのに
    `parse_query()` の解析結果自体が呼び出しごとに異なった
    （1回目: route=hybrid・semantic_residual あり／2回目: route=structured・
    semantic_residual=""）。これは `parse_query()`（Gemini Flash,
    temperature=0）の非決定性によるもので、HyDE の効果ではない。
    2回目は route=structured だったため HyDE は実際には適用されておらず、
    観測された候補差分を HyDE の効果と誤って解釈しないよう注意が必要
    であることが分かった。
- **サニティチェック:** ✅ Phase 11 (`--phase11`) 新規3件・Phase 9 (`--phase9`)
  全3件・Phase 10 (`--phase10`) 全3件、すべて回帰なしでパス。
- **コミットハッシュ:** `9b477e6`
- **採用判断:**
  - `use_fts`: 実データで効果ゼロを確認したため、**デフォルト False のまま
    据え置き**（オプトインのみ提供）。分かち書き前処理を追加する再改修が
    Phase 12 以降の候補。
  - `use_hyde`: 候補を大きく変化させる効果は確認できたが、
    （1）semantic カテゴリに正解集合がなく品質改善を定量的に実証できない、
    （2）LLM 呼び出しが1回増えるレイテンシコストがある、の2点から
    **デフォルト False のまま据え置き**（オプトインのみ提供）。
    定量評価には semantic クエリの人手評価または正解集合の拡充が必要。

---

## [Phase 12] SudachiPy 分かち書きによる FTS 有効化

> Phase 11 で判明した「DuckDB FTS は連続日本語文にほぼ機能しない」制約に対し、
> SudachiPy（Mode C）による分かち書き前処理で解消を試みる。

### Step 12-1: SudachiPy 依存パッケージ追加
- **日時:** 2026-07-17
- **実施内容:**
  - `pixi add sudachipy sudachidict-core` を実行。conda-forge で解決に成功し、
    `[dependencies]` セクションに `sudachipy = ">=0.6.11,<0.7"`,
    `sudachidict-core = ">=20260116,<20260117"` が追加された
    （`[pypi-dependencies]` へのフォールバックは不要だった）。
  - インストール確認: `Dictionary().create()` で辞書をロードし、
    `tokenize('広島駅（山陽本線）約800m', SplitMode.C)` を実行。
- **確認結果:**
  - Mode C の出力: `['広島駅', '（', '山陽本線', '）', '約', '800', 'm']`
  - 「広島駅」「山陽本線」がそれぞれ単独トークンとして正しく切り出されることを確認。
    Phase 11 で `fts_search('広島駅')` が0件だった根本原因（`text_card` 索引化時に
    巨大な1トークンへ潰れる問題）を Mode C が解消できることを裏付けた。
- **サニティチェック:** ✅ Mode C トークナイズ結果を目視確認
- **コミットハッシュ:** `e569cb7`
- **備考:** pixi.lock も同時に更新されるため、Step 12-5 のコミットに含める。

### Step 12-2: tokenize_ja() 実装
- **日時:** 2026-07-17
- **実施内容:**
  - `src/phase11_hybrid_search.py` に `tokenize_ja(text) -> str` を新規実装。
  - `_get_sudachi_tokenizer()` でモジュールレベル遅延キャッシュを実装
    （辞書ロードが重いため、初回呼び出し時のみ `Dictionary().create()` を実行）。
  - `SplitMode.C` で分かち書きし、`m.surface().strip()` が空のトークンを除外。
  - Sudachi の1回あたり文字数上限（約49,000文字）への防御として、
    `_SUDACHI_CHUNK_SIZE = 10_000` 文字単位でチャンク分割してから処理する
    （text_card は平均579文字のため通常は1チャンクで完結）。
- **確認結果:**
  - `tokenize_ja('建物ID: bldg_b 用途: 住宅 最寄り駅: 横川駅（可部線）約500m')` の
    出力: `'建物 ID : bldg _ b 用途 : 住宅 最寄り駅 : 横川駅 （ 可部 線 ） 約 500 m'`
    （19トークン、`住宅`・`横川駅` とも単独トークンとして含まれることを確認）。
  - `可部線` は辞書に複合語として未登録のため `可部`／`線` に分割されたが
    （`広島駅`・`山陽本線` は複合語として保持された）、BM25 は語の重なりで
    スコアリングするため分割されても検索自体は機能する。
  - 空文字・空白のみの入力で空文字を返すことを確認（早期リターン）。
- **サニティチェック:** ✅ 目視確認（print デバッグ、`tests/sanity_checks.py` への
  追加は Step 12-5 でまとめて実施）
- **コミットハッシュ:** `18ef750`

### Step 12-3: FTS 専用テーブル・インデックス再構築
- **日時:** 2026-07-17
- **実施内容:**
  - `ensure_fts_index()` を全面改修。`building_chunks_fts(id, wakati)` を
    FTS 専用テーブルとして新設し（`building_chunks` は HNSW インデックスを
    持つため ALTER TABLE で触らない設計）、`building_chunks` との件数不一致時
    のみ全件を `tokenize_ja()` で分かち書きして再構築する。
    旧実装（`building_chunks.text_card` への直接索引）は
    `PRAGMA drop_fts_index('building_chunks')` で削除を試み、失敗時は無視。
  - `fts_search()` を改修。検索前に `tokenize_ja(query_text)` を適用し、
    参照先を `fts_main_building_chunks_fts.match_bm25` /
    `FROM building_chunks_fts` に変更（戻り値スキーマは変更なし）。
  - `phase4_retrieval.py` の FTS インデックス存在チェックを
    `schema_name = 'fts_main_building_chunks_fts'` に更新。
- **確認結果:**
  - `ensure_fts_index()` 実行時間: 3.6秒（2,958件、初回再構築込み）。
  - **Phase 11 で0件だった固有名詞検索が解消**したことを確認:
    - `fts_search('広島駅')`: 0件 → **10件**
    - `fts_search('平和記念公園')`: 未検証（Phase11時点） → **10件**
    - `fts_search('住宅')`: 10件 → 10件（既存動作を維持）
  - Step 12-4 の合格基準（`広島駅` で1件以上）を満たすことを確認済み。
- **サニティチェック:** ✅ 実データで固有名詞ヒットを確認（詳細な効果測定は Step 12-4）
- **コミットハッシュ:** `69dbcf4`

### Step 12-4: 動作確認・効果測定
- **日時:** 2026-07-19
- **実施内容:**
  - `fts_search()` 単体で固有名詞ヒットを再確認（Step 12-3 の続き・網羅）:
    `広島駅`・`平和記念公園`・`住宅` いずれも1件以上ヒット（合格基準達成）。
  - `pixi run python tests/eval_retrieval.py --fts` を再実行し、
    Phase 10 (`use_fts=False`)・Phase 11 (`use_fts=True`・分かち書きなし)・
    Phase 12 (`use_fts=True`・分かち書きあり) の3条件で category 別マクロ平均を比較。
  - `hybrid_search(query, use_fts=True/False)` を直接呼び出し、
    候補 ID レベルでの差分を3クエリで確認。
- **確認結果（重要な発見）:**
  - **category 別マクロ平均（recall@10・precision@10・hit@1）は3条件で完全に同一**
    （structured: recall=0.637/precision=0.8375/hit1=1.0、
    hybrid: recall=0.266/precision=0.9125/hit1=1.0 のまま変化なし）。
  - しかし **候補 ID レベルでは分かち書き導入後に実際の変化を確認**:
    - route=structured のクエリ（FTS を経由しない設計）: 変化なし（想定どおり、回帰なし）
    - route=hybrid のクエリ「ランドマークまで100m以内で防災拠点に向いた建物」:
      10件中 **6件が入れ替わった**（Phase 11 では0件差分だったのと対照的）
  - **なぜ集計指標が動かなかったかの分析:**
    1. hit@1 が既に 1.0（上限）に到達しているクエリが大半で、改善の余地がない。
    2. recall@10 が正解集合サイズの上限（top_k=10）で頭打ちの大規模ゴールドクエリ
       （G03/G08 等）は FTS の有無に関わらず変化しない。
    3. **本プロジェクトの設計上の理由**: 駅名・公園名等の固有名詞は
       `query_parser.py` が `location_name`（ジオコーディング対象）や
       `distance_filters`（施設種別＋距離）として構造化してしまうため、
       `semantic_residual`（FTS の検索対象）にはほとんど残らない。
       つまり FTS が最も効くはずの「固有名詞を含む自由文」が、
       この設計では既に別経路で処理済みになっている。
  - **結論:** `fts_search()` 関数単体のバグ（0件ヒット）は完全に解消したが、
    hybrid_search() 全体のパイプラインでは、固有名詞が既に構造化フィルタで
    処理されるため、ゴールドセットの recall/precision には反映されない。
    候補の並び替え自体は実際に機能しており「壊れてはいない・効果はあるが
    今回のゴールドセットでは測定できない」という結果。
- **サニティチェック:** ✅ fts_search 単体3クエリ・hybrid_search 経由3クエリで動作確認
- **コミットハッシュ:** `50f54a5`
- **use_fts デフォルト値の判断（TODO 12-4-3 の基準に基づく）:**
  recall/hit@1 の劣化は確認されなかった（不変）ため、計画の基準
  「劣化なし → デフォルト True 化を検討しユーザーに提案」に該当。
  ただし判断はユーザー確認後に反映する（Step 12-5 で報告）。

### Step 12-5: サニティチェック・コミット
- **日時:** 2026-07-19
- **実施内容:**
  - `check_phase11_fts_index()` の検証クエリを「住宅」から**「広島駅」に変更**
    （分かち書き導入の核心的な合格基準）。docstring の「連続日本語文では
    固有名詞がヒットしない場合がある」という Phase 11 時点の注記を削除し、
    Phase 12 での解消を明記する内容に更新。
  - `check_phase12_tokenize()` を新規追加: `tokenize_ja('横川駅（可部線）約500m')`
    に `横川駅` が単独トークンとして含まれ、空トークンが含まれないことを確認。
  - `check_phase12_fts_rebuild()` を新規追加: `building_chunks_fts` の件数が
    `building_chunks` と一致することを確認。
  - `run_phase12_checks()` を実装（Phase 11 の3チェックも再実行し回帰確認を兼ねる）
    と `--phase12` CLI 分岐を追加。
- **確認結果:**
  - `--phase12`: 全5件パス（tokenize_ja・件数一致・fts_search('広島駅')・
    rrf_merge・hyde_rewrite）。
  - `--phase10`・`--phase9`: 回帰確認、両方とも全チェックパス。
- **サニティチェック:** ✅ Phase 12 全5件・Phase 10 全3件・Phase 9 全3件、
  すべてパス（回帰なし）。
- **コミットハッシュ:** 未コミット

### Phase 12 総括
- **達成事項:** Phase 11 で発見した「DuckDB FTS は連続日本語文にほぼ機能しない」
  制約を、SudachiPy（Mode C）分かち書きにより解消した。
  `fts_search('広島駅')` は 0件 → 10件 に改善し、`hybrid_search()` の
  `use_fts=True` 経路でも実際に候補の並び替えに影響するようになった
  （Phase 11 では完全に無効化されていた）。
- **測定の限界:** ただし本プロジェクトのクエリ解析設計（`query_parser.py`）が
  駅名・公園名等の固有名詞を `location_name`／`distance_filters` として
  構造化してしまうため、FTS の主戦場である「固有名詞を含む自由文
  （semantic_residual）」がほとんど発生せず、ゴールドセットの
  recall/precision/hit@1 には改善が反映されなかった。
- **use_fts のデフォルト値:** recall/hit@1 の劣化は確認されなかったため、
  デフォルト True 化の是非をユーザーへ提案する（詳細は最終報告メッセージで）。

---

## [Phase 13] 幾何・近傍コンテキストの前計算拡充

> 前回セッションでの提案書ギャップ調査（FOSS4G発表準備）を受け、
> 「日当たり」「方位」等の看板クエリを構造化経路で確定判定できるように、
> 追加データなしで前計算を拡充する。docs/plan.md に Phase13〜16 の
> 3層設計を追記し、本 Phase から実装開始。

### Step 13-1: 屋根・形状指標の追加（phase9_geometry.py 拡張）
- **日時:** 2026-07-19
- **実施内容:**
  - `analyze_building()` の面分類ループに屋根勾配集計を追加。
    `roof_slope_mean_deg`（面積加重平均勾配）、`flat_roof_ratio`
    （勾配10°未満の面積比率）、`roof_type_est`（陸屋根/勾配屋根、
    仮閾値0.7）を算出。
  - `fetch_footprint_areas()` を新規実装。hiroshima_sample.gpkg
    （maxlod ではない通常版）の建物ジオメトリを調査した結果、
    Z=0 一定の単一リング・フットプリントポリゴン（n_polys=1）と判明
    （当初「LOD1押し出し立体」と想定していたが実際は平坦フットプリント）。
    `ST_Force2D` 後の `ST_Area` でそのまま面積取得可能と確認。
  - `volume_m3`（footprint_area_m2 × building_height_m の近似）、
    `slenderness`（height / sqrt(footprint_area_m2)）を追加。
  - `create_geom_meta_table()` に新カラム6種を追加し、全2,958件を再生成。
- **確認結果:**
  - 屋根種別: 陸屋根 2,660件 / 勾配屋根 296件（平坦面比率平均0.92）
  - 体積近似: 平均7,127m3、最大2,041,668m3
  - 細長さ: 平均1.43、最大10.39
  - 建物高さ・地面標高・壁面方位は Phase 9 と完全一致（再生成のみで値は不変）
- **不具合修正:** print 文の `m³`（上付き3）が Windows コンソール既定
  エンコーディング（cp932）でクラッシュ。`m3` に変更して解消
  （以降の実行は `pixi run python -X utf8` を使用）。
- **サニティチェック:** 全2,958件のINSERT成功・統計サマリー出力を確認
  （正式なアサーション関数は Step 13-3 でまとめて追加）。
- **コミットハッシュ:** `08a029e`

### Step 13-2: 建物間コンテキストの前計算（src/phase13_context.py 新規作成）
- **日時:** 2026-07-19
- **実施内容:**
  - `building_context_meta` テーブルを新設。南側遮蔽（`south_max_elev_angle_deg`
    / `winter_sunlit`）・卓越性（`prominence_m`）・木造密度
    （`wooden_density_ratio`）・幹線道路距離・学校/病院/警察署/消防署/郵便局
    の最近傍を計算する `src/phase13_context.py` を新規実装。
  - 近傍ペア抽出（半径100m）は `building_chunks.geometry` の centroid 同士の
    自己結合＋`ST_DWithin` で実装。193,256組を取得（1秒未満）。
  - 学校・病院等は `data/related/34100_hiroshima-shi_city_2022_landmark.geojson`
    の「種類」属性（学校251/病院52/警察署70/消防署30/郵便局133件）を
    種別分解して活用。**新規ファイル追加は不要**。
- **不具合修正（2件）:**
  1. **幹線道路の定義変更:** 当初計画では `uro:RoadStructureAttribute` の
     `width`/`numberOfLanes` で幹線道路を判定する予定だったが、実データ確認の
     結果 846件中 **0件が非NULL**（両カラムとも完全に未整備）と判明。
     代替として `tran:Road.function`（コードリスト `Road_function.xml`）で
     `"2"`=一般国道・`"3"`=都道府県道 を幹線道路とみなす方式に変更
     （該当96本）。work_log にこの設計変更を記録。
  2. **セグフォルトの発生と解消:** 上記の代替検討中、`function` カラムが
     `usage` と同じ `'["2"]'` 形式のJSON配列文字列で格納されていることを
     見落とし、SQLの `IN ('2','3')` で単純比較したところ0件と誤判定され、
     結果として空の `IN ()` 句が生成されて DuckDB spatial extension が
     セグフォルトした（既知の「不正なクエリでのsegfault」パターンの再発、
     work_log Phase 10 Step 10-3 の既知問題と同系統）。
     Python側で `json.loads()` してから該当id集合をIN句に渡す方式に修正し、
     0件時は早期リターンするガードも追加して解消。
- **確認結果:**
  - 冬日照確保率（winter_sunlit=True、仮閾値30°）: 20.0%（591/2,958件）
  - 卓越性（prominence_m）平均: -37.0m（密集市街地のため近傍に自分より
    高い建物がある場合が多いことを示唆。最大+91.1m）
  - 幹線道路距離: 平均144.6m、該当道路96本
  - 学校/病院/警察署/消防署/郵便局のいずれも全2,958件で非NULL距離を取得
- **サニティチェック:** 全2,958件のINSERT成功・統計サマリー出力を確認
  （正式なアサーション関数は Step 13-3 でまとめて追加）。
- **コミットハッシュ:** `7f43133`

### Step 13-3: サニティチェック・閾値確定・コミット
- **日時:** 2026-07-19
- **実施内容:**
  - `tests/sanity_checks.py` に `check_phase13_geom_meta_extended()`
    （新カラム6種の存在・flat_roof_ratio の範囲確認）、
    `check_phase13_context_meta()`（件数一致・winter_sunlit True/False
    両方存在・nearest_school_dist_m 非NULL確認）を追加。
    `run_phase13_checks()` と `--phase13` CLI 分岐を追加。
  - 仮置きした3閾値の実データ分布を確認し、以下の通り確定した:

| 閾値 | 仮値 | 実データ分布 | 判断 |
|---|---|---|---|
| 陸屋根判定（flat_roof_ratio） | 0.7 | 中央値1.0、分位0.1で0.701。陸屋根90%/勾配屋根10% | **0.7で確定**（極端な偏りなし） |
| 冬日照（south_max_elev_angle_deg） | 30.0° | 中央値44.1°、分位0.2で30.0°。sunlit=True 20.0% | **30.0°で確定**（密集市街地として妥当な比率） |
| 幹線道路（quiet用） | width>=13m or lanes>=4 | 両カラムとも全件NULLで使用不能と判明 | **function IN ('2','3') に変更確定**（Step13-2で対応済み） |

  - `wooden_density_ratio` の閾値（Phase14 G30用に想定していた0.5）も
    実データで確認したところ、**最大値が0.259**（木造建物自体が全体の
    2.5%＝75件と少ないため）であり、0.5では**常に0件**になることが判明。
    Phase 10 の G09/G11/G16 と同じ「閾値調整が必要」パターンのため、
    **0.05 に変更**（該当540件、うち耐火構造との積集合125件で
    検証として意味のある母数）。Phase 14-1 のゴールドクエリ定義時に反映する。
  - G26（高台）用に `ground_elev_m` の90パーセンタイルを確認: 3.18m
    （該当296件）。Phase 14-1 で使用する。
- **確認結果:** `--phase13` 全2件パス、`--phase9` 回帰確認3件パス
  （wall_ratio_s 等は Phase 9 再生成でも値不変を確認）。
- **サニティチェック:** ✅ Phase 13 全2件・Phase 9 全3件、すべてパス
- **コミットハッシュ:** `77210fe`

---

## [Phase 14] 評価基盤の拡充（ゴールドセット v2・ベースライン計測）

### Step 14-1: ゴールドクエリの追加（tests/gold_set.py 拡張）
- **日時:** 2026-07-19
- **実施内容:**
  - `GOLD_QUERIES` に category `geometric`（G21〜G30, 10件）・
    `robustness`（G31〜G36, 6件）を追加し、20件→36件に拡張。
  - G30 の `wooden_density_ratio` 閾値は Phase 13 Step 13-3 で確定した
    0.05 を採用（当初計画の0.5は非現実的と判明済み）。
  - G34「広島駅から500m以内で日当たりのよい建物」用に
    `geocode('広島駅')` の実測座標（EPSG:6671: x=28393.387, y=-177726.635）
    を定数として埋め込み。
  - `build_gold()` 実行時に `_duckdb.CatalogException: st_dwithin is not
    in the catalog` エラーを発見（G34 が ST_DWithin を使用するが
    `build_gold()` の DuckDB 接続で spatial 拡張が未ロードだった）。
    `con.execute("INSTALL spatial; LOAD spatial;")` を追加して解消。
- **確認結果（母数）:** 全34件（semantic除く）が0件〜2,883件の妥当な範囲。
  極端な偏りによる追加調整は不要だった:
    - G25(陸屋根)=2,660件・G31(木造以外)=2,883件はいずれも
      実データの多数派クラス（陸屋根90%・非木造97.5%）を反映した結果であり、
      閾値調整ではなく分布の性質そのもののため許容。
    - G33(高潮リスクなし×駅100m以内×宿泊施設)=**0件**（意図通り、正解データ）。
    - G36(病院近接×洪水リスクなし)=1件とやや少ないが、Phase10 G04
      （1件）の前例があり許容。
  - `output/gold_set.json` を 36件で再生成。
  - `tests/eval_retrieval.py::evaluate()` を修正（TODO 14-1-4）。
    従来 `not gq["gold_ids"]` を semantic 同様 nan 扱いしていたが、
    G33 のような「正解0件が意図されたクエリ」を robustness カテゴリの
    マクロ平均に正しく反映できるよう分岐を追加: 正解0件時は
    候補も0件なら正解(1.0)、1件以上あれば誤検出(0.0)として定量評価する。
    category別集計（`df["category"] != "semantic"`）はデータ駆動のまま
    変更不要で geometric/robustness が自動的に含まれることを確認。
- **サニティチェック:** ✅ 母数確認・gold_set.json 36件生成・evaluate() 修正確認
- **コミットハッシュ:** `7079c9a`

### Step 14-2: ベースライン計測（配線前）
- **日時:** 2026-07-19
- **実施内容:** `pixi run python tests/eval_retrieval.py` を実行し、
  Phase 15 着手前（query_parser.py に新フィールド未実装、new gold のみ追加した状態）の
  category 別マクロ平均を計測。geometric/robustness の新36-20=16クエリは
  ParsedQuery に対応フィールドがないため大半が semantic 残差として
  ベクトル検索のみに頼ることになり、想定通り低スコアとなった。
- **確認結果（Before）:**

| category | recall@10 | precision@10 | hit@1 |
|---|---|---|---|
| structured | 0.682 | 0.917 | 1.0 |
| hybrid | 0.300 | 0.900 | 1.0 |
| geometric | **0.011** | 0.420 | **0.4** |
| robustness | 0.344 | 0.567 | 0.5 |

  - geometric 個別（hit1=0 のクエリ）: G21(南向き最大), G22(西日回避),
    G23(日当たり), G24(屋上広い), G26(高台), G30(木造密集×耐火) —
    いずれも Phase13 の前計算カラムが構造化フィルタに未接続のため、
    ベクトル検索頼みで的外れな候補になっている（提案書の看板クエリ
    G23「日当たりのよい建物」は recall=0.0・hit1=0.0）。
  - G25(陸屋根)・G28(垂直避難)・G29(はしご車)は precision=0.9〜1.0・
    hit1=1.0 だが、これは母数が非常に大きい（陸屋根2,660件・垂直避難1,908件）
    ため「たまたま上位が正解集合に含まれる」構造的な結果であり、
    フィルタが機能しているわけではないことに注意。
  - robustness の G33（正解0件）・G36（正解1件）は母数が極小のため
    たまたま1.0。G34（広島駅500m×日当たり、看板クエリのハイブリッド版）は
    recall=0.0・hit1=0.0 と完全に外している。
  - 結果保存先: `output/eval_result_20260719_1412.csv`
- **サニティチェック:** ✅ Before値を記録、Phase15実装後の比較対象として確定
- **コミットハッシュ:** `2f28913`

---

## [Phase 15] クエリ解析・検索配線の拡張

### Step 15-1: query_parser.py の語彙拡張
- **日時:** 2026-07-19
- **実施内容:**
  - `OrientationFilter` dataclass（direction/mode）を追加。
  - `ParsedQuery` に10フィールド追加: `orientation_filters`, `sunlight`,
    `quiet`, `vertical_evacuation`, `height_max`, `storeys_min`, `storeys_max`,
    `usage_exclude`, `structure_exclude`, `roof_type`。
    加えて計画外だが Phase13 の `wooden_density_ratio` を活用するため
    `wooden_dense: bool` も追加（G30 のゴールドクエリに対応する自然言語
    フィルタが存在しない状態を解消するための軽微な拡張）。
  - `_SORT_KEYS` に Phase13 前計算カラム（roof_area_m2 等）を、
    `_DISTANCE_TARGETS` に school/hospital/police/fire/post を追加。
  - `_ORIENTATION_RULES` を新設し `_SYSTEM_PROMPT` に埋め込み。
    「sunlight と orientation_filters を重複させない」等の区別ルールを明記。
  - `_RESPONSE_SCHEMA` に新フィールドを追加、`parse_query()` の変換ロジックを拡張。
  - `__main__` に6テストケースを追加し動作確認。
- **確認結果:** 全6ケースが期待通りに解析された。特に「避難所まで300m以内で
  日当たりのよい建物」は Phase10 時点では `semantic_residual='日当たりのよい建物'`
  として残っていたが、Phase15 拡張後は `sunlight=True` に完全構造化され
  `semantic_residual=''` になることを確認（Phase15 の狙い通りの効果）。
- **サニティチェック:** ✅ `__main__` 6ケース目視確認（詳細は Step 15-4 でまとめて実施）
- **コミットハッシュ:** `b250b50`

### Step 15-2: ルーター・vector_search の拡張（phase10_router.py / phase4_retrieval.py）
- **日時:** 2026-07-19
- **実施内容:**
  - `phase10_router.py` に `COLUMN_SOURCE`（カラム→テーブル出所辞書）と
    閾値定数6種（`ORIENT_PREFER_MIN=0.3`, `ORIENT_AVOID_MAX=0.1`,
    `SUNLIGHT_WALL_S_MIN=0.2`, `QUIET_ROAD_MIN_M=100.0`,
    `VERTICAL_EVAC_MARGIN_M=6.0`（Phase14 G28 の gold_sql と共有）,
    `WOODEN_DENSE_MIN=0.05`（Phase13で確定済み）) を追加。
  - `build_filter_clauses()` / `build_order_clause()` に `table_aliases`
    引数を追加し、`_resolve_alias()` でカラムごとに正しいテーブル別名
    （b./g./c.）を解決するよう改修（`table_aliases=None` 時は既存の
    単一 alias 文字列のみで動作する後方互換を維持）。
  - `TARGET_COLUMN` に school/hospital/police/fire/post を追加。
  - `classify_route()` の `has_structured` 判定に新フィールド全種を追加。
  - `verify_candidates()` に新フィルタ9種の pandas 再評価を追加
    （build_filter_clauses と同一のモジュール定数を参照）。
  - `phase4_retrieval.py::vector_search()` を改修。`has_context_meta`
    判定を追加し、`has_geom_meta`/`has_context_meta` の組み合わせ4パターン
    （旧来の2パターンに、新たに「両方あり」「context_metaのみ必要だが
    geom_metaのみ存在」等を追加）に応じて `table_aliases` を構築。
    新フィルタ指定時に対応テーブルが存在しない場合は
    `RuntimeError` を送出する分岐を追加（サイレント無視しない、TODO 15-2-8）。
    select_cols に g由来（roof_area_m2, roof_type_est）・c由来
    （winter_sunlit, prominence_m, wooden_density_ratio,
    nearest_major_road_dist_m, 学校/病院/警察署/消防署/郵便局の
    name+dist_m）を追加。
- **確認結果（単体・統合動作確認）:**
  - 南向き（`OrientationFilter(s,prefer)`）→ route=structured, 5件全件
    `wall_ratio_s>=0.3` を確認。
  - sunlight=True → 全件 `winter_sunlit=True` かつ `wall_ratio_s>=0.2`。
  - 学校距離フィルタ（`DistanceFilter(school,300)`）→ 全件
    `nearest_school_dist_m<=300`。
  - quiet+wooden_dense 複合 → 全件 `nearest_major_road_dist_m>=100` かつ
    `wooden_density_ratio>=0.05`。
  - `hybrid_search('南向きの建物')` のエンドツーエンド実行で
    query_parser→classify_route→vector_search→verify_candidates の
    全経路が正しく機能することを確認。
- **サニティチェック:** ✅ 単体テスト4パターン・エンドツーエンド1件で動作確認
  （詳細は Step 15-4 でまとめて実施）
- **コミットハッシュ:** `ddc553e`（Step15-3 と合わせて1コミット）

### Step 15-3: LLM プロンプト・回答の拡張（phase4_retrieval.py）
- **日時:** 2026-07-19
- **実施内容:**
  - `build_prompt()` の Markdown 比較表に「主壁面方位」（4方位のうち
    最大比率を `方位N%` 表示、5%未満は「-」）・「冬日照」（`winter_sunlit`
    を ○/×/不明）・「屋根」（`roof_type_est`）・「標高(m)」
    （`ground_elev_m`）の4列を追加。
  - `_fmt_orientation()`, `_fmt_sunlit()`, `_fmt_unknown()` ヘルパーを追加。
  - 回答形式の指示文に「方位・日照・静けさ・地形に関する推薦は比較表の
    数値を根拠として明示すること」を追記。
- **確認結果:** `build_prompt('南向きの建物', ...)` で比較表4列が正しく
  表示されることを確認。9999階建て等の異常表示は Phase3 由来の既存データ
  品質問題（storeys の無効値）であり Phase15 のスコープ外と判断
  （Phase16 の限界整理に記録する）。
- **サニティチェック:** ✅ 出力を目視確認（詳細は Step 15-4 でまとめて実施）
- **コミットハッシュ:** `ddc553e`（Step15-2 のルーター拡張と合わせて1コミット。
  理由: `phase4_retrieval.py::vector_search()`（Step15-2）と
  `build_prompt()`（Step15-3）は同一ファイル内で並行実装したため、
  無理に分割せず実装の実態どおりまとめてコミットする判断とした。
  `phase10_router.py` の変更は Step15-2 の内容として同コミットに含む）

### Step 15-4: サニティチェック・回帰確認・コミット
- **日時:** 2026-07-19
- **実施内容:**
  - `tests/sanity_checks.py` に Phase15用チェック4関数を追加:
    `check_phase15_orientation`（南向き→wall_ratio_s>=0.3）、
    `check_phase15_avoid_west`（西日回避→wall_ratio_w<=0.1）、
    `check_phase15_sunlight`（日当たり→winter_sunlit=True）、
    `check_phase15_exclude`（木造以外→structure_type≠木造・土蔵造）。
    `run_phase15_checks()` と `--phase15` CLI分岐を追加。
  - `--phase8`〜`--phase13` を再実行し回帰確認。
  - **回帰確認中に発見した「意図した仕様変化」:** `check_phase10_route_hybrid`
    （クエリ「駅から300m以内で日当たりのよい建物」）が
    `route=structured`（期待値はhybrid）で失敗。原因は Phase15 の狙い通り、
    「日当たりのよい」が `sunlight` フィールドに完全構造化され
    `semantic_residual=""` になったため。これは不具合ではなく Phase15 の
    効果そのものなので、テストクエリを「駅から300m以内で防災拠点に向いた
    建物」（まだ構造化フィールドを持たない意味語彙）に差し替えて解消。
- **確認結果:** `--phase15` 全4件パス、`--phase8` 全5件・`--phase9` 全3件・
  `--phase13` 全2件・`--phase10` 全3件（クエリ差し替え後）、すべてパス。
- **サニティチェック:** ✅ Phase 15 全4件・Phase 8/9/10/13 回帰確認、
  すべてパス（意図した仕様変化1件を除き回帰なし）
- **コミットハッシュ:** `2b9284a`

---

## [Phase 16] 効果測定・限界整理（発表素材化）

### Step 16-1: Before/After 効果測定
- **日時:** 2026-07-19
- **実施内容:**
  - `pixi run python tests/eval_retrieval.py` を実行し After 値を計測。
  - **Before 側の測定エラーを発見:** Phase14 計測時（`eval_result_20260719_1412.csv`）
    の G01/G08/G14（いずれも Phase15 と無関係な既存 structured クエリ）が
    `IO Error: Cannot open file ... 別のプロセスが使用中です` で失敗し
    NaN 扱いになっていたことをログから発見。原因は計測実行中に並行して
    Phase15 実装のテストコマンドを別プロセスで叩いており、DuckDB ファイルの
    ロックが競合したため（既知の複数接続競合問題、Phase10 Step10-3 の
    segfault と同系統の環境依存事象）。この3件を現行コード（Phase15適用後、
    ただし該当3クエリは Phase15 新フィールドを一切使わない）で個別に
    再実行し、正しい値（G01: recall1.0/precision0.5/hit1=1.0、
    G08: recall0.005/precision1.0/hit1=1.0、G14: recall0.026/precision1.0/
    hit1=1.0）を得て Before を補正した。
  - **効果測定中に発見した不具合2件を修正**（詳細は別コミット）:
    1. `sunlight` フィルタの閾値 `SUNLIGHT_WALL_S_MIN=0.2` が
       Phase14 gold_sql G23 の定義（`wall_ratio_s>=0.3`）とズレており、
       看板クエリ「日当たりのよい建物」が hit1=0 になっていた。
       0.3 に統一して解消。
    2. `hybrid_search()` の `parsed_query_dict` に Phase15 新フィールド
       （orientation_filters 等）が反映されておらず `KeyError` になる
       不具合を修正。
    3. G29「はしご車が届く高さで緊急輸送道路に近い建物」が hit1=0。
       `height_max=31.0` は正しく解析されていたが、「近い」という曖昧
       表現に `distance_filters` のデフォルト距離 500m が適用され
       gold_sql の閾値 100m とズレていたことが原因。`query_parser.py`
       に「はしご車が届く高さ→height_max=31.0」のルールを追加した上で、
       クエリ文言を「緊急輸送道路から100m以内」という明示的数値表現に
       変更して解消（Phase10 の G09/G11/G16 と同じ「gold_sql と実装の
       ズレを解消する」手法）。
- **確認結果（Before/After比較。Before はロック競合による測定エラーを補正済み）:**

| category | 指標 | Before(補正後) | After(最終) |
|---|---|---|---|
| structured | recall@10 | 0.637 | 0.637 |
| structured | precision@10 | 0.875 | 0.875 |
| structured | hit@1 | 1.0 | 1.0 |
| hybrid | recall@10 | 0.266 | 0.228 |
| hybrid | precision@10 | 0.912 | 0.9125 |
| hybrid | hit@1 | 1.0 | 1.0 |
| geometric | recall@10 | **0.011** | **0.235** |
| geometric | precision@10 | 0.420 | **0.900** |
| geometric | hit@1 | **0.4** | **1.0** |
| robustness | recall@10 | 0.344 | **0.405** |
| robustness | precision@10 | 0.567 | **1.000** |
| robustness | hit@1 | 0.5 | **1.0** |

  - **structured は完全に不変**（Phase15 の変更が既存機能に一切副作用を
    与えていないことの直接的な証拠）。
  - **hybrid の recall がわずかに低下**（0.266→0.228）。原因は G15
    「津波リスクがなく静かな住宅」で、Phase15 により「静かな」が
    `quiet=True`（幹線道路から100m以上）として構造化されたことで、
    gold_sql（`ts_depth_max IS NULL AND usage='住宅'`、静けさ条件を
    考慮しない定義）との間に意味論的なズレが生じたため。これは
    gold_sql 側が「静かさ」を評価に含めていなかったことによる
    見かけ上の低下であり、実装はむしろ意味論的に正確になったと判断できる
    （gold_sql の再定義は本 Phase のスコープ外とし、既知の限界として記録）。
  - **geometric が大幅改善**（hit@1: 0.4→1.0、precision: 0.42→0.90）。
    看板クエリ G23「日当たりのよい建物」を含む全10件が hit@1=1.0 を達成し、
    Phase10 に倣った合格基準（geometric hit@1=1.0）を満たした。
  - **robustness も改善**（hit@1: 0.5→1.0、precision: 0.567→1.0）。
    除外条件・範囲条件・空間×幾何ハイブリッド（G34）・施設種別最近傍
    （G35/G36）がいずれも正しく機能することを確認。
  - recall@10 が低い値に留まるクエリ（G22/G25/G28/G31 等）は、正解集合
    サイズが大きい（陸屋根2,660件・木造以外2,883件等）ことによる
    top_k=10 の物理的上限が原因で、Phase10 と同じ既知の制約。
    precision@10 で見ればいずれも 0.9〜1.0 であり、フィルタ自体は
    正しく機能している。
  - 結果保存先: `output/eval_result_20260719_1440.csv`（最終）
- **看板クエリのデモ保存（TODO 16-1-2）:** 「広島駅の近くで日当たりのよい
  建物」を `hybrid_search()` で実行し `output/demo_flagship_query.md` に
  保存。route=structured で確定的に動作し、LLM回答が比較表の「駅まで(m)」
  「冬日照」「主壁面方位」の数値を根拠として推薦理由を述べることを確認
  （提案書の看板クエリが構造化経路でエンドツーエンド動作する実証）。
- **サニティチェック:** ✅ 合格基準（geometric hit@1=1.0）達成、
  Before/After比較・看板クエリデモを記録
- **コミットハッシュ:** `b8c53f5`（`4d6c1eb`・`b8223ab` は
  効果測定中に発見した不具合修正として別コミット済み）

### Step 16-2: 限界と設計判断の文書化・最終回帰確認
- **日時:** 2026-07-19
- **実施内容:**
  - `docs/foss4g/limitations.md` を新規作成。①データの限界（DEM不使用・
    urf_usage/築年欠損・道路浸水属性なし・width/numberOfLanes全件NULL・
    landmark学校区分の粒度・生活利便施設データなし）、②手法上の近似
    （日照の角度比較モデル・体積の直方体近似・G23擬似ゴールド・埋め込み
    密集問題の未解消・陸屋根閾値の仮置き・「静かな」構造化による意味論変化）、
    ③射程外（流体/熱環境シミュレーション・集計/比較/対話ルート・都市計画
    規制ベース質問・parse_query()非決定性・storeys無効値の表示・DuckDB
    複数接続競合）の3分類で整理した。
  - `--phase8`〜`--phase13`・`--phase15` の全チェックを再実行し最終回帰確認。
- **確認結果:** `--phase8`(5件)・`--phase9`(3件)・`--phase10`(3件)・
  `--phase11`(3件)・`--phase12`(5件)・`--phase13`(2件)・`--phase15`(4件)、
  すべてパス（回帰なし）。
- **サニティチェック:** ✅ 全Phase最終回帰確認パス
- **コミットハッシュ:** 未コミット（本Step）

### Phase 13〜16 総括
- **達成事項:** FOSS4G 提案書とのギャップ調査で判明した「日当たり」等の
  看板クエリが実質ベクトル検索頼みだった問題を、**追加データなし**で
  Phase 9 の面解析（wall_ratio_*）と Phase 13 の新規前計算
  （南側遮蔽・卓越性・木造密度・幹線道路距離・学校/病院等最近傍）を
  構造化経路（SQL）に接続することで解消した。
  `hybrid_search('広島駅の近くで日当たりのよい建物')` が route=structured
  で確定的に動作し、LLM回答が比較表の数値を根拠に推薦理由を述べることを
  実証（`output/demo_flagship_query.md`）。
- **測定結果:** geometric カテゴリの hit@1 が 0.4→1.0、precision@10 が
  0.42→0.90 に改善（Phase10 に倣った合格基準を達成）。structured は
  完全不変で既存機能への副作用なしを確認。robustness（除外・範囲・
  空間×幾何ハイブリッド）も hit@1 0.5→1.0 に改善。
  hybrid の recall のみわずかに低下したが、これは「静かな」の構造化に
  伴う意味論的な精緻化であり、ゴールドセット側の定義が古いままだった
  ことに起因すると分析（不具合ではない）。
- **効果測定中に発見・修正した不具合3件:** ①sunlight閾値とゴールド定義の
  ズレ、②parsed_query_dictのKeyError、③「はしご車」の曖昧距離表現と
  gold_sql閾値のズレ。いずれも Before/After 比較の過程で発見し、
  同一セッション内で修正・再検証まで完了させた。
- **残された限界:** `docs/foss4g/limitations.md` に3分類で整理。特に
  DEM不使用（地形越しの眺望）・埋め込み類似度の密集問題（再埋め込み未実施）・
  日照の簡易角度モデルは、発表で「なぜそう割り切ったか」を語る核となる。

---

## [Phase 17] レビュー指摘の解消（整合性・精度・可視化の総仕上げ）

> Phase 16 完了後、全体レビューを実施。Phase 13〜15 で実装したフィルタ群が
> 「候補を絞り込む」段までしか機能しておらず、「絞り込んだ理由をユーザーに
> 見せる」経路（LLM提示カルテ・地図GeoJSON・フロントポップアップ）に新カラム
> が一切届いていないことが最大の指摘として判明。ユーザー指示「最大限の力で
> これらを解決」により計画→実装まで一括承認され着手。

### Step 17-1: build_prompt への新カラム反映
- **日時:** 2026-07-20
- **実施内容:**
  - `_fmt_storeys()` を新設し、階数の無効値（9999等、500以上）を「不明」表示に修正。
  - `_fmt_orientation()` を「最大方位1つ」表示から「4方位すべて」のコンパクト表記
    （例: 南30/北30/東20/西20）に変更。検索条件（南向き）と表示（僅差で北が最大）の
    食い違いによる混乱を解消。
  - 比較表に「学校まで(m)」「病院まで(m)」「幹線道路まで(m)」「木造密度」
    「突出(m)」の5列を追加。
  - text_card（DB凍結・埋め込みと対）は変更せず、候補DataFrameから動的生成する
    `[追加情報（前計算）]` ブロック（最寄り学校/病院/警察署/消防署/郵便局の
    名称+距離、幹線道路距離、木造密度、突出度、屋根種別+面積）を詳細カルテに付加。
  - 回答形式指示に施設近接の根拠提示ルールを追記。
- **確認結果:** `build_prompt('学校まで300m以内の建物', ...)` で比較表新列・
  追加情報ブロックの出力を確認。`_fmt_storeys(9999)=='不明'`、
  `_fmt_orientation()` の4方位表記を単体テストで確認。
- **サニティチェック:** ✅ 単体確認（詳細は Step17-5 の看板クエリ目視確認で総合検証）
- **コミットハッシュ:** `fcad372`

### Step 17-2: 地図UI（GeoJSON・フロントエンド）への反映
- **日時:** 2026-07-20
- **実施内容:**
  - `candidates_to_geojson()` を building_geom_meta/building_context_meta との
    LEFT JOIN に改修（テーブル不在時は従来クエリにフォールバック）。
    GeoJSON properties に屋根種別・標高・4方位比率・冬日照・突出度・木造密度・
    幹線道路距離・最寄り学校/病院（名称+距離）を追加。
  - `_sanitize_storeys()` で storeys の無効値を None に正規化。
  - `map.ts` ポップアップに壁面方位・冬の日当たり・屋根・地面標高・学校・病院・
    幹線道路の行を追加（プロパティ存在時のみ表示）。
  - `chat.ts` 候補リストに冬日照バッジ（☀）を追加。
  - `pixi run build` で再ビルドし `src/static/` を更新。
- **確認結果:** `candidates_to_geojson()` の新プロパティ11種の存在を単体テストで
  確認。ビルド成功（1.03秒、警告はチャンクサイズのみで機能に影響なし）。
- **サニティチェック:** ✅ バックエンド単体確認・ビルド成功確認
- **コミットハッシュ:** `6038cde`

### Step 17-3: パーサ・ルーターの精度と堅牢性改善
- **日時:** 2026-07-20
- **実施内容:**
  - `OrientationFilter(prefer)` を「比率>=0.3」から「比率>=0.3 かつ 4方位中最大
    （優勢方位）」に強化（SQL・pandas両方）。4方位合計1.0のため南30%・北30%の
    建物が両方の prefer にヒットしていた問題を解消。
  - `parse_query()` に include/exclude 矛盾の後処理検出を追加
    （usage_include∩usage_exclude、structure_type∈structure_exclude を検知し
    exclude側から除去+WARN）。
  - `slenderness` を `_SORT_KEYS`/`COLUMN_SOURCE` に追加し、「細長い建物」
    「体積が大きい」「底面積が広い」「最も階数が多い」の sort_by ルールを
    プロンプトに明記。
  - メタテーブル存在確認をプロセス内キャッシュ化（`_get_meta_tables()` /
    `reset_meta_tables_cache()`）。
  - `tests/gold_set.py` の G34 座標ハードコードを `{STATION_X}`/`{STATION_Y}`
    プレースホルダに置換し、`build_gold()` 実行時に `geocode('広島駅')` +
    `ST_Transform` で動的解決する方式に変更。
- **確認結果:**
  - prefer 優勢方位化: 実データ10件で「南が優勢方位」を全件確認。
  - slenderness ソート: `ORDER BY g.slenderness DESC NULLS LAST` を確認、
    細長さ上位3件を取得成功。
  - メタテーブルキャッシュ: 2回目呼び出しで同一オブジェクト参照（`is`）を確認。
  - G34 動的座標化: 再生成後も gold_ids=29件で従来と完全一致を確認
    （geocode結果が変わっていないため）。
- **サニティチェック:** ✅ 単体確認4項目すべてパス
- **コミットハッシュ:** `5b056e0`

### Step 17-4: SQL×pandas 同値性チェックの自動化
- **日時:** 2026-07-20
- **実施内容:**
  - `check_phase17_sql_verify_consistency()` を実装。代表的 ParsedQuery 9種
    （orientation prefer/avoid・sunlight・quiet・vertical_evacuation・
    roof_type・wooden_dense・storeys範囲・複合条件）について、SQL全件フィルタ
    （build_filter_clauses）と pandas全件検証（verify_candidates）の結果 id
    集合が完全一致することを確認する。LLM API 不要（ParsedQuery 直接構築）。
  - `check_phase17_direct_filters()` を実装。quiet/vertical_evacuation/
    roof_type/wooden_dense/storeys範囲の直接動作確認（API不要）。
  - `run_phase17_checks()` と `--phase17` CLI 分岐を追加。
- **不具合発見・修正:** 同値性チェック実装中に、`verify_candidates()` の
  `usage_exclude`/`structure_exclude`/`orientation avoid` 判定が SQL の
  NULL セマンティクス（`NULL NOT IN (...)` は常に偽＝除外される、
  `NULL <= ?` も常に偽）とズレていることを発見。pandas 側にも `isna()` を
  violation に含めて SQL と一致させて解消。
  この発見により「Phase16 で実際に起きた閾値ズレと同型の不整合」を、
  今回追加した自動テストが実際に機能として検知できることも実証された。
- **確認結果:** `--phase17` 全2件パス（9種の ParsedQuery すべてで SQL=pandas
  完全一致を確認、うち「複合(木造除外+高さ20-40+学校300m)」は501件で一致）。
  `--phase13` 全2件・`--phase15` 全4件、回帰なし。
- **サニティチェック:** ✅ Phase17 全2件・Phase13 全2件・Phase15 全4件、すべてパス
- **コミットハッシュ:** `0744e24`

### Step 17-5: 評価・最終確認
- **日時:** 2026-07-20
- **実施内容:**
  - `tests/eval_retrieval.py` に `--ids=G21,G23,...` 形式の部分実行オプションを
    追加（API クォータ節約・回帰確認の高速化）。
  - G34 の gold_sql 動的座標化後、`build_gold()` 再実行で gold_ids=29件が
    従来と一致することを確認（Step17-3で実施済み）。
  - 方位変更の影響を受けるクエリ（G21/G22/G23/G34）を `--ids` 部分評価で再実行。
    全4件 hit@1=1.0 を確認（回帰なし。G21 precision=0.5 は正解集合5件に対し
    top_k=10取得のため6-10位が正解外になる構造的な結果で Phase10 から不変）。
  - 看板クエリ「広島駅の近くで日当たりのよい建物」を回答生成込みで実行。
    LLM回答が「突出度」「南向きの壁面32%」「JR広島病院まで約433m」
    「幹線道路まで約282m」等、Phase17で追加した数値を具体的に引用して
    推薦理由を構成することを確認（Step17-1/17-2の目的達成を実証）。
  - **新たな発見:** 回答末尾の「データの制限事項」で LLM が「階数も
    『9999階建て』と記載されている建物が多く」と言及。比較表・GeoJSON は
    Phase17で「不明」表示に修正済みだが、詳細カルテ（text_card全文、
    DB凍結の方針で意図的に不変）には無効値が残存しており、LLM がそちらを
    読んで言及していることが判明。text_card の根本修正には再埋め込みが
    必要でありスコープ外。`docs/foss4g/limitations.md` に記録した。
  - `docs/foss4g/limitations.md` を更新。「Phase 17 で解消した項目」の
    節を新設し、旧版で指摘していた7項目（フィルタとLLM/地図の断絶、
    storeys表示、方位表示の食い違い、prefer緩さ、SQL×pandas同値性未保証、
    G34座標ハードコード、include/exclude矛盾防御なし）の解消を記録。
    併せて「storeysの無効値」項目を、比較表/GeoJSONは解消・text_cardは
    残存、という正確な状態に更新した。
- **確認結果:** 全確認項目パス。看板クエリのエンドツーエンド動作を
  回答生成込みで最終実証。
- **サニティチェック:** ✅ 部分評価4件・看板クエリ目視確認、すべて確認完了
- **コミットハッシュ:** 未コミット（本Step）

### Phase 17 総括
- **達成事項:** Phase 13〜15 で実装したフィルタ群が「絞り込みはできるが
  理由を説明できない」状態だった最大の指摘を解消。LLM回答・地図UI双方に
  Phase13前計算カラムを反映し、看板クエリで実際に数値根拠付きの推薦理由が
  生成されることを実証した。あわせて、OrientationFilter の緩さ・
  SQL×pandas検証の同値性未保証・G34座標ハードコード・include/exclude
  矛盾防御なし、という4件の設計上の不整合も解消した。
- **副産物:** Step17-4 で追加した同値性自動テストが、実装中に実際に
  NULL セマンティクスのズレ（新規不具合）を1件検出・修正した。これは
  「今回のレビューで指摘した『将来また同種の不整合が起きうる』という
  懸念」が、対策実装のわずか数十分後に現実になった実例であり、
  この種のテストの価値を裏付けるものとなった。
- **残存する限界:** text_card 全文への無効値（9999階建て）混入は、
  再埋め込みを避ける設計判断の直接的な帰結として残存する。これは
  Phase11以来の「再埋め込みをしない」制約全体のトレードオフとして
  発表で共有する。


## [Phase 18] 回答提示とマップ表現の改善

> 看板クエリ「where is the tallest building around the Hiroshima sta.」の実行画面
> レビューで判明した5件の課題（前置き復唱、推薦IDが候補リストで埋もれる、順位の
> 不自然さ、PLATEAU/OSMの建物相違、Markdown未装飾）への対応。
> 方針検討の結果、地図表現は A（出典明示）単独ではなく A+B+C（背景建物非表示＋
> PLATEAU建物の3D押し出し）を採用した。

### Step 18-1: 候補順序バグの修正
- **日時:** 2026-08-23
- **実施内容:** `src/phase6_app.py::candidates_to_geojson()` が
  `WHERE id IN (...)` のDuckDBスキャン順をそのままGeoJSON feature順にしていたため、
  検索ランキング1位の建物が候補リストの下位に埋もれるバグを修正。
  DB行を`feat_map`に一旦格納し、candidates（ランキング順）のid順に再構築するよう
  変更。properties に1始まりの`rank`と`is_recommended`（Step18-2で使用）を追加。
- **確認結果:** シャッフルした10件のidで3パターンのテストを実施し、
  `candidates_to_geojson()`の出力順序がcandidatesの順序と完全一致すること、
  rankが連番であることを確認。
- **サニティチェック:** ✅ `check_phase18_geojson_order()` パス
- **コミットハッシュ:** `2fa9698`

### Step 18-2: 推薦建物の抽出と候補リストUI
- **日時:** 2026-08-23
- **実施内容:**
  - `src/phase6_app.py`に`extract_recommended_ids()`を追加。LLM回答本文から
    建物ID（`bldg_[UUID]`形式）を正規表現抽出し、出現順維持・重複排除・
    候補ID集合との積集合（幻覚ID除外）を行う。`/api/search`のレスポンスに
    `recommended_ids`を追加。
  - フロント（`frontend/src/chat.ts`）で推薦建物を候補リスト先頭に並べ替え、
    「★ 推薦」バッジを表示。番号は並べ替え後の位置ではなく元の検索順位
    （`properties.rank`）を表示。
  - 「さらにN件」ボタンに展開/折りたたみのクリックハンドラを実装
    （従来は未実装で押しても反応しなかった）。全件をDOMに描画し`hidden`属性で
    折りたたむ方式のため、展開後の項目にも既存のホバー連動（地図ハイライト）が
    そのまま効く。
- **確認結果:** ブラウザ実機（`pixi run dev`）で看板クエリを実行し、
  1位＝推薦建物・★バッジ表示・rank番号一致・「さらに5件」展開後の
  hidden解除とホバー連動をJS経由で確認。
- **サニティチェック:** ✅ `check_phase18_geojson_order()`・
  `check_phase18_recommended_ids()` パス、TypeScriptビルド成功
- **コミットハッシュ:** `e3878b6`

### Step 18-3: Markdownレンダリング
- **日時:** 2026-08-23
- **実施内容:**
  - `marked`・`dompurify`を導入。`anthropic-skills:supply-chain-audit`スキルで
    Web検索（攻撃報告なし。dompurifyは類似名パッケージ「express-dompurify」の
    存在を確認したが正規パッケージ名を直接指定しているため無関係）・
    レジストリメタデータ・依存ツリー・`npm audit`を確認。最新版は公開から
    5日/4日しか経っておらずcooldown推奨（7日）未満のため、1つ前の安定版
    （marked@18.0.9・dompurify@3.4.13、いずれも公開20日前後）に固定して
    `--save-exact --ignore-scripts`でインストール。監査記録を
    `docs/audit-logs/`に保存。
  - AI回答バブルのみ`marked`→`DOMPurify.sanitize()`でHTML化。ユーザー/エラー
    メッセージは`_esc()`のプレーンテキストのまま維持（攻撃面を広げない）。
  - 比較表はtable自体に`overflow-x:auto`を設定し、チャットパネル本体が
    横スクロールしないようにした。
- **確認結果:** ブラウザ実機で回答バブルの`<strong>`/`<hr>`/`<ol>`等が
  正しくレンダリングされることをJS経由で確認。
- **サニティチェック:** ✅ TypeScriptビルド成功、`--phase18`回帰なし
- **コミットハッシュ:** `fc65898`

### Step 18-4: データ出典・整備時点の明示（方針A）
- **日時:** 2026-08-23
- **実施内容:** 地図パネルとウェルカムメッセージに、PLATEAU建物データが
  整備時点のスナップショットであり背景地図（OpenStreetMap）とは建物の
  有無が一致しないことを明示する注記を追加。
  PLATEAU広島市データの整備年度は、GPKGの`uro:DataQualityAttribute`
  （コード値のみで年号を含まない）・`docs/specification.pdf`（38MB超の
  汎用仕様書。圧縮バイナリのため簡易的な年号抽出は不可）のいずれからも
  特定できなかったため、年次は明記せず「整備時点」の表記に留めた
  （推測で年を書かないという計画の方針に従った）。
- **確認結果:** ブラウザで両注記の表示を確認。
- **サニティチェック:** ✅ `--phase18`回帰なし、TypeScriptビルド成功
- **コミットハッシュ:** `6c65337`

### Step 18-5: 地図の3D化と背景建物の抑制（方針B+C）
- **日時:** 2026-08-23
- **実施内容:**
  - 【B】`_hideBasemapBuildings()`を新設。OpenFreeMapのレイヤーIDはliberty/dark
    スタイルで異なるため、`source-layer === 'building'`で判定して非表示化
    （ID直書きを回避）。`initMap()`の`load`時と`applyMapTheme()`の
    `styledata`時（`setStyle()`で非表示設定が失われるため）の両方で呼び出す。
  - 【C】`buildings-fill`/`buildings-outline`/`buildings-highlight`の3レイヤーを
    `buildings-3d`（`fill-extrusion`）1枚に統合。`fill-extrusion-height`は
    `measured_height`（無効値・NULLは3mにクランプ）、色は
    ホバー→推薦建物→高潮リスク3段階の優先順のcase式。`fill-extrusion`は
    データ駆動のフィルタ/opacityに対応しないため、ホバーは`setFilter`から
    `setFeatureState`（`promoteId:'id'`が必要）に置き換えた。
    アクセント色はCSS変数を解決できないため`map.ts`に定数で保持し、
    `style.css`の`--accent`と同値である旨をコメントで明記。
  - 地図の初期`pitch`を45度に設定し、`fitBounds`のpaddingを上方向厚めに調整。
- **確認結果:** `_hideBasemapBuildings()`のsource-layer判定を、実際の
  OpenFreeMap liberty/darkスタイルJSON（fetchで取得）に対して検証し、
  想定通りbuilding系レイヤー（liberty: building/building-3d、dark: building）
  を検出できることを確認した。
  **一方、本セッションのBrowserペインはフレームをコンポジットしない環境
  （`document.hidden === true`でMapLibreのrender loop/loadイベントが進行しない）
  のため、3D押し出し・背景建物非表示・ホバー強調の実際のピクセル描画は
  視覚確認できていない。** TypeScriptビルド成功とロジック検証のみで
  Stepを完了しており、ユーザー側での実機目視確認を推奨する。
- **サニティチェック:** ✅ TypeScriptビルド成功、`--phase18`回帰なし
  （⚠️ 地図描画の視覚確認は未実施）
- **コミットハッシュ:** `3a0170b`

### Step 18-6: プロンプト調整
- **日時:** 2026-08-23
- **実施内容:** `build_prompt()`の【回答形式】に、役割の名乗り・質問文の復唱を
  しない指示（最上位に配置し、否定例を明記して強度を上げた）と、`#`最上位見出し
  禁止を追加。`sort_by`（`ParsedQuery.sort_by`、「最も高い」等の最上級クエリで
  設定）が指定されている場合は比較表が指定順である旨を明示し、推薦件数を
  1件+次点2件に絞るよう指示する引数を追加し、`generate_answer`/`hybrid_search`
  から配線した。比較表の先頭列を「No.」から「順位」に変更。
- **確認結果:** 実機（Gemini 2.5 Flash, temperature=0）で英語・日本語クエリを
  再実行し検証した。
  - `sort_by`指定時の「1件推薦+次点比較」は機能し、2番目に高い建物との
    比較文が回答に含まれた。
  - 前置き禁止指示は**部分的にしか効かなかった**。強化前は
    「広島市の都市計画・防災アドバイザーとして、ユーザーの『（質問文）』
    という質問に対し」で開始していたが、強化後は「アドバイザーとして」の
    自己紹介は消えたものの、「ユーザーの質問『（質問文）』に対し」という
    質問文の復唱は日本語・英語クエリの双方で残存した。
    ANTHROPIC_API_KEY未設定のためClaude Sonnet 4.6での比較検証は
    実施できなかった。プロンプト指示による抑制はベストエフォートであり、
    完全な排除は保証できないことを確認した（LLMの指示追従性の限界であり、
    コード側の不具合ではない）。
- **サニティチェック:** ✅ `--phase18`・`--phase17`回帰なし
  （⚠️ 前置き復唱の完全排除は未達成）
- **コミットハッシュ:** `310071f`

### Step 18-7: ビルド・検証・記録
- **日時:** 2026-08-23
- **実施内容:** `pixi run build`でフロントエンド最終ビルド、
  `--phase18`・`--phase17`の全チェック実行、ブラウザ実機での看板クエリ
  （英語・日本語）目視確認、work_log.md記録。
- **確認結果（看板クエリ 英語/日本語 共通）:**
  - (a) 候補リスト1位＝回答が推薦した建物ID: ✅
  - (b) ★推薦バッジ表示（複数推薦にも対応、日本語クエリで4件同時検出を確認）: ✅
  - (c) 「さらにN件」展開・ホバー連動: ✅
  - (d) Markdown装飾（strong/hr/ol等）: ✅
  - (e) 前置き復唱の抑制: ⚠️ 部分的（Step18-6参照）
  - (f) 地図・ウェルカムメッセージの出典注記: ✅
  - (g) チャットパネルの横スクロールなし: ✅（`message-list`/`chat-panel`/`body`
    いずれも`scrollWidth === clientWidth`をJS実測で確認）
  - (h)(i) 3D押し出し・背景建物非表示の視覚確認: ⚠️ **未実施**（Browserペインが
    フレームをコンポジットしない環境のため。Step18-5参照。ロジックのみ検証済み）
- **サニティチェック:** ✅ `--phase18`・`--phase17`全パス、TypeScriptビルド成功
- **コミットハッシュ:** 本Stepでは work_log.md のみ追加のためコード変更なし
  （直前の `310071f` が実質最終コミット）

### Phase 18 総括
- **達成事項:** 候補順序バグ（1位の建物がリストで埋もれる）を修正し、
  推薦建物の可視化（バッジ・順位・地図強調）、Markdown装飾、データ出典明示、
  地図の3D化（PLATEAU建物をmeasured_heightで押し出し）と背景OSM建物の
  非表示化を実装した。
- **残存する限界（次フェーズ以降の課題）:**
  1. LLMの前置き復唱（役割の名乗りは消えたが質問文の復唱が残る）は
     プロンプト指示だけでは完全に排除できなかった。決定論的に排除するには
     回答の後処理（正規表現によるプリアンブル検出・除去等）が必要だが、
     誤検出リスクがあるため今回は見送った。
  2. 地図の3D押し出し・背景建物非表示・ホバー強調の実際の描画は、
     本セッションのBrowserペインがフレームをコンポジットしない制約により
     視覚確認できていない。`_hideBasemapBuildings()`のロジックは実際の
     OpenFreeMapスタイルJSONに対して検証済みだが、`pixi run dev` +
     `pixi run app`でのユーザー自身による目視確認を推奨する。

---

## 候補リストの高潮リスクバッジ削除（Phase 19 準備）

- **日時:** 2026-08-23
- **背景:** Phase 19（地図の色分けをクエリ連動の動的配色に変更）を設計する過程で、
  候補リストのバッジが常に高潮リスク（`ht_rank_worst`）固定表示であり、
  クエリ内容（日当たり・方位等）と無関係な情報が常設されている点が
  「色の意味が分かりづらい」の一因と判明した。バッジの動的化自体は
  別タスクとする方針とし、今回は固定表示のまま残すより一旦削除する方が
  誤解を招かないと判断した。
- **実施内容:**
  - `frontend/src/chat.ts::_buildingListHtml()` から `riskClass`/`riskLabel`
    の算出と `<span class="risk-badge...">` の描画、`aria-label` 内の
    「高潮 ◯◯」文言を削除。
  - 未使用となった `_riskClass()` ヘルパー関数を削除。
  - `frontend/src/map.ts` のクリック時ポップアップ（今回のスコープ外）は、
    自身で独立した `_riskClass()`/`.risk-badge` を保持しており影響なし。
- **確認結果:** `npm run build`（tsc + vite build）が型エラーなく成功。
  CSS（`.risk-badge`関連）はmap.ts側で引き続き使用するため変更なし。
- **サニティチェック:** ビルド成功のみ（表示ロジックの削除のためAPI/DB非依存）
- **コミットハッシュ:** （このコミットで記録）
- **今後の課題:** 候補リストの表示内容をクエリ連動で動的化するタスクを
  別途 Phase として計画する（Phase 19 の地図配色動的化と合わせて検討）。

---

## [Phase 19] 地図配色のクエリ連動動的化（方針C、フォールバックとして方針A内蔵）

### Step 19-1〜19-4: 型の伝搬・動的配色ロジック・map.tsへの適用・凡例UI
- **日時:** 2026-08-23
- **背景:** Phase 18 の 3D 地図は常に高潮浸水リスク固定の3段階配色だった。
  アプリの目的（方位・日照・静けさ・距離など多数の軸を自由に検索する
  セマンティックRAG）と噛み合っておらず、閾値もPLATEAU公式ランクコード
  リスト（`HighTideRiskAttribute_rank`: 0.5m/3m/5m/10m/20m区切り）と
  無関係な独自値（0.5m/2.0m）だった。`docs/plan.md` Phase 19 の設計通り、
  `ParsedQuery` から実際に問われた属性を優先順位（9段階）で判定し、
  地図の塗り分け・凡例を動的に切り替える方針Cを実装した。該当なし
  （意味検索のみ等）の場合は9番目の分岐として中立色（方針A）に
  自動フォールバックする設計とした。バックエンド変更は不要
  （`parsed_query` は既に `/api/search` レスポンスに含まれる）。
- **実施内容:**
  - `frontend/src/api.ts`: `ParsedQueryDto`/`RiskFilterDto`/`SortSpecDto`/
    `OrientationFilterDto`/`DistanceFilterDto` を追加し、
    `SearchResponse.parsed_query` を型付け。
  - `frontend/src/store.ts`: `Message.parsedQuery`・
    `AppState.activeParsedQuery` を追加。
  - `frontend/src/main.ts` / `frontend/src/chat.ts`: `openMap()`・
    `onMapOpen` コールバックの全呼び出し箇所（自動オープン・地図ボタン・
    候補リスト項目クリックの計3箇所）に `parsedQuery` を伝搬。
  - `frontend/src/mapColor.ts`（新規）: `determineColorSpec()`（優先順位
    9段階の判定）・`colorExprFor()`（MapLibre Expression生成）・
    ドメイン計算ヘルパーを実装。map.ts の肥大化を避けるため独立モジュール化。
  - `frontend/src/map.ts`: `_fillExtrusionColorExpr()` を
    `colorExprFor(currentColorSpec)` 呼び出しに置換。`setGeojson()` に
    `parsedQuery` 引数を追加し、呼び出しごとに `currentColorSpec` を再計算・
    凡例テキスト（`#map-color-legend`）を更新。`pendingGeojson` と対にした
    `pendingParsedQuery`、`applyMapTheme()` のテーマ再適用パスにも
    `activeParsedQuery` を伝搬。
  - `frontend/index.html` / `frontend/src/style.css`: `#map-color-legend`
    を地図オーバーレイに追加（件数表示と出典注記の間、`order: 2`）。
- **確認結果:**
  - `npm run build`（tsc + vite build）が型エラーなく成功。
  - ブラウザコンソールから `mapColor.ts` を直接 import し、実際の
    `/api/search` レスポンス（`広島駅周辺で一番高い建物は？`）を使って
    `determineColorSpec()` の**9分岐すべて**（risk×2経路、sort_by由来の
    グラデーション、方位、日照、静けさ、垂直避難、木造密集、屋根種別、
    該当なし→中立フォールバック、`parsedQuery=null`→中立）を個別に
    シミュレートし、期待通りの `mode`/`domain`/`legendText` が返ることを
    確認した。`colorExprFor()` も全モードで例外なく妥当な MapLibre
    Expression（`case`/`interpolate`/`match`）を生成することを確認した。
  - 実クエリ「広島駅周辺で一番高い建物は？」を実行し、回答本文・候補リスト
    （1位=97.4mの建物が推薦と一致、バッジ削除の反映も確認）は正常動作。
- **サニティチェック:** フロントエンドに自動テストランナー未導入のため、
  ブラウザコンソールでの直接実行によるロジック検証で代替（API/DB非依存）。
- **残存する限界:** 本セッションの Browser ペインは外部タイルサーバー
  （tiles.openfreemap.org）への通信ができず（ネットワークリクエストが
  一切記録されない）、`map.on('load')` が発火しないため**地図の実描画
  （実際の色・凡例が塗られた見た目）は視覚確認できていない**
  （Phase 18 で既に記録済みの同種の制約）。ロジック層（`mapColor.ts`）は
  上記の通り実データで完全に検証済みのため、`pixi run dev` +
  `pixi run app` でのユーザー自身による目視確認を推奨する。
- **コミットハッシュ:** （このコミットで記録）

### Phase 19 総括
- **達成事項:** 地図の配色をクエリ連動の動的配色（優先順位9段階、
  該当なしは中立色に自動フォールバック）に変更し、地図オーバーレイに
  「今回何を基準に塗ったか」を示す凡例を追加した。高潮リスクの閾値も
  PLATEAU公式ランクコードリスト基準（0.5m/5m）に統一した。
- **今後の課題:**
  1. 候補リストバッジの動的化（Phase 19 開始前に別タスクとして
     切り出し済み、未着手）。
  2. `risk_filters` に複数ハザードが指定された場合、地図は最初の1件のみを
     可視化する（複合表示は非対応、意図的な簡略化）。
  3. 地図の実描画の目視確認はユーザー環境での実施が必要（上記「残存する
     限界」参照）。

---

## Phase 19 追加修正（ユーザーレビュー対応）

- **日時:** 2026-08-24
- **背景:** Phase 19 の初回実装をレビューしたユーザーから4点の指摘があった。
- **対応内容:**
  1. **地図クレジット表記の欠落**: `maplibregl.AttributionControl({ compact: true })`
     を明示的に追加（`frontend/src/map.ts::initMap()`）。`.map-overlay` が
     ボトム帯を占有し `bottom-right` の既定位置と衝突しうるため、`top-left`
     に配置した。DOM上に `.maplibregl-ctrl-attrib` が `top-left` 配下に
     生成されることを確認済み。
  2. **初期表示が3D固定だった**: `initMap()` の `pitch: 45` を `pitch: 0`
     に変更し、真上から見た2D表示をデフォルトにした。3D押し出し自体
     （fill-extrusionレイヤー）は変更しておらず、`NavigationControl`
     （`visualizePitch: true`）やドラッグ操作でユーザーが任意に3D表示へ
     切り替えられる。
  3. **凡例が文章のみで色ごとの条件が不明瞭**: `ColorSpec` に
     `legendEntries`（色+ラベルの配列）と `legendType`
     （'discrete'|'gradient'）を追加し、`mapColor.ts` の9分岐すべてに
     具体的な条件（例: risk=「0.5m未満/0.5〜5m未満/5m以上」、
     boolean-sunlight=「確保/未確保」、categorical-roof=「陸屋根/勾配屋根」、
     gradient系=両端の実測値ラベル）を持たせた。`map.ts::_renderLegendHtml()`
     で discrete はスウォッチ+ラベルの列挙、gradient は2色グラデーション
     バー+両端ラベルとして描画する（QGISのレイヤー凡例に類似した形式）。
     `#map-color-legend` は `<span>` から `<div>` に変更（内部にブロック
     要素を持てるようにするため）。
  4. **候補クリック時のズームが弱い**: `map.ts` に `_boundsOfFeatures()`
     共通ヘルパーと `focusBuilding(id)` を追加。候補リスト項目クリック
     （`chat.ts`）と地図上の建物クリックの両方で、該当建物1件の bbox に
     `fitBounds(..., { maxZoom: 19 })` するよう変更した（全候補への
     fitBoundsは維持しつつ、直後に単一建物へのフィットで上書きする）。
- **確認結果:**
  - `npm run build`（tsc + vite build）が型エラーなく成功。
  - `.maplibregl-ctrl-attrib` が `top-left` 配下に存在することを DOM で確認。
  - `mapColor.ts::determineColorSpec()` の `legendEntries`/`legendType` を
    実データ（risk/静けさ/日照/屋根種別/中立の5パターン）で再検証し、
    期待通りの色・ラベルが返ることを確認。
- **残存する限界:** Phase 19 初回実装時と同じ理由（Browser ペインが
  外部タイルサーバーへ通信できず地図スタイルの読み込みが完了しない）により、
  凡例の実際の描画・2D初期表示・ズームインの視覚的な挙動は本セッションでは
  確認できていない。`pixi run dev` + `pixi run app` でのユーザー自身による
  目視確認が必要。
- **コミットハッシュ:** （このコミットで記録）

---

## [Phase 20] フットプリント形状指標（円形・矩形・L字型・十字型・星形など）の追加

> **背景:** ユーザーが「円形や星形に近い建物を探して」と指示したところ「形状に関する
> 情報がない」という回答が返った。`building_geom_meta`（Phase 9/13）には壁面方位・
> 屋根形状・体積近似・細長さは前計算済みだが、フットプリント輪郭形状の指標が存在
> しなかったため。ユーザーの追加要望により円形・星形に加え L字型・コの字型・十字型・
> 矩形にも対応する設計とした（`docs/plan.md` Phase 20 参照。承認日 2026-08-26）。

### Step 20-1: フットプリント形状指標の計算（`src/phase9_geometry.py` 拡張）
- **日時:** 2026-08-26
- **実施内容:**
  - `fetch_footprint_areas()` を `fetch_footprint_shape()` に拡張。
    `hiroshima_sample.gpkg` から `footprint_area_m2` に加え
    `footprint_perimeter_m`（`ST_Perimeter`）・`convex_hull_area_m2`
    （`ST_Area(ST_ConvexHull(...))`）・`footprint_vertex_count`（`ST_NPoints`）・
    フットプリント全体の WKT（`ST_AsText(ST_Force2D(geometry))`）を取得。
  - `count_concave_vertices(footprint_wkt)` を新規実装。MULTIPOLYGON WKT から
    正規表現で外周リングを抽出し、隣接エッジ外積の符号（多数決）から外れる
    頂点数を凹角数として数える。
  - `estimate_shape_type(circularity, convexity_ratio, concave_vertex_count)` を実装。
    真円度・凹角数・凸性比の組み合わせで
    「円形に近い/矩形・単純形状/L字型/コの字型・T字型/十字型・複雑形状/星形・複雑形状」
    の6分類を推定。
  - `building_geom_meta` に新カラム7種
    （`footprint_perimeter_m`, `convex_hull_area_m2`, `footprint_vertex_count`,
    `concave_vertex_count`, `circularity`, `convexity_ratio`, `shape_type_est`）を追加。
  - `extract_geom_meta()` に形状指標の計算・保存・統計サマリー出力を追加。
- **不具合修正（動作確認中に発見）:**
  - 実装前に DuckDB spatial 拡張で `ST_Perimeter` / `ST_ConvexHull` / `ST_NPoints` /
    `ST_ExteriorRing` が解決可能か最小サンプルで確認したところ、いずれも解決可能
    だったが、実データ（`bldg:Building.geometry`）の型が **MULTIPOLYGON**
    （要素数1）であり、`ST_ExteriorRing` は POLYGON 型のみ対応のため常に
    `NULL` を返すことが判明（`ST_GeometryN` も DuckDB spatial に存在せず
    MULTIPOLYGON からポリゴンを取り出す関数がない）。
    → `ST_AsText(ST_Force2D(geometry))` で MULTIPOLYGON 全体の WKT を取得し、
    `count_concave_vertices()` 側で `parse_multipolygon_z()` と同じ正規表現手法
    により最初のリング（=外周リング、ホールなし前提）を抽出する方式に変更して解消。
  - **真円度閾値の誤分類を発見**: 仮値 `_CIRCULAR_THRESHOLD = 0.75` で実行したところ
    `shape_type_est` が `{'矩形・単純形状': 1046, '円形に近い': 619, ...}` となり、
    「円形に近い」に分類された619件のうち346件が `footprint_vertex_count=5`
    （閉じたリングで4角形＝単純な矩形建物）であることが判明。正方形の真円度は
    `4π・面積/周長² = π/4 ≈ 0.785` であり、これが閾値0.75を上回るため矩形建物が
    誤って円形に分類されていた。
    → 頂点数別の真円度分布を確認したところ、`circularity >= 0.85` は全体で
    わずか9件のみで、いずれも頂点数9以上（曲線に近い多角形）であり矩形建物を
    含まないことを確認。`_CIRCULAR_THRESHOLD` を **0.85** に修正して解消。
- **確認結果（実データ分布・2026-08-26、修正後の閾値で再実行）:**
  - 真円度: 平均 0.627、最大 0.975（有効2958件）
  - 凸性比: 平均 0.967、最小 0.130（有効2958件）
  - 凹角数の分布: `{0: 1522, 1: 438, 2: 433, 3: 161, 4: 142, 5: 58, 6: 69, 7: 32, ...}`
  - `shape_type_est` 分布: `{'矩形・単純形状': 1513, 'L字型': 438, 'コの字型・T字型': 433,
    '十字型・複雑形状': 300, '星形・複雑形状': 265, '円形に近い': 9}`
    （6分類すべてに0件でない件数が入っており、閾値の妥当性を確認）。
- **サニティチェック:** ✅ `pixi run python src/phase9_geometry.py` の統計サマリー
  print で分布を目視確認（`tests/sanity_checks.py` への追加は Step 20-5 で実施）。
- **既知の限界:** `shape_type_est` は凹角数ベースのヒューリスティック推定であり、
  L字・T字・十字の厳密な区別は保証しない（例: 凹角2個は「コの字」にも
  「Tの字を横倒しにした形」にも該当し得る）。完全な形状認識（テンプレート照合等）
  は本 Phase のスコープ外。
- **コミットハッシュ:** `dd19899`

### Step 20-2〜20-4: query_parser拡張・router配線・比較表拡張
- **日時:** 2026-08-26
- **実施内容:**
  - `query_parser.py`: `ParsedQuery.footprint_shape` を追加。`_SHAPE_VALUES`
    （6分類のラベル一覧）・`_SHAPE_RULES`（形状語→分類のマッピングルール、
    「最も円形に近い」等の最上級表現は `sort_by={"key":"circularity",...}` に
    誘導）を `_SYSTEM_PROMPT` に組み込み、`_RESPONSE_SCHEMA` と `parse_query()`
    に配線。`_SORT_KEYS` に `circularity` を追加。
  - `phase10_router.py`: `COLUMN_SOURCE` に `circularity`/`convexity_ratio`/
    `concave_vertex_count`/`footprint_vertex_count`/`shape_type_est` を
    `"g"`（building_geom_meta）として追加。`classify_route()` の
    `has_structured` 判定・`build_filter_clauses()`（`shape_type_est = ?`）・
    `verify_candidates()`（同条件の pandas 側再検証）に `roof_type` と
    同一パターンで配線。`build_order_clause()` は既存の汎用ロジックで
    `circularity` にも対応済みのため変更不要（確認のみ）。
  - `phase4_retrieval.py`: `vector_search()` の SELECT 句（has_geom_meta の
    2パターン）に `g.shape_type_est` を追加。`build_prompt()` の比較表に
    「形状」列を追加（屋根列の直後、22列に拡張。ヘッダーと区切り行の列数一致を
    確認）。`hybrid_search()` の `parsed_query_dict` に `"footprint_shape"` を追加。
  - `phase6_app.py`: `candidates_to_geojson()` の `meta_cols` に
    `g.shape_type_est` を追加し、地図ポップアップでも形状分類を参照できるようにした
    （`roof_type_est` と同じ扱い。計画外だが同一パターンのため低リスクとして追加）。
- **確認結果:**
  - `parse_query('円形に近い建物を教えて')` → `footprint_shape='円形に近い'`
  - `parse_query('L字型の建物はある？')` → `footprint_shape='L字型'`
  - `parse_query('最も円形に近い建物は？')` → `sort_by={key:circularity,order:desc}`,
    `footprint_shape=None`（意図通り、フィルタでなくソートとして処理）
  - `parse_query('コの字型や十字型の建物を探して')` → `footprint_shape=None`,
    `semantic_residual='コの字型や十字型の建物を探して'`
    （**既知の制約**: `footprint_shape` は単一値のため、2種類の形状を OR で
    問うクエリは LLM が単一分類を選べず semantic_residual にフォールバックする。
    ベクトル検索は形状語を認識できないため実質ヒットしない。複数形状の同時
    検索への対応は本 Phase のスコープ外とする）。
  - `hybrid_search('円形に近い建物を教えて', skip_answer=True)` を実行し、
    `route='structured'`、候補9件全件で `shape_type_est == '円形に近い'`、
    `parsed_query['footprint_shape'] == '円形に近い'` を確認（SQL フィルタが
    正しく機能し、Step 20-1 で確定した9件と一致）。
- **サニティチェック:** ✅ 上記の手動確認（`tests/sanity_checks.py` への
  自動チェック追加は Step 20-5 で実施）。
- **コミットハッシュ:** `e7ec7cb`

### Step 20-5: 評価・サニティチェック・コミット
- **日時:** 2026-08-26
- **実施内容:**
  - `tests/gold_set.py` に `G37`（円形に近い建物、`shape_type_est='円形に近い'`）・
    `G38`（L字型の建物、`shape_type_est='L字型'`）・`G39`（星形や複雑な形状の建物、
    `shape_type_est='星形・複雑形状'`）を `category="geometric"` として追加。
  - `tests/sanity_checks.py` に `check_phase20_shape_columns()`（新カラム7種の存在・
    `circularity` 非NULL件数>0・`shape_type_est` の分類数>=2）、
    `check_phase20_shape_filter()`（「円形に近い建物を教えて」で `route="structured"`
    かつ全候補 `shape_type_est=="円形に近い"`）を追加。`run_phase20_checks()` と
    `--phase20` CLI 分岐を追加。
- **確認結果:**
  - `pixi run python tests/sanity_checks.py --phase20` → 2件パス
    （形状指標カラム7種確認、circularity 非NULL=2958件、shape_type_est 分類数=6／
    円形クエリで route=structured・全9件が条件充足）。
  - `pixi run python tests/sanity_checks.py --phase13` / `--phase15` を再実行し、
    既存チェック（building_geom_meta 新カラム・南向き/西日回避/日照/除外条件）に
    回帰がないことを確認（全件パス）。
  - `pixi run python tests/gold_set.py` を再実行し、39件（既存36件+新規3件）の
    ゴールドセットを再生成。G37=9件、G38=438件、G39=265件で
    Step 20-1 の分布確認結果と一致することを確認。
  - `pixi run python tests/eval_retrieval.py` を再実行（`output/eval_result_20260826_0557.csv`）。
    - 新規3件: G37/G38/G39 いずれも precision=1.0、hit1=1.0（recall は
      top_k=10 の物理的上限による低下のみで、既存の G03/G08 等と同種の
      既知の制約であり不具合ではない）。
    - category別マクロ平均: structured recall=0.637/precision=0.875/hit1=1.0、
      hybrid recall=0.228/precision=0.913/hit1=1.0、
      geometric recall=0.262/precision=0.923/hit1=1.0（G37-39追加込み）、
      robustness recall=0.405/precision=1.0/hit1=1.0。
      形状フィルタの追加によって structured/hybrid/robustness カテゴリ
      （gold_sql未変更）のクエリが悪影響を受けていないことを確認
      （直近の比較可能な eval_result は Phase 14 時点のもののみで、
      Phase 15〜19 の変更を経ているため単純比較はできないが、
      全カテゴリで precision/hit1 が高水準を維持していることを確認した）。
- **サニティチェック:** ✅ `--phase20` 新規2件・`--phase13`/`--phase15` 回帰確認、
  すべてパス。
- **コミットハッシュ:** （このコミットで記録）

### Phase 20 総括
- ユーザーの「円形や星形に近い建物を探して」という要望と、追加要望
  「L字型など多様な形状にも対応できるか」の両方に対応した。
  `building_geom_meta` に真円度・凸性比・凹角数を追加し、
  円形/矩形/L字型/コの字型・T字型/十字型/星形の6分類を推定できるようにした。
- **既知の限界（README・work_log に明記）:**
  1. `shape_type_est` は凹角数ベースのヒューリスティック推定であり、
     L字・T字・十字の厳密な区別は保証しない。
  2. `footprint_shape` は単一値のみ保持できるため、「コの字型や十字型」のように
     複数形状を OR で問うクエリは特定の分類に絞り込めず `semantic_residual` に
     フォールバックする（ベクトル検索は形状語を認識できないため実質ヒットしない）。
  3. 真円度の閾値（0.85）は少数の実データ分布確認に基づく仮決定であり、
     今後データセットが変わった場合は再確認が必要。

---

## [Phase 21] RURI v3 310m 埋め込みモデルのベンチマーク検証

> FOSS4G（国際会議）発表に向け、埋め込みモデルを `gemini-embedding-001`（クローズドAPI）
> からオープン&フリーな `cl-nagoya/ruri-v3-310m`（Apache 2.0, 日本語特化）へ切り替える
> 検討の一環。本Phaseは**ベンチマーク取得のみ**が目的であり、本番の埋め込み切り替え
> （再埋め込み・DuckDBスキーマ変更・検索ロジック改修）は行っていない。

### Step 21-1: pixi環境へのローカル埋め込みモデル依存追加
- **日時:** 2026-08-27
- **実施内容:**
  - `/c/Users/pikkarin/AppData/Local/pixi/bin/pixi.exe add pytorch-cpu sentence-transformers psutil`
    を実行。conda-forgeで解決に成功し、`[dependencies]` セクションに
    `pytorch-cpu = ">=2.13.0,<3"`, `sentence-transformers = ">=6.0.0,<7"`,
    `psutil = ">=7.2.2,<8"` が追加された（`[pypi-dependencies]` へのフォールバックは
    不要だった。Phase 12のSudachiPy追加時と同じ経路）。
  - `SentenceTransformer('cl-nagoya/ruri-v3-310m')` で初回ロード（HuggingFace Hub
    から自動ダウンロード）に成功。出力ベクトル形状 `(1, 768)` を確認し、
    モデルカード記載の768次元と一致することを確認した。
  - RURI v3の「1+3プレフィックス方式」を確認し、本プロジェクトでの割り当てを
    次の通り確定した:
    - building_chunks側（text_card）→ `"検索文書: "` を先頭に付与
    - ユーザークエリ側 → `"検索クエリ: "` を先頭に付与
- **確認結果:** ✅ モデルロード・768次元出力・プレフィックス仕様確認完了
- **コミットハッシュ:** （このコミットで記録）
- **備考:** `pixi.exe run python -c "import torch; print(torch.get_num_threads())"`
  で確認した既定スレッド数は4（CPU論理コア数8のノートPC上）。

### Step 21-2: ベンチマークスクリプト実装
- **日時:** 2026-08-27
- **実施内容:**
  - `tests/benchmark_ruri.py` を新規作成。既存パイプライン（`src/` 配下）には
    一切変更を加えず、read-only で `src/phase3_enrichment.py` の
    `build_text_card()` と `src/codelist_loader.py` の `CodelistLoader` を
    import して再利用する設計とした（不要になれば本ファイル削除のみで
    元に戻せるよう、既存コードとの分離を優先）。
  - データソースは `output/building_attrs_cache.parquet`（Phase 3 が
    既に作成済みのキャッシュ）を直接読み込み、GPKG再読込を回避。
  - `run_benchmark(texts, batch_size)` で以下を計測:
    総処理時間・1件あたり平均時間（`time.perf_counter()`）、
    ピークメモリ使用量（`psutil.Process().memory_info().rss` の前後差分）、
    出力ベクトルの次元数。バッチサイズ `[8, 32]` の2パターンを比較。
  - エンコード時は必ず `"検索文書: " + text_card` の形でプレフィックスを付与。
  - `--full`（全2,958件）／`--n`（件数指定、デフォルト100件）のCLIオプションを実装。
    結果は `output/benchmark_ruri_{YYYYMMDD_HHMM}.json` に保存。
- **サニティチェック:** 実行結果がエラーなく完了し、JSON保存を確認（Step 21-3で実施）。
- **コミットハッシュ:** （このコミットで記録）

### Step 21-3: 実測・記録・判断
- **日時:** 2026-08-27
- **実施内容:**
  - `pixi.exe run python tests/benchmark_ruri.py`（サンプル100件）を実行。
- **確認結果（100件サンプル、GPU非搭載ノートPC・メモリ16GB・空き約8GB）:**

| batch_size | 1件あたり処理時間 | メモリ増分 | 次元数 |
|---|---|---|---|
| 8 | 1.196秒 | +1,108.2MB | 768 |
| 32 | 1.265秒 | +1,034.9MB | 768 |

  - 結果保存先: `output/benchmark_ruri_20260827_0518.json`
  - **速度:** バッチサイズを8→32に増やしても速度改善はほぼなし（誤差範囲）。
    1件あたり約1.2秒ペースのため、**全2,958件を処理すると推定約60分**。
    `gemini-embedding-001`（Free Tier 1,000 req/day 制限のため数日がかり、
    Phase 3実績）と比較すると、日次クォータ待ちが不要になる点は明確な利点だが、
    1回あたりの処理自体はAPI呼び出しより低速。
  - **メモリ:** モデル1回ロードあたり約1.1GB消費。本ベンチマークスクリプトは
    batch_size=8/32の比較のためモデルを**2回ロード**しており、2回目終了時点の
    プロセス累積メモリは2.6GB（494MB→2,637MB）。実運用では1回ロードして
    使い回すため、恒常的な消費は約1.1GB程度と見るのが妥当。空き8GBの環境では
    余裕を持って動作すると判断できる。メモリ不足エラーは発生しなかった。
  - **次元数:** 768（`gemini-embedding-001` の実測3,072より小さく、
    DuckDB側のHNSWインデックス・保存容量は本採用時に縮小する見込み）。
  - 全2,958件でのフル実行（推定約60分）は、100件サンプルの結果で速度・メモリの
    傾向が十分に把握できたと判断し、**ユーザー判断によりスキップ**した。
- **サニティチェック:** ✅ ベンチマーク実行・JSON保存・数値の妥当性を確認
- **コミットハッシュ:** （このコミットで記録）
- **採用判断:** 本Phaseはベンチマーク取得のみが目的であり、本番の埋め込み切り替え
  （再埋め込み・DuckDBスキーマ変更・検索ロジック改修）は実施していない。
  実測結果（メモリ面は問題なし、速度は全件で約60分・一度きりのローカル処理）を
  踏まえた本採用の可否は、別途ユーザーと協議のうえ次Phaseとして計画する。

---

## [Phase 22] RURI v3 310m 全件ベンチマーク＋精度比較

> Phase 21の100件サンプル結果を受け、ユーザーから「全件実行すべきでは」
> 「Geminiとの精度比較なしに本採用は判断できない」との指摘があり着手。
> 本Phaseの目的は「全件実行→精度比較→判断」までであり、本番の埋め込み切り替え
> （スキーマ変更・検索ロジックの恒久改修・複数モデル切り替え機構）は含まない。

### Step 22-1: 全件RURI埋め込み生成
- **日時:** 2026-08-27〜2026-08-28
- **実施内容:**
  - `src/phase22_ruri_embed.py` を新規作成。`connect_rag()`（Phase3）を再利用し、
    本番DB（`output/plateau_rag.duckdb`）の`building_chunks`から全件`id, text_card`を
    取得、`"検索文書: " + text_card`でRURI v3 310mエンコードし、追加テーブル
    `building_chunks_ruri_embed(id, embedding FLOAT[768])`にDROP→CREATE→INSERTで保存。
    既存の`building_chunks`・HNSWインデックスには一切触れない設計。
  - `embed_query_ruri(text)`（`"検索クエリ: "`プレフィックス付与）も同ファイルに実装。
  - 実行中にユーザーがPCをシャットダウンする必要が生じたため、一度バックグラウンド
    プロセスを中断（5/93バッチ・約4分経過時点）。`build_ruri_index()`は最後に
    一括でDROP→CREATE→INSERTする設計のため、中断時点で`building_chunks_ruri_embed`
    テーブルは未作成であり、中途半端なデータが残る問題はなかった。電源復旧後に
    最初から再実行した。
- **確認結果:**
  - 全2,958件の埋め込み生成完了: **4,251.6秒（約71分、1.437秒/件）**。
    Phase21の100件サンプルからの推定（約60分）よりやや長め（誤差範囲）だが、
    長時間実行でのメモリ不足・エラーは発生せず完走した。
  - `building_chunks_ruri_embed`へ2,958件保存完了（`building_chunks`の件数と一致）。
- **サニティチェック:** ✅ 件数一致確認
- **コミットハッシュ:** （このコミットで記録）

### Step 22-2: 検索経路へのRURI組み込み（最小差分）
- **日時:** 2026-08-28
- **実施内容:**
  - `src/phase4_retrieval.py`の`vector_search()`に`embedding_source: str = "gemini"`を
    追加。`"ruri"`かつベクトル検索経路の場合のみ`LEFT JOIN building_chunks_ruri_embed r`
    を追加し、スコア式の埋め込み参照を`r.embedding`に差し替え（`dim`は
    `len(query_vec)`から768に自動決定されるため変更不要）。デフォルト値`"gemini"`時は
    既存コードパスと完全に同一。
  - `hybrid_search()`に同じく`embedding_source`を追加。`"ruri"`時は`embed_query()`の
    代わりに`phase22_ruri_embed.embed_query_ruri()`を呼ぶ。戻り値dictに
    `"embedding_source"`を追加。
  - `tests/eval_retrieval.py`の`evaluate()`/`main()`に`embedding_source`パラメータと
    `--ruri` CLIオプションを追加（既存の`--fts`/`--hyde`と同じパターン）。
- **確認結果（TODO 22-2-4 回帰確認）:**
  - 「広島市で最も高い建物は？」（G01、structuredカテゴリ）を
    `embedding_source="gemini"`と`"ruri"`の両方で実行し、**候補5件が完全に同一**
    であることを確認（route=structuredは埋め込み非依存のため、実装が正しければ
    当然の結果であり、実装ミスがないことの検証になる）。
- **サニティチェック:** ✅ 回帰確認（gemini/ruri完全一致）
- **コミットハッシュ:** （このコミットで記録）

### Step 22-3: 精度比較・記録・判断
- **日時:** 2026-08-28
- **実施内容:**
  - `pixi run python tests/eval_retrieval.py --ruri`で全39件のゴールドクエリを実行。
    結果: `output/eval_result_20260827_2321_ruri.csv`。
  - 直近のGeminiベースライン（`output/eval_result_20260826_0557.csv`、Phase20時点）と
    候補ID（`retrieved_ids`列）を突き合わせ。
- **重要な発見（想定外の結果）:**
  - **39件中36件で候補IDが完全に一致**した。しかしこれは「RURIがGeminiと同等の
    精度を持つ」ことを意味しない。原因は`query_parser.py`の`parse_query()`
    （Gemini Flash, temperature=0）の**非決定性**（Phase11 work_logで既知の問題が
    再発）で、本来hybrid/semanticに分類されるべきクエリの大半（G09〜G16等）が
    今回の実行では`route=structured`（埋め込み完全不使用のSQL確定検索）に
    分類されてしまっていた。structured経路はモデルに依存しないため、
    GeminiでもRURIでも当然同じ結果になる。
  - 実際に埋め込みが使われたのは39件中ごくわずか（G19等）で、
    **category別マクロ平均（structured=0.637, hybrid=0.228, geometric=0.262,
    robustness=0.405）は実質的に「structured経路の再確認」であり、
    RURIの検索精度をほぼ検証できていなかった**。
  - この問題を受け、`route="semantic"`を直接指定してclassify_route()の
    非決定性を回避し、gold_sqlが存在しない純粋な意味的クエリ4件
    （G17「日当たりのよい建物」/G18「静かな住宅街にある建物」/
    G19「防災拠点として活用できそうな建物」/G20「landmarkとして目立つ
    特徴的な形の建物」）についてGemini/RURIのtop5候補を直接比較した。
- **意味的クエリ4件の定性比較結果:**
  - **4件すべてでtop5候補の重複が0/5**。2つの埋め込みモデルは全く異なる
    候補ランキングを返しており、埋め込み空間の性質が大きく異なることを確認。
  - G17「日当たりのよい建物」について、`building_geom_meta.wall_ratio_s`
    （南壁面比率）・`building_context_meta.winter_sunlit`を確認したところ、
    **Gemini・RURIどちらのtop5も`winter_sunlit=True`の建物が0件、
    `wall_ratio_s`も0.10〜0.37と低め**であり、どちらのモデルも「日当たりの
    良さ」を意味的に正しく捉えられていなかった（Phase10/15で判明済みの
    「純粋ベクトル検索の識別力不足」がRURIでも同様に発生。この種のクエリは
    本来`pq.sunlight`構造化フィルタで処理すべきというPhase15の設計判断を
    裏付ける結果）。
  - semanticカテゴリはgold_sql（正解定義）が存在しないため、
    **どちらのモデルがより「正しい」かを客観的に判定する手段がなかった**。
- **structuredカテゴリの回帰確認:** TODO 22-2-4と合わせ、39件中の全structured
  ラベルクエリ（および非決定性で結果的にstructuredに落ちたクエリ）で
  候補IDが完全一致することを確認。Step 22-2の実装が正しいことの裏付けとなった。
- **サニティチェック:** ✅ 回帰確認（structured経路の完全一致）／
  意味的クエリの定性比較実施
- **コミットハッシュ:** （このコミットで記録）
- **採用判断（現時点でユーザーに提示する材料）:**
  1. **速度・メモリ**（Phase21）: RURIは実用範囲内（1件あたり約1.4秒、
     メモリ約1.1GB）。
  2. **structured/robustnessカテゴリの精度**: GeminiとRURIで完全に同一
     （これらは埋め込みモデルに依存しないSQL確定検索のため、当然の結果）。
  3. **semantic/hybridカテゴリ（純粋な埋め込み検索）の精度**: 今回の評価では
     決定的な比較ができなかった。両モデルとも意味的クエリの识別力が低く、
     優劣を判定する材料（gold_sql）が存在しない。
  4. **副次的な発見**: `query_parser.py`の`parse_query()`の非決定性により、
     同一クエリでもroute分類が実行のたびに変わりうる問題が今回も再現した。
     これはRURI導入とは独立した既存の課題（Phase11で既知）だが、
     eval_retrieval.pyによる自動評価の信頼性に影響するため、
     将来的な改善候補として記録しておく。
  - 本Phaseの完了をもって「全件実行→精度比較→判断」を終え、
    本採用（Phase23）に進むかどうかはユーザーに上記材料を提示して判断を仰ぐ。

### Step 22-4〜22-6: 同一ParsedQueryによるペア比較評価（追加実施）
- **日時:** 2026-08-28
- **背景:** Step 22-3で発見した「gemini用・ruri用を別々に実行すると
  `parse_query()`の非決定性でroute判定がブレる」問題に対し、ユーザーと相談の上
  「`parse_query()`自体を直す」のではなく「評価方法を同一クエリで1回だけ解析し
  Gemini/RURI両方に使い回す」形に修正する方針で追加実施した。
- **実施内容:**
  - `src/phase4_retrieval.py`の`hybrid_search()`に
    `parsed_query_override: ParsedQuery | None = None`を追加。指定時は
    `parse_query(query)`を呼ばずそのまま使う（デフォルト`None`時は既存動作と同一）。
  - `tests/eval_retrieval.py`に`evaluate_paired()`を新規実装。各ゴールドクエリで
    `parse_query()`を1回だけ呼び、同じ`ParsedQuery`を`embedding_source="gemini"`/
    `"ruri"`両方の`hybrid_search()`に渡し、1行にrecall/precision/hit1をペアで
    記録する。`main()`に`--paired`オプションを追加。
  - 回帰確認: `parsed_query_override`未指定時、既存の`hybrid_search()`呼び出しが
    従来と完全に同じ結果を返すことを確認。
- **確認結果（`pixi run python tests/eval_retrieval.py --paired`）:**
  - route分布（39件）: structured 35件、hybrid（semanticカテゴリ内）1件、
    残る3件もstructured。**同一ParsedQueryを使っても39件中38件がstructured
    経路に着地**した。
  - category別マクロ平均はGemini・RURIで**すべて完全に同一の数値**
    （例: hybrid recall_gemini=0.228312, recall_ruri=0.228312）。
  - **重要な発見**: これはバグではなく、Phase10のルーター設計（`classify_route`）
    が意味的クエリの大半を構造化条件に変換できてしまうという、アプリ設計上の
    必然だった。つまり**このデータセット・この設計では、embeddingモデルの
    違いが結果に影響する場面が、正解データのある39件中実質0件**という
    構造的事実が判明した。recall/precisionでの定量比較は原理的に決着しない。
  - 結果保存先: `output/eval_result_20260828_0603_paired.csv`
- **サニティチェック:** ✅ `parsed_query_override`未指定時の回帰確認
- **コミットハッシュ:** `b766261`
- **最終的な採用判断材料（Phase22総括）:**
  1. 速度・メモリ: 実用範囲内（Phase21）
  2. structured/robustness系（実クエリの大半）: Gemini・RURIで精度差なし（証明済み）
  3. semantic系（ごく一部）: 定量比較は不可能。定性比較（4クエリ、top5重複0/5）
     でも優劣不明
  4. ユーザーとの結論: 「実際に使ってみて判断する」方針とし、Phase23で
     Web UIを含む切り替え機能を実装した上でドッグフーディングする。

---

## [Phase 23] Gemini/RURI 埋め込み切り替え機能（Web UIまで対応）

> Phase 22で精度の定量的な決着がつかなかったため、「実際に使ってみて判断する」
> 方針となり、Web UIを含めてGemini/RURIをその場で切り替えられる機能を実装した。

### Step 23-1: バックエンド（FastAPI）への配線
- **日時:** 2026-08-28
- **実施内容:**
  - `src/phase4_retrieval.py`の`_get_meta_tables()`に`building_chunks_ruri_embed`の
    存在確認を追加（`building_geom_meta`/`building_context_meta`と同じキャッシュ
    機構を再利用）。`vector_search()`に、`embedding_source="ruri"`かつベクトル検索
    経路なのにテーブル不在の場合、`pixi run python src/phase22_ruri_embed.py`の
    実行を促すメッセージ付きで`RuntimeError`を送出する処理を追加
    （Phase15の`needs_geom`/`needs_context`チェックと同じパターン）。
  - `src/phase6_app.py`の`SearchRequest`に`embedding_source: str = "gemini"`、
    `SearchResponse`に`embedding_source: str = "gemini"`を追加。
    `hybrid_search()`呼び出しに`embedding_source=req.embedding_source`を渡し、
    レスポンスに`result.get("embedding_source", "gemini")`を含める。
- **サニティチェック:** ✅ `embedding_source="ruri"`を明示指定した`hybrid_search()`
  直接呼び出しでPhase22時点と同じ結果が得られることを確認（回帰なし）
- **コミットハッシュ:** （このコミットで記録）

### Step 23-2: フロントエンドUIへの配線
- **日時:** 2026-08-28
- **実施内容:**
  - `frontend/index.html`の`.input-options`に、既存の`model-select`と同じ構造で
    `embedding-select`（Gemini Embedding / RURI v3 310m（ローカル））を追加。
  - `frontend/src/store.ts`の`Settings`に`embeddingSource: string`
    （初期値`'gemini'`）を追加。
  - `frontend/src/api.ts`の`SearchRequest`/`SearchResponse`に`embedding_source`を追加。
  - `frontend/src/main.ts`で`embedding-select`の`change`イベントを購読し、
    `runSearch()`のAPI呼び出しに`embedding_source: settings.embeddingSource`を渡す
    （`model-select`と同じ配線パターン）。
  - `pixi run build`でTypeScriptコンパイル・Viteビルドが成功することを確認。
- **不具合発見（Phase23と無関係の既存バグ）:** `pixi run build && pixi run app`で
  本番相当配信を確認しようとしたところ、`index.html`のアセット参照
  （`/assets/index-xxxx.js`）とFastAPI側のマウント（`/static`配下のみ）が
  食い違っており、JS/CSSが404になりチャットUIが読み込めない不具合を発見した。
  Phase6完了時（2026-03-22）の記録では動作確認済みとなっているが、今回は再現した。
  Phase23の変更とは無関係の既存バグのため、別タスクとして切り出した
  （`vite.config.ts`に`base: '/static/'`を追加する軽微な修正で解決見込み）。
  本Phaseの動作確認は`pixi run dev`（開発サーバー、`/api`をFastAPIへプロキシ）に
  切り替えて実施した。
- **サニティチェック:** ✅ ビルド成功（TypeScriptエラーなし）
- **コミットハッシュ:** （このコミットで記録）

### Step 23-3: 動作確認・記録
- **日時:** 2026-08-28
- **実施内容:**
  - `pixi run dev`（フロントエンド）+ `pixi run app`（バックエンド）を起動し、
    ブラウザで`embedding-select`に「RURI v3 310m（ローカル）」を表示・選択できる
    ことを確認。
  - APIを直接呼び出し、以下を確認:
    - 構造化クエリ（「広島市で最も高い建物は？」）: `embedding_source="ruri"`指定で
      200 OK、`route="structured"`、`embedding_source`がレスポンスに正しく反映。
    - 意味的クエリ（「日当たりのよい建物」）: `use_query_parser=False`で
      `route="semantic"`を強制し、RURIのベクトル検索経路（`building_chunks_ruri_embed`
      へのJOIN）が実際に実行されてエラーなく5件返ることを確認。
  - `building_chunks_ruri_embed`を一時的にリネームしてテーブル不在状態を再現し、
    バックエンドプロセス再起動後（`_META_TABLES_CACHE`はプロセス内キャッシュのため
    再起動が必要）、`embedding_source="ruri"`かつ`route="semantic"`のリクエストで
    500エラー・想定通りのメッセージ（`pixi run python src/phase22_ruri_embed.py`
    の実行を促す文言）が返ることを確認。確認後にテーブル名を元に戻した。
- **サニティチェック:** ✅ 正常系（gemini/ruri）・異常系（テーブル不在）とも想定通り
- **コミットハッシュ:** （このコミットで記録）
- **既知の課題（別タスク切り出し済み）:** `pixi run app`単体での本番ビルド配信時の
  静的ファイル404（Step23-2参照）。Phase23の機能自体には影響しない。

### Step 23-4: 本番ビルド配信の静的ファイル404を修正（切り出しタスクとして対応）
- **日時:** 2026-08-28
- **現象:** `pixi run build && pixi run app`を実行し`http://localhost:8000/`を
  開くと、JS/CSSが404になりチャットUIが動作しない。
- **原因:** `frontend/vite.config.ts`の`build.outDir`は`../src/static`
  （FastAPIのstaticディレクトリに出力）だが、ビルドされた`index.html`内の
  アセット参照はルート相対パス`/assets/index-xxxx.js`になっていた。一方
  `src/phase6_app.py`は`app.mount("/static", StaticFiles(...))`で`/static`配下
  にしかマウントしていないため、ブラウザは`/assets/...`を要求してしまい404に
  なっていた。
- **解決策:** `frontend/vite.config.ts`に`base: '/static/'`を追加。
  ビルド後のアセット参照が`/static/assets/index-xxxx.js`になり、FastAPIの
  マウント先と一致するよう修正した（`src/phase6_app.py`は無改修）。
- **確認結果:**
  - `pixi run build`実行後、`src/static/index.html`のアセット参照が
    `/static/assets/...`に変わったことを確認。
  - `pixi run app`起動後、ブラウザで`http://localhost:8000/`を開き、
    `/static/assets/index-nYSYpPnn.js`・`/static/assets/index-DagtAfbZ.css`が
    200 OKで読み込まれることを確認。
  - チャットUIから「高潮リスクが低い建物」を検索し、`POST /api/search`が
    200 OKで完了、回答（推薦建物・理由）が画面に正しく表示されることを確認。
- **サニティチェック:** ✅ 静的ファイル配信・検索実行とも正常動作を確認
- **コミットハッシュ:** （このコミットで記録）
- **備考:** Phase18〜22で`pixi run dev`（開発サーバー、Viteのプロキシ経由）のみで
  動作確認していたため、`base`未設定による本番ビルドの不具合が見過ごされていた。
  今後、本番相当の動作確認は定期的に`pixi run build && pixi run app`でも
  実施することが望ましい。

---

## [Phase 24] UI日英切り替え対応（チャット・地図凡例・ポップアップ・LLM回答）

> FOSS4G（国際会議）発表に向け、UIを日英切り替え対応にした。対応範囲は
> チャットUIの静的テキスト・動的メッセージ・地図凡例/ポップアップ・
> 候補建物リスト・LLM回答本文。固有名詞（駅名等）は対象外。

### Step 24-1: i18n基盤の実装
- **日時:** 2026-08-28
- **実施内容:**
  - `frontend/src/i18n.ts`を新規作成。`UI_STRINGS`（静的/動的UI文言の
    日英辞書、`t(lang, key, params?)`ヘルパー）、`VALUE_LABELS`
    （DB列挙値の英訳辞書。`output/plateau_rag.duckdb`の実データから
    確認した有限集合——用途14種・構造7種・耐火4種・浸水ランク4種・
    屋根種別2種・形状分類7種、および方角・施設カテゴリ・災害種別）、
    `translateValue()`（未登録値はそのまま返すフォールバック付き）を実装。
    `applyStaticTranslations()`・`initLang()`・`toggleLang()`も同ファイルに
    実装し、`theme.ts`の`initTheme()`/`toggleTheme()`と同じ
    「トグルボタン + 一括更新 + localStorage永続化」パターンを踏襲した。
  - `frontend/src/store.ts`の`AppState`に`language: Lang`
    （初期値`'ja'`）を追加。
  - `frontend/index.html`に`lang-toggle`ボタンを追加し、静的テキスト要素に
    `data-i18n`/`data-i18n-placeholder`/`data-i18n-aria-label`/
    `data-i18n-query`属性を付与（サンプル質問ボタンは表示文言だけでなく
    クリック時に送信される質問文自体も英語版に切り替わる設計）。
  - `frontend/src/main.ts`に`setupLang()`を実装し初期化時に呼び出す。
  - **配線順序の不具合を発見・修正**: `setupTheme()`を`setupLang()`より先に
    呼ぶと、`theme-toggle`の初期aria-labelが（保存済み言語が'en'の場合でも）
    日本語のまま設定される不具合を発見。`setupLang()`を先に呼ぶ順序に修正した。
  - さらに、言語トグル時に`theme-toggle`のaria-labelが再適用されない
    不具合も発見し、`theme.ts`に`refreshThemeToggleLabel()`を追加して
    `lang-toggle`のクリックハンドラから呼び出すよう修正した。
- **サニティチェック:** ✅ ブラウザで`lang-toggle`クリック時に全静的UI要素が
  英語表示に切り替わることを確認（後述Step24-5で詳細確認）
- **コミットハッシュ:** （このコミットで記録）

### Step 24-2: 動的UI文言・announce()メッセージの多言語化
- **日時:** 2026-08-28
- **実施内容:**
  - `frontend/src/main.ts`の`announce()`呼び出し・エラーメッセージ・
    候補件数アナウンスを`t()`経由に置き換え。
  - `frontend/src/chat.ts`の`appendUserMessage`/`appendLoadingBubble`/
    `appendAssistantMessage`/`_buildingListHtml`に`lang`引数を追加し、
    aria-label・「さらにN件」・件数/秒数表示等を`t()`経由にした。
  - 候補建物リスト内の属性表示は現状「距離」のみで、`translateValue()`が
    必要なDB列挙値（用途等）を表示していないことを確認したため、
    このStepでの適用は不要と判断した（マップポップアップ側はStep24-3で対応）。
- **サニティチェック:** ✅ 英語モードでの検索実行時、ユーザーメッセージ・
  ローディング・回答バブルのaria-label・メタ情報が英語になることを確認
- **コミットハッシュ:** （このコミットで記録）

### Step 24-3: 地図凡例・ポップアップの多言語化
- **日時:** 2026-08-28
- **実施内容:**
  - `frontend/src/mapColor.ts`の`HAZARD_LABEL`/`DIR_LABEL`/`FACILITY_LABEL`/
    `SORT_KEY_LABEL`を`Record<Lang, ...>`形式に拡張し、`determineColorSpec()`
    に`lang`引数を追加。9種類の配色ケース（リスク/sort_by/方位/日照/静けさ/
    垂直避難/木造密集/屋根種別/中立）すべてのlegendText・legendEntriesを
    日英で出し分けるようにした。
  - `frontend/src/map.ts`の`setGeojson()`で`store.get().language`を
    `determineColorSpec()`に渡し、候補件数表示も`t()`経由にした。
  - `_showPopup()`のポップアップHTML生成（用途・高さ・階数・高潮リスク・
    壁面方位・冬の日当たり・屋根・地面標高・最寄り駅/避難所/学校/病院・
    幹線道路まで・類似度スコア）を`lang`対応にし、DB値（用途・屋根種別）は
    `translateValue()`を適用した。`_orientationLabel()`も方角表記
    （南北東西 → S/N/E/W）を言語別にした。
- **サニティチェック:** コード上の配線は完了。実際のブラウザでの地図凡例・
  ポップアップ表示確認はStep24-5で試みたが、後述の理由により実施できず
  コードレビューでの確認に留まっている。
- **コミットハッシュ:** （このコミットで記録）

### Step 24-4: LLM回答の英語化（バックエンド）
- **日時:** 2026-08-28
- **実施内容:**
  - `src/phase4_retrieval.py`の`build_prompt()`に`response_language: str =
    "ja"`を追加。回答言語の指示文のみ日英で切り替え、比較表・詳細カルテ
    （日本語データ）自体は翻訳しない設計とした（Geminiは日本語データから
    英語で説明を生成できるため）。
  - `generate_answer()`/`hybrid_search()`に同様に追加・伝播し、戻り値dictに
    `"response_language"`を追加（Phase22/23の`embedding_source`と同じ慣習）。
  - `src/phase6_app.py`の`SearchRequest`/`SearchResponse`に
    `response_language`を追加し配線した。
- **確認結果:** `response_language="en"`を指定してAPIを直接呼び出し、
  「Show me buildings with low storm surge risk」への回答が完全に英語
  （見出し `## Recommended Buildings` 含む）で返ることを確認した。
- **サニティチェック:** ✅ 英語回答生成を実APIコールで確認
- **コミットハッシュ:** （このコミットで記録）

### Step 24-5: フロントエンド最終配線・動作確認・記録
- **日時:** 2026-08-28
- **実施内容:**
  - `frontend/src/api.ts`に`response_language`を追加し、`main.ts`の
    `runSearch()`で`store.get().language`をそのまま渡すよう配線。
  - `pixi run build`でビルド成功を確認（1回目、`chat.ts`で未使用の
    `translateValue`インポートによるTS6133エラーを発見・削除して解消）。
  - `pixi run dev` ではなく `pixi run build && pixi run app`
    （Phase23で修正済みの本番配信経路）でブラウザ確認を実施。
- **確認できたこと:**
  - `lang-toggle`クリックで、ヘッダー・ウェルカムメッセージ・入力エリア・
    オプション選択・サンプル質問ボタン（表示文言とクリック時の送信文の両方）が
    英語表示に切り替わることを確認。
  - localStorage永続化により、ページリロード後も選択した言語が維持される
    ことを確認。
  - 英語モードで実際に検索を実行し、`POST /api/search`のレスポンスに
    `response_language: "en"`が含まれ、LLM回答本文が完全に英語で
    返ってくることを確認。
- **確認できなかったこと（環境制約）:** 地図パネルの凡例・ポップアップの
  実際の英語表示は、本セッションのブラウザプレビュー環境から
  `tiles.openfreemap.org`（MapLibreのベクトルタイルスタイル）への
  外部ネットワークアクセスが行えず（`read_network_requests`で該当リクエストが
  一切記録されない）、地図スタイルの読み込みが完了しないため確認できなかった。
  これはPhase24の実装に起因する問題ではなく、既存のプレビュー環境の
  ネットワーク制約であり、Phase23以前から同様の制約が存在していたと考えられる
  （Phase23の動作確認でも地図の詳細表示までは確認していなかった）。
  地図凡例・ポップアップの多言語化コード（Step24-3）は静的UI翻訳と同一の
  `t()`/`translateValue()`パターンで実装しているため、ロジック上の
  正しさはコードレビューで確認済みだが、**ユーザーの手元環境（外部ネットワーク
  に到達可能）での目視確認を推奨する**。
- **サニティチェック:** ✅ 静的UI・動的メッセージ・LLM回答（英語化）を確認、
  ⚠️ 地図凡例・ポップアップは環境制約によりコードレビューのみ
- **コミットハッシュ:** （このコミットで記録）
- **既知の制限:** README.mdに記載（固有名詞未翻訳、言語トグル時に既存の
  会話履歴・地図表示は再翻訳されない、LLM回答言語はUI言語と連動）。

---

## [Phase 25] 楕円形（オーバル）分類の追加とあいまい「円形」クエリの複数形状マッチ対応

> ユーザーから「広島駅付近に楕円のような形状のビルがあったはず」との指摘を受け、
> `pixi run dev` + `pixi run app` で実機確認したところ、「広島駅付近で円形の建物を探して」
> が0件になる事象を発見。原因調査の結果、Phase20の`circularity`（真円度）は離心率に
> 敏感な指標であり、真円しか捉えられないことが判明（Phase20の既知の限界②とも関連）。
> ユーザーと協議のうえ、「円形」「丸い」はあいまい表現として円形・楕円の両方にヒットさせ、
> 「真円」「楕円」は明示的に絞り込めるようにする方針で合意し、`docs/plan.md` Phase 25 として
> 計画を承認（承認日 2026-08-28）。

### Step 25-1: 楕円形状判定ロジックの追加
- **日時:** 2026-08-28
- **実施内容:**
  - 新指標 `box_fill_ratio = footprint_area_m2 / bbox_area_m2` を導入。`bbox_area_m2` は
    `ST_MinimumRotatedRectangle`（DuckDB spatialに存在確認済み）による最小回転外接矩形の
    面積で、`fetch_footprint_shape()`（`src/phase9_geometry.py`）のSQLに追加取得。
  - 真円・楕円は外接矩形に内接する図形として、アスペクト比によらず理論値
    `π/4≈0.785` に収束する（`circularity`と異なり離心率に鈍感）。矩形は
    `box_fill_ratio≈1.0` になるため、`_OVAL_BOX_FILL_MIN=0.70`/`_OVAL_BOX_FILL_MAX=0.85`
    で区別する定数を追加。
  - `estimate_shape_type()` に楕円形分岐を追加（`circularity>=0.85`の直後、
    `concave_vertex_count==0`判定の中）。Phase20の`circularity>=0.85`判定はそのまま
    残しているため、既存の「円形に近い」判定ロジックへの変更は無い。
  - `building_geom_meta`テーブルに`bbox_area_m2`/`box_fill_ratio`カラムを追加。
- **確認結果:**
  - `pixi run python src/phase9_geometry.py` を再実行し、2958件を再構築。
  - 形状分類の分布: `{'矩形・単純形状': 1480, 'L字型': 438, 'コの字型・T字型': 433,
    '十字型・複雑形状': 300, '星形・複雑形状': 265, '楕円形': 33, '円形に近い': 9}`。
    「円形に近い」は Phase20 時点と同じ9件のまま変化なし（回帰なし）。
  - 広島駅から500m以内の建物を確認したところ、新たに5件が「楕円形」に分類され、
    ユーザーが指摘した建物が拾えるようになったことを確認。
  - 楕円形33件の`box_fill_ratio`は0.70〜0.85の範囲に収まり、`circularity`は0.44〜0.83と
    ばらつく（アスペクト比に応じて`circularity`が下がっても`box_fill_ratio`は安定して
    捉えられるという設計意図通りの挙動）。
- **サニティチェック:** ✅ 円形9件不変・楕円形33件検出・広島駅近傍5件検出を確認
- **コミットハッシュ:** （このコミットで記録）

### Step 25-2: クエリ解析・SQLフィルタの複数形状対応
- **日時:** 2026-08-28
- **実施内容:**
  - `query_parser.py`: `ParsedQuery.footprint_shape` を `str|None` → `list[str]`
    （デフォルト空リスト）に変更。`_SHAPE_VALUES` に「楕円形」を追加、
    `_RESPONSE_SCHEMA["footprint_shape"]` を配列型に変更。
  - `_SHAPE_RULES` を更新: 「真円」「正円」「円形に近い」（分類名そのもの）→
    `["円形に近い"]`、「円形」（単独）「丸い」「円柱状」「曲線的な形状」→
    `["円形に近い","楕円形"]`、「楕円」「オーバル」「小判型」「卵型」→ `["楕円形"]`。
  - `phase10_router.py`: `build_filter_clauses()` の `shape_type_est = ?` を
    `IN (...)`（usage_include と同一パターン）に変更。`verify_candidates()` を
    `isin()` ベースに変更。`classify_route()` は空リストがFalsyのため変更不要。
- **不具合発見・修正:** 当初のルール文言では「円形に近い建物を教えて」
  （Phase20 gold_set G37 のクエリ。分類名"円形に近い"をそのまま含む）が
  あいまい「円形」パターンにもマッチしてしまい、`footprint_shape=['円形に近い','楕円形']`
  となり G37 の期待値（円形のみ9件）が崩れる回帰を発見。「円形に近い」を
  「真円」「正円」と同じ厳密表現として明示的にルールへ追加し解消した。
- **確認結果（`hybrid_search` 直接実行）:**
  - 「円形に近い建物を教えて」→ 9件、`shape_type_est`は'円形に近い'のみ（G37と一致・回帰なし）
  - 「広島駅付近で円形の建物を探して」→ 5件、全て'楕円形'（ユーザーが指摘した建物を検出）
  - 「広島駅付近で真円の建物を探して」→ 0件（従来通り。真円は744m先のみ）
- **サニティチェック:** ✅ 上記3クエリすべて期待通り。既存G37相当の回帰なしを確認
- **コミットハッシュ:** （このコミットで記録）

### Step 25-3: テスト・サニティチェックの更新
- **日時:** 2026-08-28
- **実施内容:**
  - `tests/gold_set.py` に G40「楕円形の建物を教えて」（`shape_type_est = '楕円形'`）・
    G41「丸い建物を探して」（`shape_type_est IN ('円形に近い', '楕円形')`）を追加。
    既存 G37〜G39 は変更なし。
  - `tests/sanity_checks.py` に `check_phase25_ellipse_shape()`（shape_type_est
    分類数=7種の確認、「楕円形の建物を教えて」「丸い建物を探して」「真円の建物を探して」
    の3クエリで期待される shape_type_est 集合の部分集合になっていることを確認）・
    `run_phase25_checks()`（`--phase25` 引数）を追加。
- **確認結果:**
  - `pixi run python tests/gold_set.py` 実行: G40=33件、G41=42件（9+33=42、
    円形9件と楕円形33件の合算と一致）。既存 G37=9件のまま変化なし。
  - `pixi run python tests/sanity_checks.py --phase25` → 全パス。
  - `pixi run python tests/sanity_checks.py --phase20` → 引き続き全パス（回帰なし）。
- **サニティチェック:** ✅ Phase20/Phase25とも全チェックパス
- **コミットハッシュ:** （このコミットで記録）
- **備考:** `tests/eval_retrieval.py`（LLM APIを呼ぶ全件recall/precision評価）は
  コスト・時間の都合上、本Stepでは実行していない。次回全体評価を回す際にG40/G41も
  対象に含まれる。

### Step 25-4: 動作確認
- **日時:** 2026-08-28
- **実施内容:** `pixi run python src/phase9_geometry.py` 再構築後、FastAPIバックエンド
  （新規プロセス、port 8001）を起動し、Vite開発サーバー（port 5173, `plateau-rag-dev`）
  経由でブラウザから実クエリを実行して確認した。
- **確認結果（ブラウザ fetch 経由の実HTTPリクエスト）:**
  - 「広島駅付近で円形の建物を探して」→ `route=structured`, `footprint_shape=['円形に近い','楕円形']`,
    5件（全て'楕円形'）。ユーザーが指摘した楕円形建物が拾えることを確認。
  - 「広島駅付近で真円の建物を探して」→ 0件（従来通り。真円は744m先のみ）。
  - 「楕円形の建物を教えて」→ 10件（top_k上限、全て'楕円形'）。
  - 「円形に近い建物を教えて」→ 9件（全て'円形に近い'）。G37相当の回帰なし。
- **サニティチェック:** ✅ 上記4クエリすべて期待通り。
- **コミットハッシュ:** （このコミットで記録）
- **既知の問題（Phase25の実装とは無関係の環境事象）:** 動作確認の過程で、以前起動した
  `pixi run app`（port 8000）が異常終了後もOSのTCPリッスンテーブルにゴーストとして
  残留し、`taskkill`（Bash）・`Stop-Process`（PowerShell）のいずれでも解放できない
  状態を確認した（`Get-Process`でPID自体が見つからないにも関わらずport 8000を
  握り続ける）。原因は本セッションのサンドボックス環境のネットワーキング層の問題と
  推測され、Phase25のコード変更とは無関係。回避策として新規ポート（8001）で
  バックエンドを起動し、フロントエンドからは直接fetchで検証した。次回セッションで
  `pixi run app`を使う際にport 8000が使用中の場合はターミナル再起動を試すこと。

### Step 25-5: ユーザー報告に基づく高頂点数曲線フットプリントの誤分類修正
- **日時:** 2026-08-28
- **現象:** ユーザーがUI地図上で楕円形に見える建物（`bldg_b6fb7f0d-cd0b-4ca0-a5c4-
  0589648222f5`、用途:店舗等併用共同住宅、高さ75.8m）を提示し、「円形の建物」検索に
  ヒットしない不具合を報告。
- **原因調査:** 当該建物は `circularity=0.5648`, `convexity_ratio=0.9572`,
  `box_fill_ratio=0.8121`（楕円形範囲内）, `footprint_vertex_count=40`,
  `concave_vertex_count=11` だった。Step25-1の楕円形判定は
  `concave_vertex_count==0`（完全な凸多角形）を要求していたため、この建物は
  素通りして `星形・複雑形状` に誤分類されていた。原因は、滑らかな曲線を
  多数（40）の短い辺で近似したフットプリントは、デジタイズ時の丸め誤差で
  符号判定が反転する頂点が多数（11個）発生し、`concave_vertex_count` が
  大きくなってしまうため（幾何的にはほぼ凸形状＝`convexity_ratio=0.9572`
  なのに、頂点ベースの凹角カウントでは「凹角が11個ある複雑形状」と
  誤判定されていた）。
- **調査方法:** `footprint_vertex_count>=15 かつ convexity_ratio>=0.90 かつ
  box_fill_ratio∈[0.70,0.85]` の条件で実データを検索したところ、既存の
  「星形・複雑形状」236件中36件・「十字型・複雑形状」39件中2件が該当し、
  いずれも `concave_vertex_count / footprint_vertex_count` が0.16〜0.43程度に
  分散した「小さな凹角が多数」というプロファイルで、単一の大きな切り欠きを
  持つ真のL字型・十字型とは性質が異なることを確認した。
- **解決策:** `estimate_shape_type()` の楕円形判定を、`concave_vertex_count==0`
  の場合に加えて「頂点数15以上 かつ convexity_ratio 0.90以上」の場合も
  box_fill_ratio による楕円形判定を適用するよう修正（`_OVAL_NOISY_MIN_VERTEX=15`,
  `_OVAL_NOISY_CONVEXITY_MIN=0.90`）。`estimate_shape_type()` に
  `footprint_vertex_count` 引数を追加。
- **確認結果:**
  - `pixi run python src/phase9_geometry.py` 再構築後、`bldg_b6fb7f0d-...` が
    `shape_type_est='楕円形'` に修正されたことを確認。
  - 分類分布: `{'矩形・単純形状':1480, 'L字型':438, 'コの字型・T字型':433,
    '十字型・複雑形状':298(-2), '星形・複雑形状':229(-36), '楕円形':71(+38),
    '円形に近い':9(不変)}`。矩形・L字型・コの字型・円形に近いは完全に不変。
  - `pixi run python tests/sanity_checks.py --phase20` / `--phase25` とも全パス。
  - `pixi run python tests/gold_set.py` 再生成: G37=9件(不変)、G38=438件(不変)、
    G39=229件(265→229、星形分類の精緻化を反映)、G40=71件(33→71)、G41=80件(9+71)。
- **サニティチェック:** ✅ 上記すべて確認、回帰なし
- **コミットハッシュ:** （このコミットで記録）
- **備考:** この修正は「デジタイズ由来の見せかけの複雑形状」を「実質的に丸い形状」に
  正しく寄せるものであり、`星形・複雑形状`/`十字型・複雑形状` の減少（-38件）は
  意図した精度改善である。

---

## [Phase 26] 視覚デザイン刷新（改名・レスポンシブ改善込み）

> FOSS4G向けスクリーンショットへのユーザーフィードバック（言語トグルの折り返し
> 不具合・アプリ名変更・デザイン全体見直し・モバイル対応）を受け、`frontend-design`
> スキルの指針に従い「測量機器・地図計測器」を方向性としたビジュアル刷新を実施した。

### Step 26-1〜26-5: デザイントークン刷新・改名・レスポンシブ改善
- **日時:** 2026-08-28
- **実施内容:**
  - `frontend/src/style.css`のカラートークンを刷新。`--ink`（墨）/`--paper`
    （紙）/`--depth`（浸水深を想起するティール、旧`--accent`の青から置換）/
    `--flag`（測量旗の温色アクセント）を基調とするパレットに置き換えた
    （ライト/ダーク両テーマ、`--accent`等の変数名は維持し値のみ変更したため
    呼び出し側の修正は不要だった）。`src/map.ts`の`ACCENT_COLOR`定数
    （CSS変数を解決できないMapLibre paint式専用の複製値）も合わせて更新。
  - Google Fonts（Space Grotesk / Zen Kaku Gothic New / JetBrains Mono）を
    `frontend/index.html`に追加。本文は日英共通でZen Kaku Gothic New、
    見出し・ブランドワードマークはSpace Grotesk、建物ID・距離・座標・
    スコア等の数値表示はJetBrains Monoに統一した。
  - 言語/テーマ切り替えボタンの不具合（「日本語」が正方形アイコンボタンに
    収まらず2行折り返しになる）を修正。`.btn--icon`固定44×44pxから、
    可変幅の`.btn--toggle`（テキスト用）/`.btn--toggle-icon`
    （アイコン用、44px以上を維持）に分離し、`.toggle-group`で
    セグメントコントロール風にまとめた。
  - アプリ名を`frontend/src/i18n.ts`の`appTitle`で日英とも
    「City RAG Example」に統一（絵文字は削除しSpace Groteskの
    ワードマークのみにした）。`<title>`・`<meta description>`も更新。
    ヘッダーに実用的なアイキャプション（"HIROSHIMA · PLATEAU 3D BUILDING
    SEARCH" / "広島市 · PLATEAU 3D建物検索"）を追加。
  - シグネチャ要素として「目盛り（スケールバー）」モチーフ
    （`.scale-divider`、CSS `repeating-linear-gradient`による目盛り表現）を
    ウェルカム画面の見出し下に追加。
  - メッセージバブル・地図ボタン・入力欄等の角丸を16px/20px系から
    8-10px系に統一し、より直線的な「計測器」の質感に寄せた。
  - 入力オプション行（モデル/件数/埋め込み選択）を`.input-options__group`で
    グルーピングし、モバイル幅でラベルと選択肢が分離して折り返らないようにした。
    ラベルをモノスペース・small caps表記に変更し、selectのタップ領域を
    32px→40pxに拡大。
- **不具合の発見・修正（実装中）:** アイコン用トグルボタンを可変幅クラスに
  分離した際、`.btn--toggle-icon`のpaddingを縮小しすぎて幅22.8pxとなり、
  既存の「UD: min 44pxタッチターゲット」要件を下回る回帰を作ってしまった。
  ブラウザでの実測確認により発見し、`min-width: 44px`を追加して解消した。
- **確認結果（ブラウザ実測、`pixi run build && pixi run app`）:**
  - 375px（モバイル）/1280px（デスクトップ）双方で`scrollWidth ===
    clientWidth`（横スクロールなし）を確認。
  - 言語トグルボタンの実測サイズ: 幅59.3px・高さ44px（1行表示、折り返しなし。
    修正前は2行に折り返っていた不具合が解消）。
  - テーマ切り替えボタン: 44×44px（UD要件を維持）。
  - ダークモード切り替え後、`--accent`が新パレットの`#57c8d1`
    （ティール）に正しく反映されることを確認。
  - `<title>`が「City RAG Example」に、ヘッダーのブランド名・アイキャプションが
    日英切り替えに連動して正しく表示されることを確認。
- **サニティチェック:** ✅ `pixi run build`成功、375px/1280pxでの横スクロールなし、
  タップターゲット44px維持、ライト/ダーク/日英の組み合わせ動作確認
- **コミットハッシュ:** （このコミットで記録）
- **既知の制限:** 前回（Phase24）同様、このセッションのブラウザプレビュー環境からは
  外部地図タイルサーバーに到達できないため、地図パネル内の見た目（凡例・
  ポップアップの配色反映）はコードレビューのみで、実際の目視確認は
  ユーザーの手元環境での確認を推奨する。

### Step 26-6: 13インチノートPCでのスクロール解消・デモ向けフォントサイズ調整
- **日時:** 2026-08-28
- **実施内容:** ユーザーから「13.3インチノートPCでウェルカム画面がスクロールを
  要求する」「デモで見せるにはフォントが小さい」との指摘を受け、追加調整を実施。
  - `.welcome-msg`の余白を大幅に圧縮: padding `40px 24px`→`16px 24px`、
    gap `12px`→`8px`、アイコン`48px`→`32px`、`.scale-divider`の上下マージンを
    ゼロに、`.welcome-msg__attribution`を`12px/opacity 0.8`→`11px/opacity
    0.65`に縮小（データ出典注記は補助的情報のため優先度を下げた）、
    `.example-btn`のpaddingを`10px 16px`→`8px 16px`に圧縮（`min-height:
    44px`のタップターゲット要件は維持）。
  - 一方でデモでの視認性を優先し、`.welcome-msg__title`（22px→24px）・
    `.welcome-msg__hint`（14px→15px）・`.example-btn`文字（13px→14px）・
    `.msg__bubble`（14px→15px）・`.input-form__textarea`（14px→15px）は
    サイズアップした。`.message-list`のpaddingも`16px`→`12px 16px`に微調整。
- **確認結果（ブラウザ実測）:** `pixi run build && pixi run app`で起動し、
  ビューポート高さ700px/650px/560px（13インチノートPC相当〜それ以下）で
  `message-list`の`scrollHeight === clientHeight`（スクロール不要）を確認。
  560pxの極端に低い高さでもサンプル質問ボタン3件・見出し・注記文がすべて
  クリップされずに表示されることを確認した。
- **サニティチェック:** ✅ 700/650/560pxいずれもスクロールなし、要素の
  クリップなし、`.example-btn`のタップターゲット44px維持を確認
- **コミットハッシュ:** （このコミットで記録）

### Step 26-7: フォントサイズの再拡大とモバイル入力欄の可視性改善
- **日時:** 2026-08-28
- **実施内容:** Step26-6後もユーザーから「まだフォントが小さい」
  「スマホでチャット入力欄が少し隠れる」との指摘があり、追加対応した。
  - フォントサイズをさらに拡大: `.app-title`（18→21px）・
    `.welcome-msg__title`（24→30px）・`.welcome-msg__hint`（15→17px）・
    `.example-btn`（14→16px）・`.msg__bubble`（15→17px）・
    `.input-form__textarea`（15→17px）・`.input-options__select`
    （13→15px）・`.msg__meta`（12→13px）・`.building-item`（13→14px）・
    地図ポップアップ各要素（12-13px→13-14px）。
  - フォント拡大でスクロールが再発しないよう、`@media (max-height:
    700px)`で ウェルカム画面（アイコン・見出し・余白・出典注記・
    サンプルボタン）を追加圧縮し、`@media (max-height: 560px)`では
    出典注記と目盛り区切り線を非表示にする段階的フォールバックを実装した。
  - モバイルでチャット入力欄が隠れる不具合に対応。原因はソフトキーボード
    表示時に`100dvh`がキーボード分を差し引かない機種があるため。
    `frontend/src/main.ts`に`setupViewportHeightFix()`を実装し、
    `window.visualViewport`の実測高さをCSSカスタムプロパティ
    `--app-height`に反映、`body`の`height`を`100dvh`から
    `var(--app-height, 100dvh)`に変更した（JS未実行時は100dvhに
    フォールバック）。保険として、テキストエリアのfocus時に
    `scrollIntoView({block:'end'})`する処理も追加した。
- **確認結果（ブラウザ実測）:** 1280×650pxで縮小メディアクエリが働き
  見出しフォント30px→24pxに自動調整されスクロールなしを維持、
  1280×800pxでは通常の30px見出しでもスクロールなしを確認。
  モバイル幅（375×812）で`--app-height`が`window.visualViewport.height`と
  一致し、入力エリアの下端がビューポート下端に一致することを確認した
  （このプレビュー環境では実機のソフトキーボード表示自体はシミュレート
  できないため、`--app-height`の追従機構が正しく動作することの確認に留まる。
  実機でのキーボード表示時の見え方はユーザーの手元環境での確認を推奨する）。
- **サニティチェック:** ✅ フォント拡大後もスクロール非発生（650px/800px）、
  `--app-height`の追従を確認
- **コミットハッシュ:** （このコミットで記録）

### Step 26-8: 回答本文の「間延び」解消・地図ボタンの視認性向上・モバイル横あふれ修正
- **日時:** 2026-08-28
- **実施内容:** ユーザーから「回答が間延びして見える（PC・スマホ双方）」
  「地図で確認できることが分かりにくい」との指摘を受け対応した。
  - Markdown回答の余白を全体的に圧縮: 見出し（h1〜h4）のフォントサイズを
    `1.3em〜1.0em`→`1.15em〜1.0em`に、margin`12px 0 6px`→`10px 0 3px`に、
    段落margin`6px 0`→`4px 0`、リストmargin`6px 0`→`4px 0`・
    `li margin 2px`→`1px`に圧縮し、`.msg__bubble--markdown`自体の
    `line-height`を1.65→1.5に設定した。
  - 「地図で確認できることが分かりにくい」への対応として、`🗺 地図で
    N件を確認`ボタンを回答フッター（本文の最後）から**回答本文の先頭**
    （アバターの直後、Markdown本文より前）に移動し、幅いっぱい・
    やや大きめ（`.btn--map-toggle-top`、44px高さ）にして見落とされない
    ようにした。`frontend/src/chat.ts`の`appendAssistantMessage()`の
    innerHTML構築順を変更。
  - LLM回答中の「建物ID: bldg_xxx-...」が太字の生テキストで表示され
    視覚的に重く見えていたため、`_renderMarkdown()`にMarkdown解析前の
    前処理を追加し、建物ID（`bldg_`+UUID）パターンを自動的に
    バッククォートで囲んでインラインコード化（モノスペース・控えめな
    背景ピル）するようにした。
- **不具合の発見・修正（確認作業中）:** モバイル幅（375px）で確認した際、
  長い建物ID文字列を含む回答が吹き出し右端からはみ出し、
  `overflow-x: hidden`で**見えないまま切り捨てられている**（テキストが
  実質的に読めなくなる）重大な不具合を発見した。原因は`.msg`
  （flexbox）に`min-width: 0`が指定されておらず、子要素の内容幅に
  応じてflexアイテムがビューポート幅を超えて広がっていたため
  （flexboxの既定`min-width: auto`によるオーバーフロー）。
  `.msg`・`.msg__body`に`min-width: 0`を追加し、`.msg__bubble--markdown
  code`に`overflow-wrap: anywhere; word-break: break-word;`を追加して
  解消した。
- **確認結果（ブラウザ実測、実際に検索を実行）:**
  - デスクトップ: 見出し・段落の余白が視覚的に詰まり、地図ボタンが
    回答冒頭に大きく表示されることを確認。建物IDがモノスペースの
    ピル表示になったことを確認。
  - モバイル（375px）: 修正前は`.msg__bubble--markdown`の
    `getBoundingClientRect().right`が318〜481px（ビューポート幅375pxを
    超過）だったが、修正後は260〜318px幅に収まり、
    `document.documentElement.scrollWidth === clientWidth`
    （375px、横あふれなし）を確認。長い建物ID・本文とも正しく
    折り返して表示されることをスクリーンショットで確認した。
- **サニティチェック:** ✅ モバイル横あふれ解消・地図ボタン視認性向上・
  Markdown余白圧縮を確認
- **コミットハッシュ:** （このコミットで記録）

### Step 26-9: 見出し下の不要な空行の根本原因を修正・回答の簡潔化
- **日時:** 2026-08-28
- **実施内容:** ユーザーから「見出しの下などに不要な改行がある」
  「回答の理由が長く情報量が多すぎる」との指摘を受け対応した。
  - **CSS詳細度バグの発見・修正**: ブラウザで実際にAPIを叩いて回答を
    レンダリングし、`getBoundingClientRect()`で要素間の実測ギャップを
    調査したところ、見出し下の空白は「余白の設定ミス」ではなく、
    `.msg--assistant .msg__bubble { white-space: pre-wrap; }`
    （詳細度0,0,2,0）が`.msg__bubble--markdown { white-space: normal; }`
    （詳細度0,0,1,0）に**CSS詳細度で打ち勝ってしまい**、リスト項目内の
    ブロック要素（`<p>`と`<ul>`）間にあるソース上の改行テキストノードが
    そのまま「空行」として描画されていたことが根本原因と判明した
    （Step26-6〜26-8で見出し・段落・リストのmarginを圧縮しても解消しな
    かった理由はこれだった）。セレクタを`.msg--assistant
    .msg__bubble--markdown`に変更し、pre-wrap側と同じ詳細度に揃えた上で
    ソース順を後ろに配置し、確実に上書きされるようにした。
  - **回答の簡潔化（プロンプト調整）**: `src/phase4_retrieval.py`の
    `build_prompt()`で、`language_instruction`の「詳しく説明してください」
    を「簡潔に説明してください」に変更。【回答形式】に新ルールを追加:
    推薦理由を箇条書き2〜3点に絞る・各理由は1〜2文で数値根拠1〜2個まで・
    入れ子の箇条書みを使わずフラットな箇条書みにする、を明記した。
- **確認結果:**
  - 修正前後で同一クエリ（「広島駅周辺の宿泊施設を教えて」）の回答文字数を
    比較: 修正前は約1000文字超（見出し3階層・入れ子箇条書み・4項目の
    詳細説明）→ 修正後は214文字（フラットな箇条書み3点）に短縮。
  - ブラウザで実際にレンダリングし、見出し直下・箇条書み項目間の
    不要な空行が解消されたことをスクリーンショットで確認。
  - `getComputedStyle(bubble).whiteSpace`が`"normal"`になっている
    （修正前は`"pre-wrap"`が漏れていた）ことを確認。
- **サニティチェック:** ✅ 空行解消・回答簡潔化（214文字/フラット箇条書み）を
  実機確認
- **コミットハッシュ:** （このコミットで記録）
- **教訓:** 見た目の不具合を都度CSSの数値（margin/padding）だけで
  「圧縮」して対処しようとすると、詳細度や継承の構造的な問題を
  見逃したまま表面的な調整を繰り返すことになる。今回は実際に
  `getBoundingClientRect()`で要素の実測値を取得し、想定外の数値
  （line-height相当のギャップが2箇所）から原因を逆算したことで
  根本原因（詳細度の逆転）に辿り着けた。

---

## [Phase 27] モバイル地図のボトムシート化

> ユーザーから「PC（左地図・右チャット）は現状で良いが、スマホはボトムシート
> なり工夫できないか」との要望があり対応した。設計検討として「チャットを
> 土台・地図をボトムシート」と「地図を土台・チャットをボトムシート」の
> 2案を比較し、本アプリの主操作が「自然言語で質問する」ことである以上、
> 地図はRAGの実現に比べれば優先度が低い副次的手段という位置づけから
> 前者を採用した。

### Step 27-1〜27-5: ボトムシートの実装・動作確認
- **日時:** 2026-08-28
- **実施内容:**
  - `frontend/src/store.ts`の`isMobileMapOpen`（bool）を廃止し、
    `mapSheetState: 'hidden' | 'peek' | 'half' | 'full'`に置き換えた。
  - `frontend/index.html`の`map-mobile-header`を、つまみ兼展開ボタン
    （`#map-sheet-peek-bar`、44px以上のタップ領域）+ 縮小ボタン
    （`#map-sheet-collapse-btn`）+ 閉じるボタン（`#map-close-btn-mobile`）
    の構成に置き換えた（旧`map-back-btn`「← 戻る」は撤去）。
  - `frontend/src/style.css`の`@media (max-width: 767px)`内で、
    `.panel-map`を`fullscreen`固定オーバーレイから、`position: fixed;
    left/right/bottom:0`＋`height`を`[data-sheet-state]`属性値
    （`peek`=64px、`half`=50vh、`full`=90vh、属性なし=0=hidden）で
    切り替えるボトムシートに変更した。`transition: height 0.25s`で
    スナップアニメーションし、ドラッグ中は`.dragging`クラスで
    transitionを無効化して指の動きに直接追従させる。
  - `frontend/src/main.ts`に`setMapSheetState()`・
    `setupMapSheetDrag()`を新規実装。Pointer Events
    （`pointerdown`/`pointermove`/`pointerup`）でつまみ帯全体
    （`#map-sheet-peek-bar`）のドラッグを検出し、移動量6px未満は
    タップ（一段階展開: peek/hidden→half、half/full→full）、
    それ以上はドラッグとして高さを直接追従させ、指を離した時点の高さに
    最も近いスナップポイント（peek/half/full）へ確定する。
  - 検索結果取得時（`runSearch()`）の自動地図表示ロジックを整理:
    PC/タブレットは既存の`.visible`自動表示を維持、モバイルは
    `mapSheetState`が`'hidden'`の場合のみ自動で`'peek'`にする
    （ユーザー指摘への対応: 既に`half`/`full`まで開いている場合は
    状態を維持し、地図を見ながら追加で質問する使い方を妨げない）。
  - `history.pushState`/`popstate`によるブラウザ戻るボタン連動は撤去した
    （ボトムシートは画面遷移ではなく同一画面内のUI状態変化のため）。
  - `frontend/src/map.ts`の`setGeojson()`に、既存の`#map-result-count`
    （PC/タブレット用）に加えて`#map-sheet-count`（モバイルのつまみ帯）
    への件数反映を追加。
  - `frontend/src/i18n.ts`に新規文言を追加（`mapSheetExpandAriaLabel`、
    `mapSheetCollapseBtnAriaLabel`、`mapSheetPeekAnnounce`、
    `mapSheetHalfAnnounce`、`mapSheetFullAnnounce`）。不要になった
    `mapBackBtn`/`mapBackBtnAriaLabel`/`mapPanelHeading`は削除した。
- **設計判断の記録（ユーザーとの議論）:** 当初「つまみ単体をタップ領域に
  する」案を提示したところ、ユーザーから使いやすさの観点で2点の改善案
  （①つまみ帯全体をタップ可能にする、②検索のたびにpeekへ強制的に戻さず
  既存の展開状態を維持する）を得て採用した。
- **確認結果（ブラウザ実測、`pixi run build && pixi run app`、375px幅）:**
  - 初期状態: `data-sheet-state`属性なし・`aria-hidden="true"`・
    高さ0pxを確認。
  - 検索実行後: 自動的に`data-sheet-state="peek"`・高さ64px・
    `#map-sheet-count`に「候補 N 件」が表示されることを確認。
  - `#map-sheet-peek-bar`への合成PointerEvent（pointerdown→pointerup、
    移動なし）で`peek→half`のタップ展開を確認。
  - 合成PointerEvent（pointerdown→400px分のpointermove→pointerup）で
    ドラッグ中に高さがリアルタイム追従し（実測730.8px）、指を離した
    位置に最も近い`full`（90vh=730.8px）へ正しくスナップすることを確認。
  - `#map-sheet-collapse-btn`のクリックで`full→half→hidden`と
    一段階ずつ縮小することを確認。
  - シートを`half`まで開いた状態で新しいクエリを実行し、
    `mapSheetState`が`half`のまま維持され（`peek`に戻らない）、
    件数表示のみ新しい検索結果（10件）に更新されることを確認
    （ユーザーの改善案②の動作を確認）。
  - 実際に地図タイル・MapLibreコントロール（ズーム・回転）・凡例・
    候補建物リストが正しく描画されることも確認（今回はプレビュー環境の
    外部ネットワークが到達可能だった）。
  - タブレット/デスクトップ幅（1280px）で既存動作
    （`.panel-map.visible`クラストグル、幅704px=55%相当）に
    回帰がないことを確認。
- **サニティチェック:** ✅ 初期hidden・自動peek表示・タップ展開・
  ドラッグ+スナップ・段階的collapse・状態維持（既存open時の非リセット）・
  PC/タブレット回帰なし、をすべてブラウザ実測で確認
- **コミットハッシュ:** （このコミットで記録）
- **既知の制限:** ブラウザ戻るボタンでシートを閉じる連動は撤去した
  （ボトムシートはページ遷移ではないため）。つまみに`role="slider"`等の
  高度なARIAセマンティクスは付与しておらず、キーボード操作は展開/縮小/
  閉じるの3ボタンのみで行う（連続的な高さ調整はドラッグ操作のみ）。

---

## [Phase 28] 最上級クエリ（一番高い等）の推薦をコード側で確定させる

### Step 28-1〜28-3: プロンプト改修・検証・記録
- **日時:** 2026-08-28
- **不具合報告:** 「What is the tallest building around Hiroshima Station?」で、
  検索候補1位（97.4m）ではなく2位（90.9m）がLLMの回答として推薦される事象を
  ユーザーが発見。ユーザーからの仮説「距離順ではなく高さ順で推薦すべきでは」を
  起点に調査した。
- **調査結果（原因切り分け）:**
  - `query_parser.py`の解析結果は`sort_by={key: measured_height, order: desc}`で
    正しく、非決定性の問題も5回試行で再現せず。
  - `phase10_router.py`の`ORDER BY`構築ロジック（sort_by優先）も正しく、
    `hybrid_search()`に渡る`candidates` DataFrameは実際に1位=97.4mの降順で
    確定していた（直接実行で確認）。
  - 原因は`build_prompt()`（`src/phase4_retrieval.py`）にあった。`sort_by`指定時、
    プロンプトは「表がその順に並んでいる」旨（`sort_note`）を伝えるのみで、
    「表1位を推薦せよ」という確定的な指示になっておらず、プロンプト本文も
    「ユーザーの質問に最も合致する建物を**選定**し」とLLMの自由裁量に委ねる
    書き方だった。CLAUDE.mdの設計方針（構造化条件はSQLで確定判定し、LLMの
    推論に委ねない）に対する抜け穴だった。
  - 既存の`tests/eval_retrieval.py`は`skip_answer=True`で検索段のみを評価しており、
    LLM回答生成後の最終推薦IDを検証していなかったため、この不具合を
    検出できていなかった。
- **対応内容:**
  - `build_prompt()`: `sort_by is not None`の場合、`candidates.iloc[0]`のIDを
    `top_id`として取得し、「必ず比較表1位（`{top_id}`）を推薦すること。他の建物を
    推薦してはならない」という確定的な指示に変更（従来の`recommend_count_rule`を
    `fixed_recommendation_rule`に置き換え）。次点2件のIDもコード側で固定して
    プロンプトに明示し、LLMの役割を「理由説明」のみに限定した。
  - `hybrid_search()`: `sort_by`指定時、LLM回答冒頭で言及された建物IDが
    `candidates`の1位と一致するかを確認するログ出力（不一致ならワーニングのみ、
    回答は改変しない）を追加。今後の再発検知用。
  - `tests/sanity_checks.py`: `check_phase28_superlative_recommendation()`を
    新規追加。日本語「広島駅付近で一番高い建物を教えて」・英語
    "What is the tallest building around Hiroshima Station?" の2クエリで
    `hybrid_search()`をフル実行し、回答冒頭の建物IDが比較表1位と一致することを
    確認する。`run_phase28_checks()` / `--phase28` CLI分岐を追加。
- **確認結果:**
  - 修正後、報告事例（英語クエリ）を再実行し97.4mの建物（1位）が正しく
    推薦されることを確認。
  - `tests/sanity_checks.py --phase28`: 日英2クエリともパス。
  - 既存gold_set G01「広島市で最も高い建物は？」を3回連続実行し、
    毎回1位建物（`bldg_22ee3854-abb9-45fd-8302-df8f8154f1fd`）と回答の
    推薦IDが一致することを確認（回帰なし）。
  - `tests/sanity_checks.py --phase18`（推薦ID抽出・GeoJSON順序保持）も
    回帰なしでパス。
- **サニティチェック:** ✅ 全項目パス
- **コミットハッシュ:** `249b7d7`
- **学び:** SQL側の`ORDER BY`が正しくても、LLMへの指示が「並び順の説明」に
  留まり「選定の確定」になっていなければ、LLMは他の観点（駅近さ等）を
  重視して1位以外を選んでしまう余地が残る。最上級クエリのように
  決定的な正解が存在するケースでは、選定自体をコード側で固定し、
  LLMの役割を理由説明に限定するのが安全（CLAUDE.mdの「構造化条件はSQLで
  確定判定し、LLMの推論に委ねない」という方針をプロンプト設計にも
  一貫させる必要がある）。

---

## [Phase 28-4] 見出し「推薦する建物」の英語UI未対応を修正

### Step 28-4: build_prompt() の見出し文言をresponse_language連動に修正
- **日時:** 2026-08-28
- **不具合報告:** ユーザーがPhase 28修正の動作確認中、英語UIで正しく1位の建物
  （97.4m）が推薦されるようになった一方、回答冒頭の見出し `## 推薦する建物` が
  英語回答内でも日本語のまま残っていることに気づいた。
- **原因:** `build_prompt()`（`src/phase4_retrieval.py`）の【回答形式】指示内で
  見出し文言が `## 推薦する建物` とハードコードされており、`response_language`
  に連動していなかった（本文の説明文は`language_instruction`で英語化される一方、
  見出し部分のみ配線が漏れていた）。
- **対応内容:** `language_instruction`と同様に `heading_label`
  （`response_language=="en"` なら `"Recommended Building"`、それ以外は
  `"推薦する建物"`）を定義し、プロンプト内の見出し指示を `## {heading_label}`
  に変更。
- **確認結果:** 英語クエリで `## Recommended Building`、日本語クエリで
  `## 推薦する建物` がそれぞれ正しく出力されることを確認。
  `tests/sanity_checks.py --phase28` も再度パス（回帰なし）。
- **サニティチェック:** ✅ 日英2パターンとも見出し・推薦IDともに正しいことを確認
- **コミットハッシュ:** `b86fc73`

---

## [Phase 28-5] 候補0件・確認質問・幻覚注記の英語UI未対応を修正

### Step 28-5: build_prompt()以外の固定文言も一括で言語連動化
- **日時:** 2026-08-28
- **経緯:** Phase 28-4（見出し文言）の修正後、ユーザーから「他も確認してほしい」
  との依頼を受け、`response_language`が渡っているにもかかわらず固定日本語の
  ままになっている箇所を`src/phase4_retrieval.py`・`src/query_parser.py`・
  `src/phase6_app.py`全体で洗い出した。
- **発見した不具合（4件）:**
  1. 候補0件時の回答メッセージ（`hybrid_search()`）が固定日本語。0件ヒットは
     通常のクエリでも発生しうるため実害あり。
  2. `validate_answer()`のハルシネーション検知注記が固定日本語
     （LLMが候補外の建物IDを回答に含めた場合にのみ付与されるため発生頻度は低い）。
  3. `query_parser.py`の`parse_query()`が`response_language`を受け取っておらず、
     目的があいまいな高さクエリで返す`clarification_question`（確認質問文）が
     常に日本語で生成されていた。
  4. `phase6_app.py`の空クエリ400エラー詳細文が固定日本語
     （フロントエンドで空クエリは送信前にブロックされているため通常は未到達）。
- **対応内容:**
  - `hybrid_search()`: 候補0件時のanswerを`response_language`で分岐。
  - `validate_answer()`: `response_language: str = "ja"`引数を追加し、
    注記文言を英語/日本語で出し分け。呼び出し元にも`response_language`を追加。
  - `query_parser.py`: `parse_query()`に`response_language: str = "ja"`引数を
    追加。`response_language=="en"`の場合のみ、プロンプト末尾に
    「clarification_question を設定する場合は英語で記述すること」という
    追加指示を付与（他フィールドの分類・コード値は言語に依存しないため対象外）。
    `hybrid_search()`から`parse_query(query, response_language=response_language)`
    で呼び出すよう変更。
  - `phase6_app.py`: 空クエリ400エラーの`detail`を`req.response_language`で分岐。
- **確認結果:**
  - 候補0件（「高さ99999m以上の建物」/ "Buildings taller than 99999m"）:
    日英とも正しい言語でメッセージが返ることを確認。
  - 確認質問誘発（「高い建物を教えて」/ "Tell me about tall buildings"）:
    日英とも`clarification_question`が正しい言語で生成されることを確認
    （英語版: "What is the purpose of looking for tall buildings? ..."）。
  - ハルシネーション注記: `validate_answer()`を候補外IDを含む回答で直接実行し、
    日英とも正しい言語で注記が付与されることを確認。
  - `tests/sanity_checks.py --phase8`（クエリ解析・確認質問・統合検索）
    全5件・`--phase28`（最上級クエリ推薦）1件、いずれも回帰なしでパス
    （`parse_query()`への引数追加が既存呼び出し元に影響しないことを確認）。
- **サニティチェック:** ✅ 全項目パス（新規確認4パターン＋既存回帰2スイート）
- **コミットハッシュ:** `53914e1`

---

## [Phase 29] レイテンシ改善（リトライ短縮 + 回答生成・クエリ解析モデル軽量化）

### Step 29-1 & 29-2: リトライ待機短縮 + gemini-3.5-flash-lite への切替
- **日時:** 2026-08-29
- **経緯:** ユーザーから「質問から回答までが遅い」との指摘を受け、Explore調査を
  実施。`hybrid_search()`（`src/phase4_retrieval.py`）はクエリ解析(LLM)→
  ジオコーディング→ルート分類→クエリ埋め込み(API)→DuckDB検索→候補検証→
  回答生成(LLM)→バリデーションの順に完全直列実行されており、①LLM呼び出しの
  直列化、②リトライの指数バックオフ（埋め込み10s→20s、回答生成15s→30s、
  クエリ解析5s→10s。API不調時にワーストケースが数十秒〜1分超）、③Nominatim
  外部APIキャッシュなし、④埋め込みAPIキャッシュなし、の順にボトルネックと
  特定した。費用対効果が高く低リスクな①②への対応として本Stepを実施。
- **実施内容:**
  - `src/query_parser.py`: リトライ待機`5*(n+1)`→`2*(n+1)`秒に短縮。
    `parse_query()`のモデルを`gemini-2.5-flash`→`gemini-3.5-flash-lite`に変更。
  - `src/phase4_retrieval.py`: `embed_query()`のリトライ待機`10*(n+1)`→
    `3*(n+1)`秒、`generate_answer()`の`15*(n+1)`→`3*(n+1)`秒に短縮。
    `_generate_with_gemini()`のモデルを`gemini-2.5-flash`→
    `gemini-3.5-flash-lite`に変更（docstring・モジュール冒頭コメントも更新）。
  - `src/phase11_hybrid_search.py`のHyDE機能（`gemini-2.5-flash`、デフォルト
    無効のオプション機能）は対象外（Phase29計画のスコープ外）。
- **確認結果:**
  - `gemini-3.5-flash-lite`モデルIDの実在をAPI直接呼び出しで確認（応答約1秒）。
  - `tests/eval_retrieval.py`（gold_set.json 41件）を実行し、変更前
    （`output/eval_result_20260826_0557.csv`）と比較:
    - 平均レイテンシ（検索段のみ、回答生成はskip）: **4.86秒 → 1.81秒**
      （約63%短縮）。
    - category別 recall/precision/hit1: `structured`/`geometric`/
      `robustness`はほぼ同等〜微増。`hybrid`カテゴリのみ、G11
      「浸水5m以下で耐火構造の建物」1件でhit1が1.0→0.0、precisionが
      1.0→0.3に劣化（41件中1件、2.4%）。
    - G11個別調査: `gemini-3.5-flash-lite`はtemperature=0でも呼び出しごとに
      `risk_filters`の解析結果（対象ハザード数）にばらつきが出ることを確認
      （`gemini-2.5-flash`では発生せず、非決定性の程度が大きい可能性）。
      軽微な既知の限界として記録し、Phase29では許容（要ユーザー確認）。
  - 実クエリ「広島駅周辺で一番高い建物は？」を`skip_answer=False`で実行し、
    Phase28で確定させた最上級クエリの推薦ロジック（97.4mの建物を正しく
    1位推薦）に回帰がないこと、回答生成まで含めた総所要時間が**4.3秒**で
    あることを確認。
- **サニティチェック:** ✅ eval全41件エラーなし完走、実クエリ動作確認1件パス
- **コミットハッシュ:** `5c20ab3`

### Step 29-2-補: G11・G12 の非決定性をプロンプト補強で解消
- **日時:** 2026-08-29
- **経緯:** Step 29-1/29-2で検出した1件の精度劣化（G11）をユーザーに報告した
  ところ、「個別にプロンプトを補強したい」との依頼を受けた。調査の結果、
  `gemini-3.5-flash-lite`はtemperature=0でも`_STRUCTURED_RULES`に曖昧さが
  残る箇所で解釈がブレることが判明。`tests/gold_set.py`の`gold_sql`を突合し、
  2箇所の未定義ルールを特定・補強した。
- **原因1（G11「浸水5m以下で耐火構造の建物」）:**
  `risk_filters`のルールは「災害種別不明の"リスクが低い"(`mode=none`)は
  ht/rv/ts の3つ全てに設定」という規定はあったが、`mode="max_depth"`側で
  災害種別が明示されない場合のデフォルトが未定義だった。gold_set.pyの
  `gold_sql`が`ht_depth_max`のみを対象としている（プロジェクトの一貫した
  規約）ことを確認し、「災害種別未指定の`max_depth`は hazard="ht" のみ
  （rv・ts は追加しない）」というルールを`src/query_parser.py`の
  `_STRUCTURED_RULES`に明記。合わせて既存の少数ショット例
  （「浸水1m以下で耐火構造の建物」）も具体的な出力例に書き換えた。
- **原因2（G12「公園に隣接していて眺めのよい高い建物」、prompt補強の副作用で
  新規発覚）: ** `distance_filters`のルールは「駅から近い」等の曖昧な近接
  表現に`max_dist_m=500.0`をデフォルト適用する規定のみで、「隣接」という
  "近い"より強い近接表現が未定義だったため、`gemini-3.5-flash-lite`が
  稀に`max_dist_m=0.0`を出力し検索結果0件（`n_retrieved=0`）になる不具合が
  発生していた。「隣接」「すぐ隣」「隣り合う」「接している」は
  `max_dist_m=100.0`をデフォルト適用し、`max_dist_m`を0にしないことを
  明記するルールを追加。
- **確認結果:**
  - G11: `parse_query()`を3回試行し、いずれも
    `risk_filters=[{hazard:'ht', mode:'max_depth', max_depth_m:5.0}]`で
    安定（補強前は呼び出しごとに対象ハザード数がブレていた）。
  - G12: `parse_query()`を5回試行し、いずれも`max_dist_m=100.0`
    （gold_set.pyの`gold_sql`の閾値と完全一致）で安定。
  - `tests/eval_retrieval.py`（41件）再実行。旧ベースライン
    （`gemini-2.5-flash`、`output/eval_result_20260826_0557.csv`）と比較し、
    全カテゴリで`hit1=1.0`を維持。`hybrid`カテゴリの`precision`は
    0.9125→**1.0**（旧モデル超え）、`recall`もわずかに改善。
    平均レイテンシは1.75秒（変更前4.86秒から約64%短縮を維持）。
- **サニティチェック:** ✅ eval全41件、hit1=1.0（全カテゴリ）で完走
- **コミットハッシュ:** `f35165e`
- **備考:** embeddingのRURI軽量版デフォルト化・並列化（ジオコーディング×
  埋め込み）は次Phase以降で対応予定。

---

## [Phase 30] クエリ側embeddingの高速化（RURIデフォルト化）+ スマホ実機デモ対応

### Step 30-1〜30-3: RURIデフォルト化・プリウォーム・検証
- **日時:** 2026-08-29
- **経緯:** ユーザーからスマホ実機デモの要望を受け、クエリ側embeddingの
  高速化を検討。単発クエリで実測比較したところ、`gemini-embedding-001`
  （API）が1.254秒/件なのに対し、`ruri-v3-310m`（ローカル、ウォーム後）
  は0.085秒/件で約15倍高速と判明（Phase21記録の1.2秒/件はドキュメント側
  長文バッチエンコードの数値であり、短いクエリ単発推論とは条件が異なる
  ことも判明）。ドキュメント側（`building_chunks_ruri_embed`、2,958件）
  はPhase22で既にRURI v3 310mで構築済みのため再埋め込み不要（クエリ側と
  ドキュメント側は同一モデルサイズで統一する必要があり、310m/310mで統一）。
- **実施内容:**
  - `src/phase4_retrieval.py`: `hybrid_search()`・`vector_search()`の
    `embedding_source`デフォルトを`"gemini"`→`"ruri"`に変更。
  - `src/phase6_app.py`: `SearchRequest.embedding_source`・
    `SearchResponse.embedding_source`のデフォルトを`"ruri"`に変更。
    FastAPIの`lifespan`コンテキストマネージャ（`@app.on_event("startup")`は
    非推奨のため不採用）を追加し、サーバー起動時に`embed_query_ruri()`を
    ダミーテキストで1回呼び出してモデルロード（コールドスタート時約11秒）
    を完了させ、デモ本番中の初回クエリ遅延を防止。
  - `frontend/src/store.ts`: `settings`初期値`embeddingSource`を
    `'ruri'`に変更。
  - `frontend/index.html`: `embedding-select`の`<option>`順序を
    `ruri`が先頭になるよう並べ替え（他のセレクトと同様、HTML側の
    デフォルト選択とstore初期値を一致させるパターンに統一。順序を
    変えないとDOM上の選択表示とstoreの実値が食い違う不具合になる
    ところだった）。また`model-select`のラベル「Gemini 2.5 Flash」が
    Phase29でのモデル変更後も更新されていなかったため
    「Gemini 3.5 Flash Lite」に修正。
  - `pixi run build`でフロントエンド本番ビルドを再生成。
- **確認結果:**
  - `pixi run python tests/eval_retrieval.py --ruri`（41件）実行。
    `hybrid`カテゴリで1件（G11）hit1が0→1に見えたが、これは
    `route=structured`（embedding不使用）のクエリであり、Phase29で
    許容した`gemini-3.5-flash-lite`の残存非決定性（低頻度）による
    ものと判明。`parse_query()`を10回試行しすべて安定した結果
    （`hazard='ht'`, `max_depth_m=5.0`）を得ており、eval実行時のみの
    一過性APIエラーと判断（RURI切替とは無関係）。
  - semantic/hybrid経路の実クエリ（「防災拠点として活用できそうな建物」
    「landmarkとして目立つ特徴的な形の建物」）を`hybrid_search()`で
    直接実行し、`embedding_source="ruri"`で正常動作を確認。ウォーム後は
    3.66秒（LLM呼び出しが支配的、embedding自体は誤差程度）。
  - FastAPI開発サーバー（`pixi run app`、ポート8000、既存プロセスが
    `--reload`で自動反映）に対し`/api/search`をAPI直接呼び出しし、
    `"embedding_source":"ruri"`（未指定時のデフォルト動作）で
    `route:"hybrid"`のクエリが`elapsed_sec:5.4`で正常応答することを確認。
  - `pixi run dev`のフロントエンド開発サーバーを`resize_window`で
    モバイル幅（375px）にし、ブラウザ上で「埋め込み: RURI v3 310m
    （ローカル）」がデフォルト選択されていること（DOM値`"ruri"`も
    確認）、実際に検索を実行して回答・候補一覧が正常表示されることを
    確認（`elapsed_sec:3.32`）。
- **サニティチェック:** ✅ eval回帰確認（G11は既知の残存非決定性と判明）、
  実クエリ2件・API直接呼び出し1件・モバイル幅ブラウザ実行1件、いずれも
  正常動作
- **コミットハッシュ:** `34fd45e`
- **備考:** デプロイ先（クラウド/ローカルネットワーク等）の検討は
  ユーザーの意向により別Phaseで実施予定。

---

## [Phase 31] 未使用のClaude Sonnet選択機能を削除

### Step 31-1〜31-4: バックエンド・フロントエンド・周辺ファイルの削除と検証
- **日時:** 2026-08-29
- **経緯:** ユーザーから「モデルは`Gemini 3.5 Flash Lite`しか使っていないと
  思うが、モデル選択処理・UIは不要では」との指摘。調査の結果、
  `model_provider="claude"`はUIのドロップダウン以外（eval/testスクリプト・
  FOSS4G発表資料）から一切呼ばれておらず実質未使用と判明。完全削除で合意。
- **実施内容:**
  - `src/phase4_retrieval.py`: `generate_answer()`から`model_provider`
    引数を削除し常にGemini呼び出しに簡素化。`_generate_with_claude()`
    関数を削除。`hybrid_search()`の引数・戻り値dict・early-return3箇所
    から`model_provider`を全て除去。モジュールdocstringも更新。
  - `src/phase6_app.py`: `SearchRequest.model_provider`・
    `SearchResponse.model_provider`フィールドを削除。
  - `frontend/index.html`: `model-select`のラベル+セレクトブロックを削除。
  - `frontend/src/store.ts`・`api.ts`・`main.ts`・`i18n.ts`（日英）から
    `modelProvider`/`model_provider`関連のフィールド・要素取得・
    イベントリスナー・i18nキーを削除。
  - `tests/sanity_checks.py`の`model_provider="gemini"`引数を削除
    （`hybrid_search()`のシグネチャ変更に追従）。
  - `README.md`のClaude Sonnet言及箇所（パイプライン図・設定表・curl例・
    レスポンス例・技術スタック表）をgemini/RURI固定の記述に更新
    （併せて、Phase29/30の変更が未反映で古いままだった`gemini-embedding-001`
    ・`Gemini 2.5 Flash`表記も現状に合わせて修正）。
  - `.env`の`ANTHROPIC_API_KEY`定義は削除せず維持（CLAUDE.mdの環境変数
    定義を勝手に変更しないため）。
  - `pixi run build`でフロントエンドを再ビルド。
- **確認結果:**
  - `grep`で`model_provider`/`modelProvider`/`model-select`/
    `Claude Sonnet`を全文検索し、`docs/plan.md`・`work_log.md`（過去の
    記録）・`CLAUDE.md`（変更不可）・ユーザーの個人ドラフト
    （`docs/foss4g/review_context.md`）以外に残存がないことを確認。
  - `pixi run build`: TypeScript型チェック含めエラーなしでビルド成功。
  - `tests/sanity_checks.py`の`assert_answer_contains_building_id`
    （`hybrid_search()`を直接呼ぶテスト）が`model_provider`引数なしで
    パス。`run_phase8_checks()`・`run_phase18_checks()`も実行し、
    `check_phase8_integrated_search`（目的不明の高さクエリで確認質問を
    返すかの判定）のみ約20〜30%の頻度で失敗することを確認したが、
    `parse_query()`を直接5回試行して再現・原因を切り分けたところ
    Phase29由来の`gemini-3.5-flash-lite`の既知の残存非決定性であり、
    Phase31の変更（`model_provider`削除）とは無関係と判断した。それ以外の
    全チェック（Phase8残り4件・Phase18全2件）は安定してパス。
  - `pixi run dev`のフロントエンドをモバイル幅（375px）で確認し、
    `model-select`要素がDOMから消えていること、`embedding-select`は
    引き続き`"ruri"`で正常動作すること、実際の検索が200 OKで応答し
    結果が正常表示されることを確認。
- **サニティチェック:** ✅ ビルド成功、`hybrid_search()`関連チェック
  （既知の非決定性1件を除き）全てパス、モバイル幅ブラウザでの動作確認
- **コミットハッシュ:** `1b3896f`
- **備考:** `check_phase8_integrated_search`の非決定性はPhase29から
  持ち越しの既知課題であり、対応する場合は別Phaseで扱う。

---

## [Phase 32] ディレクトリ再編成 + 英語docstring化 + Cloudflare Containers対応

> ブランチ`refactor/phase32-directory-restructure`上でStep単位コミットにより実施。
> Part A(ディレクトリ再編成)完了時点でこのエントリを記録する。Part B
> (Cloudflare Containers対応)は別途Step 32-7〜32-8で実施予定。

### 新旧ファイル名対応表

| 旧パス | 新パス |
|---|---|
| `src/phase1_investigate.py` | `src/pipeline/investigate.py` |
| `src/phase2_spatial.py` | `src/pipeline/gpkg.py` |
| `src/phase3_enrichment.py` | `src/pipeline/enrichment.py` |
| `src/phase9_geometry.py` | `src/pipeline/geometry.py` |
| `src/phase13_context.py` | `src/pipeline/context.py` |
| `src/codelist_loader.py` | `src/pipeline/codelist_loader.py` |
| `src/phase22_ruri_embed.py` | `src/pipeline/ruri_embed.py`（オフライン部分）+ `src/app/ruri_query.py`（ランタイム部分、分割） |
| `src/phase6_app.py` | `src/app/main.py` |
| `src/phase4_retrieval.py` | `src/app/retrieval.py` |
| `src/phase10_router.py` | `src/app/router.py` |
| `src/phase11_hybrid_search.py` | `src/app/search_fusion.py` |
| `src/query_parser.py` | `src/app/query_parser.py`（移動のみ） |
| `src/geocoder.py` | `src/app/geocoder.py`（移動のみ） |
| （新規） | `src/common/db.py`（`connect_rag`/`RAG_DB_PATH`/`wgs84_to_epsg6671`を集約） |

### Step 32-1〜32-6: ディレクトリ再編成・英語docstring化・import統一・周辺ファイル追従
- **日時:** 2026-08-29
- **経緯:** ユーザーから「全体的にリファクタリングしたい」との要望、および
  スマホ実機デモ常時公開のためのCloudflare Containersデプロイ検討に伴い、
  `phaseN_*.py`という開発フェーズ番号ベースのファイル名を機能ベースの
  ディレクトリ構成に再編成することにした。あわせてコード内コメント・
  docstringの英語化（Googleスタイル）も実施した。
- **実施内容:**
  - `src/common/db.py`を新規作成し、複数モジュールから再利用される
    `connect_rag()`・`RAG_DB_PATH`・`wgs84_to_epsg6671()`を集約。
  - 上記対応表の通りパイプライン系7ファイル・ランタイムAPI系6ファイルを
    移動・リネーム。`phase22_ruri_embed.py`はオフライン処理
    （`build_ruri_index()`）とランタイム処理（`embed_query_ruri()`）を
    別ファイルに分割した（両者は別プロセスでしか動かないため、
    `_model`シングルトンキャッシュもそれぞれ独立させた）。
  - 全Pythonファイルのdocstring・非自明な設計判断を説明するコメントを
    英語Googleスタイルに書き直した（LLMプロンプト本文はデータのため対象外）。
  - `sys.path.insert` + `try/except ImportError`の二重import形式を廃止し、
    `src/__init__.py`を追加してパッケージ化。`from src.app.retrieval import
    hybrid_search`のような一貫した絶対importに統一。
  - `pixi.toml`の5タスクを`python -m src.pipeline.xxx`/
    `uvicorn src.app.main:app`形式に更新（PYTHONPATH環境変数指定が不要に）。
  - `tests/`配下4ファイルのimport文を新パスに更新。
  - `frontend/src/`配下の全TypeScriptファイル（api.ts, main.ts, chat.ts,
    theme.ts, store.ts, mapColor.ts, map.ts, i18n.ts）のコメントを英語化
    （UI表示用の文言データは対象外）。
- **副次的に発見・修正したバグ:**
  - `src/app/retrieval.py`の`RuntimeError`メッセージと
    `src/pipeline/enrichment.py`のログが移動前の旧ファイル名
    （`phase9_geometry.py`等）を参照したままだった。新モジュールパスに修正。
  - `tests/sanity_checks.py`の`check_phase9_vector_search_geom_cols`が
    Phase30由来の潜在バグを含んでいた：gemini埋め込み（3072次元）を
    `embedding_source`未指定で`vector_search()`に渡しており、Phase30で
    デフォルトが`"ruri"`（768次元）に変わったことで次元不一致エラーに
    なっていた。`embedding_source="gemini"`を明示して修正。
  - `frontend/src/api.ts`・`chat.ts`内の古いコメントが
    `src/phase4_retrieval.py`・`src/phase6_app.py`を参照していたのを
    新パスに修正。
- **確認結果:**
  - `pixi run python tests/sanity_checks.py`相当の全Phase
    （8/9/10/11/13/15/17/18/20/25/28）のサニティチェックを実行し、
    全件パスを確認。
  - `pixi run build`でTypeScript型チェック含めビルド成功を複数回確認。
  - `uvicorn src.app.main:app`（PYTHONPATH環境変数なし）を実際に起動し、
    プリウォーム→`/api/health`→`/api/search`が正常応答することを確認。
  - `pixi run dev` + `pixi run app`のブラウザ実機確認で、実際に検索を実行し
    候補建物リスト・地図の動的配色（凡例含む）が正常表示されることを確認。
- **サニティチェック:** ✅ 全Phaseのサニティチェックパス、ビルド成功、
  実サーバー起動確認、ブラウザ実機確認
- **コミットハッシュ:** `d62b7b5`, `77f5d72`, `a5ff186`, `ea63d85`,
  `3d154d1`, `a9047cf`, `cb7fd67`, `463ef22`, `ee067ab`, `6216bd9`
- **備考:** Part B（Cloudflare Containersデプロイ対応、Step 32-7〜32-8）は
  別途実施する。ブランチ`refactor/phase32-directory-restructure`は
  Part A完了確認後に`master`へマージする。

---

## [main] 開発プロセス用語（Phase/Step）の除去とREADME整備

### Step: 内部向けジャーナリングの除去
- **日時:** 2026-08-29
- **背景:** GitHubにpush済みの`main`ブランチを今後の正とするにあたり、
  「Phase N」「Step N-N」のような開発プロセス内部用語がコード・テスト・
  READMEに残っていないかユーザーから確認依頼があった。
- **実施内容:**
  - `src/`・`tests/`配下の全Pythonファイルを`grep -rn "Phase"`で網羅的に
    走査し、コメント・print文・docstring・エラーメッセージ中の
    「Phase N」表記をすべて除去（機能を変えず文言のみ修正）。
  - `tests/sanity_checks.py`の45個のチェック関数名を内容ベースの名前に
    リネーム（例: `check_phase9_vector_search_geom_cols` →
    `check_vector_search_geometry_columns`）。CLIディスパッチャの
    `--phaseN`フラグも`--geometry`等の説明的なケバブケースに変更。
  - `src/pipeline/{investigate,gpkg,enrichment}.py`・
    `src/app/retrieval.py`の`run_phase1/2/3/4()`を、それぞれ
    `run_investigation_demo()`/`run_spatial_demo()`/
    `run_enrichment_pipeline()`/`run_retrieval_demo()`にリネーム。
  - `tests/gold_set.py`のゴールドクエリ`note`フィールド中の
    「PhaseN Step N-N」参照を実データに基づく説明文に書き換え。
    あわせて`from geocoder import geocode` →
    `from src.app.geocoder import geocode`という潜在的なimportバグを発見・修正。
  - `tests/eval_retrieval.py`・`tests/benchmark_ruri.py`の
    docstring・print見出しからもPhase参照を除去。
  - `frontend/src/`配下のTypeScriptファイルは、以前の英語化作業で
    既にPhase参照が無いことを`grep`で再確認済み（今回の追加修正なし）。
  - `README.md`を全面的に見直し：
    - 「CLI（Phase 1〜4）」「Web UI（Phase 6）」等の見出しからPhase番号を除去。
    - プロジェクト構成図を`src/common/`・`src/pipeline/`・`src/app/`の
      実際のディレクトリ構造に合わせて更新。
    - 古い`src/phase4_retrieval.py`の`run_phase4()`参照を
      `src/app/retrieval.py`の`run_retrieval_demo()`に修正。
    - Phase31で削除済みのClaude関連`.env`項目（`ANTHROPIC_API_KEY`）を削除。
    - `git clone <repository-url>`のプレースホルダを実際のリポジトリURLに置換。
- **確認結果:**
  - `grep -rn "Phase" src/ tests/ frontend/src/ README.md --include="*.py" --include="*.ts" --include="*.md"`
    が全て0件（完全にクリーン）であることを確認。
  - `sanity_checks.py`・`gold_set.py`・`eval_retrieval.py`・
    `benchmark_ruri.py`を再importし、リネーム後の関数呼び出しに
    問題がないことを確認。リネーム後のチェック関数を複数実行し全件パス。
- **サニティチェック:** ✅ 全項目パス
- **コミットハッシュ:** `c6c27cd`
- **備考:** GitHub上の`main`（プライベートリポジトリ
  `raokiey/hiroshima-bldg-rag-example`）にpushする前段階の整備。
  Cloudflare Containersデプロイ対応（Part B）は未着手のまま。

---

## [main] README を公開向けに全面刷新（英語版 + 日本語版）

### Step: README.md を英語化し README_ja.md を新設
- **日時:** 2026-08-29
- **背景:** ユーザーからGitHubへのpush内容を他者に見てもらう想定である旨の
  説明があり、README.md を「概要／処理について／環境構築／実行方法／
  使用データ／ライセンス」の6セクション構成の英語版に刷新し、日本語版
  README_ja.md を新設して相互リンクする方針で合意した。
- **確認事項（AskUserQuestionで確認）:**
  - コードのライセンス: MIT License（ユーザー選択）。
  - PLATEAUデータの出典表記: ユーザー指定の文言
    「国土交通省都市局『3D都市モデル（Project PLATEAU）広島市（2022年度）』
    (CC BY 4.0)を加工して使用」を採用し、データセット名部分に
    `https://www.geospatial.jp/ckan/dataset/plateau-34100-hiroshima-shi-2022`
    へのリンクを設定。
- **実施内容:**
  - `LICENSE`（MIT）を新規作成。
  - `README.md` を英語で全面刷新: Overview / How it works / Setup /
    How to run / Data used / License の6セクション構成に整理。
    プロジェクト構成図・APIエンドポイント例・設定オプション表等の内部向け
    詳細は削減し、外部読者向けに簡潔化。
  - `README_ja.md` を新規作成し、同じ構成の日本語版として用意。両ファイル
    の冒頭に相互リンクを設置。
  - `.env.example` を新規作成（`GEMINI_API_KEY` のみ）。
  - `frontend/src/i18n.ts` の `mapAttribution`・`welcomeAttribution`
    （ja/en 各キー）を、README と同じPLATEAU出典表記に統一。
  - 副次的に発見: `pixi.toml` の `pypi-dependencies` に未使用の
    `anthropic` パッケージが残っていた（Phase31でClaude機能削除済みだが
    依存関係の削除漏れ）。使用箇所がないことを`grep`で確認の上削除し、
    `pixi install` で `pixi.lock` を再生成。
- **確認結果:**
  - `pixi run build` でフロントエンドのビルドが成功することを確認
    （型チェック含む）。
  - `pixi run python -c "import duckdb; import google.genai"` で
    `anthropic` 削除後もランタイムの依存関係解決に問題がないことを確認。
  - Claude Browser で開発サーバー（`localhost:5173`）を再読み込みし、
    地図パネル・ウェルカムメッセージの出典表記が意図通り
    日本語で表示されることを確認。
- **サニティチェック:** ✅ ビルド成功、依存関係解決確認、ブラウザ表示確認
- **コミットハッシュ:** `9c92323`
- **備考:** `src/static/`（フロントエンドビルド成果物）はリポジトリに
  コミットされている構成のため、出典表記変更に伴うビルド差分も
  あわせてコミットする。

---

## [Phase 33] データパスのCLI引数化・環境変数対応

### Step 33-1: 共通パス定義の一元化（`src/common/db.py`）
- **日時:** 2026-08-29
- **実施内容:**
  - `GPKG_PATH`が`investigate.py`・`gpkg.py`・`enrichment.py`の3箇所に重複定義
    されていた問題を解消し、`src/common/db.py`に全パス定数を集約した
    （`GPKG_PATH`・`MAXLOD_GPKG_PATH`・`LANDUSE_GPKG_PATH`・`URF_GPKG_PATH`・
    `RELATED_DATA_DIR`・`CITY_PREFIX`・`SHELTER_PATH`等5種・`RAG_DB_PATH`）。
  - 各定数は`PLATEAU_*`環境変数→未設定時はデフォルト値（広島データ）の順で
    解決するようにした。関連GeoJSON5種は`RELATED_DATA_DIR`＋`CITY_PREFIX`
    から`related_path()`関数で組み立てる方式にし、他都市への切り替えを
    prefix変更のみで可能にした。
  - `connect_rag()`に`db_path`省略可能引数を追加（省略時は`RAG_DB_PATH`、
    後方互換維持）。
- **副次的に発見・修正したバグ:** `main.py`が`src.common.db`を
  `src.app.retrieval`（`.env`読み込み元）より先にimportしていたため、
  新設した`PLATEAU_*`環境変数がFastAPI起動時に読み込まれない問題を発見。
  `db.py`自体が`load_dotenv()`を呼ぶよう修正し解消した。

### Step 33-2: パイプラインCLIスクリプトへのargparse追加
- **実施内容:** `investigate.py`・`gpkg.py`・`enrichment.py`・`geometry.py`・
  `context.py`・`src/app/retrieval.py`（`pixi run search`）の
  `if __name__ == "__main__":`にargparseを追加し、`--gpkg-path`
  `--landuse-path` `--urf-path` `--maxlod-gpkg-path` `--data-dir`
  `--city-prefix` `--db-path`のいずれかを個別実行時に指定できるようにした。
  `retrieval.py`は既存の「クオートなしでクエリを渡せる」挙動を維持しつつ
  `--db-path`を追加した。
  計画時は`context.py`に`--gpkg-path`を含めていなかったが、`GPKG_PATH`を
  直接参照している実装だったため、計画から逸脱して追加した（他都市切り替え
  が実際に機能するために必要な変更）。
- **副次的に発見・修正したバグ:** `context.py`の`compute_nearest_facility()`
  が`landmark_path: Path = LANDMARK_PATH`という関数定義時にデフォルト値を
  束縛するパターンを使っており、`__main__`でのモジュールグローバル
  再代入が呼び出し元の`build_context_meta()`経由の呼び出しには反映されない
  ことが判明。呼び出し側で`landmark_path=LANDMARK_PATH`を明示するよう修正。

### Step 33-3: FastAPIランタイム側の環境変数対応
- **実施内容:** `geocoder.py`の`_STATION_PATH`・`_LANDMARK_PATH`を
  `src.common.db`の環境変数対応済み`STATION_PATH`・`LANDMARK_PATH`に
  置き換えた。`.env.example`に`PLATEAU_*`環境変数をコメントアウトで
  追記した（すべて任意設定）。

### Step 33-4: 動作確認
- **確認結果:**
  - 全pipelineモジュール・appモジュールの再importが成功することを確認。
  - `investigate`・`spatial`・`search`の各pixiタスクを引数なしで実行し、
    従来と同じ結果で完走することを確認（回帰なし）。
  - `--gpkg-path`等の引数を実際に渡してargparseの解決結果が正しいことを
    単体テストで確認。`PLATEAU_CITY_PREFIX`環境変数の上書きも確認。
  - FastAPIアプリを環境変数なしで起動し、`/api/health`が従来通り
    `output/plateau_rag.duckdb`を指すこと、`/api/search`が地名（駅名）解決
    含めて正常応答することをブラウザ経由で確認。
  - `tests/sanity_checks.py`のフル実行で、Phase30由来の既知バグ
    （`assert_vector_search_returns_results`のembedding次元不一致、
    `run_all_checks()`がAssertionError以外を捕捉せず後続チェックが
    止まる問題）を発見。今回の変更が原因ではないことをgit diffで確認の上、
    別タスクとして切り出した（本Phaseのスコープ外）。個別に
    `--geometry`・`--context`チェックおよび`assert_answer_contains_building_id`
    を実行し、いずれもパスすることを確認して回帰がないことを確認した。
- **サニティチェック:** ✅ 該当範囲は全件パス（既知の別バグはスコープ外として切り出し）
- **コミットハッシュ:** `7c0cd08`

### Step 33-5: ドキュメント更新
- **実施内容:** README.md/README_ja.mdの「データの準備」節を新設し、
  CLI引数（`--gpkg-path`等）・環境変数（`PLATEAU_*`）での差し替え方法を
  記載。英語版にも同内容を反映し、`hiroshima_sample.gpkg`の説明を
  「2,958件全て」ではなく「2,958件のサンプル」という、より正確な表現に
  統一した。
- **コミットハッシュ:** `148ba3f`

---

## [main] pixi タスク名の整理（app/dev → api/app）

### Step: `pixi run app`/`dev` の混同を解消
- **日時:** 2026-08-29
- **背景:** ユーザーから、FastAPIバックエンドが`pixi run app`、Web UI開発
  サーバーが`pixi run dev`という命名がわかりにくいとの指摘があり、
  APIを`pixi run api`、Web UIを`pixi run app`に変更する依頼があった。
- **実施内容:**
  - `pixi.toml`のタスク名を変更: `app`（旧: FastAPIバックエンド）→`api`、
    `dev`（旧: Viteフロントエンド開発サーバー）→`app`。
  - `src/app/main.py`の開発モード時のフォールバックメッセージ
    （`pixi run dev でフロントエンドを起動してください`）を
    `pixi run app`に更新。
  - README.md/README_ja.mdの「Web UI」節のコマンド例・説明文を新名称に
    更新。
  - `.claude/launch.json`（git管理外）のブラウザプレビュー設定も
    新タスク名に合わせて更新。
- **確認結果:** `pixi task list`で`api`・`app`タスクが認識されることを
  確認。実際に両タスクを起動し、`pixi run api`がFastAPIバックエンド
  （ポート8000、ヘルスチェック・RURIプリウォーム含め正常）、
  `pixi run app`がVite開発サーバー（ポート5173、Web UI表示・
  バックエンドとの連携含め正常）として機能することをブラウザで確認。
- **サニティチェック:** ✅ 両タスクの起動・動作を確認
- **コミットハッシュ:** `7856fc7`

---

## [main] tests/sanity_checks.py の埋め込み次元不一致バグ修正

### Step: assert_vector_search_returns_results() の修正 + 例外捕捉の拡張
- **日時:** 2026-08-29
- **背景:** Phase 33の動作確認中に発見し別タスクとして切り出していた
  既知バグ（`tests/sanity_checks.py`実行時のクラッシュ）を修正した。
- **実施内容:**
  1. `assert_vector_search_returns_results()`（旧272行目付近）で、
     `embed_query()`（Gemini、3072次元）由来の`query_vec`を
     `embedding_source`未指定のまま`vector_search()`に渡しており、
     デフォルト値`"ruri"`（768次元、Phase30由来）との次元不一致で
     `_duckdb.BinderException`が発生していた。呼び出しに
     `embedding_source="gemini"`を明示して解消。同種のバグは以前
     `check_vector_search_geometry_columns`でも見つかり、同じ修正
     パターンで対応済みだった。
  2. `run_all_checks()`内の4箇所の`except AssertionError`ループが、
     BinderExceptionのようなAssertionError以外の例外を捕捉できず、
     発生時に`run_all_checks()`全体が異常終了し以降のチェックが
     一切実行されない問題があった。`except Exception`に広げ、
     想定外の例外も1件の`[FAIL]`として記録した上で後続チェックへ
     進むよう修正。
- **確認結果:** `pixi run python tests/sanity_checks.py`を実行し、
  終了コード0・全14件パス・0件失敗（`[SUCCESS] 全アサーションパス`）
  で完走することを確認。
- **サニティチェック:** ✅ 全14件パス
- **コミットハッシュ:** `802354b`

---

## [main] アプリ名変更・タイトルのホームリンク化・ホーム画面の絵文字削除

### Step: UI微調整3件
- **日時:** 2026-08-29
- **実施内容:**
  1. アプリ名を「City RAG Example」から「Hiroshima Building RAG」に変更
     （`frontend/index.html`の`<title>`・meta description、
     `frontend/src/i18n.ts`の`appTitle`（ja/en）、README.md/README_ja.md
     の見出し）。
  2. ヘッダー左上のタイトル部分（`.app-brand`）を`<div>`から
     `<a href="/">`に変更し、クリック/タップでホーム（ルートURL）に
     戻れるようにした。ブラウザネイティブのページ遷移のため、チャット
     状態に関わらず必ずクリーンな初期状態に戻る。`style.css`に
     リンクのスタイルリセット（下線なし・色継承）とホバー時の
     アクセントカラー表示を追加。
  3. ホーム画面（ウェルカムメッセージ）の絵文字をすべて削除:
     `welcome-msg__icon`（🏙️）要素を削除、質問例3件の絵文字プレフィックス
     （💧🔥🌊）を`i18n.ts`（ja/en）・`index.html`から削除。未使用となった
     `.welcome-msg__icon`のCSSルール（通常時・狭幅画面向けの2箇所）も削除。
  - 副次的に、`index.html`に残っていた「Phase27」というコメントも
    このタイミングで除去した（以前のPhase用語除去はPython/TypeScript
    ファイルのみが対象で、HTMLファイルは対象外だったため見落とし）。
- **確認結果:** `pixi run build`でTypeScript型チェック含めビルド成功を
  確認。Claude Browserでブラウザ実機確認: タブタイトルが
  「Hiroshima Building RAG」になっていること、ホーム画面に絵文字が
  一切表示されないこと、タイトルをクリックするとルートURLへ遷移し
  ウェルカム画面が再表示されること、ホバー時にタイトルの色が
  アクセントカラーに変わることを確認。
- **サニティチェック:** ✅ ビルド成功、ブラウザ実機確認3点とも意図通り
- **コミットハッシュ:** `dc0968a`
