# CLAUDE.md — PLATEAU Semantic 3D-Geospatial RAG

> このファイルは、Claude Code / Codex などの AI コーディングエージェントが本プロジェクトを正しく理解・実行するための **唯一の信頼できる情報源（Single Source of Truth）** です。
> コーディングを開始する前に必ずこのファイルを全文読み込み、内容に従ってください。

---

## 0. プロジェクト概要

Project PLATEAU の LOD2 建物データ（広島市）と災害リスク拡張属性を組み合わせた、**地理空間セマンティック RAG プロトタイプ**を構築する。
「広島市内の高潮リスクが低く、西日の当たらない建物は？」のような自然言語クエリに、空間演算 × ベクトル検索 × LLM 推論で回答することを最終ゴールとする。

---

## 1. 絶対ルール（Breaking these is a critical failure）

以下のルールはいかなる場合も破ってはならない。

| # | ルール |
|---|--------|
| R-01 | **回答・コメント・ログはすべて日本語で記述する** |
| R-02 | データは `./data/` のみを参照する。外部からデータをダウンロードしない |
| R-03 | データ仕様書 `./docs/specification.pdf` を必ず確認してからコードを書く |
| R-04 | コードを書く前に **3層構造の設計（Phase > Step > TODO）** を必ず作成する |
| R-05 | 設計は **plan モード**で行い、ユーザーに確認・承認を得てから実装に移る |
| R-06 | 不明点はデータ仕様書・データ本体を確認し、それでも解決しない場合は**必ずユーザーに質問する** |
| R-07 | TODO 単位で実装・確認、Step 単位でテストし、問題がなければ git commit する |
| R-08 | 各 Step に適切なコメントを付与する |
| R-09 | `./docs/work_log.md` に Step ごとの作業内容とコミットハッシュを記録する |
| R-10 | 不具合発生時は `work_log.md` を参照し、**不具合発生前の Step まで戻ってゼロベースで再設計**する |
| R-11 | APIキー等の秘匿情報は `.env` に記載し、コードに直接書かない |

---

## 2. 技術スタック

| 役割 | 採用技術 |
|------|----------|
| パッケージ管理 | **pixi** (`pixi.toml`) |
| データベース | **DuckDB** (extensions: `spatial`, `vss`) |
| 空間データ入力 | GeoPackage (`hiroshima_sample.gpkg`) / EPSG:6671 |
| テキスト要約 | Gemini 2.5 Flash |
| 埋め込み生成 | Google `text-embedding-004`（768次元、`google-genai` SDK） |
| 推論・回答生成 | Claude Sonnet 4.5 / Gemini 2.5 Pro |
| LLM 連携 | Python (`anthropic`, `google-genai`) |
| 高速データ連携 | `pyarrow`（DuckDB ↔ Python のゼロコピー） |
| 環境変数管理 | `python-dotenv` (`.env` ファイル) |

---

## 3. ディレクトリ構成

```
project-root/
├── CLAUDE.md              # このファイル（変更不可）
├── pixi.toml              # パッケージ定義
├── .env                   # APIキー等（git管理外）
├── .gitignore
│
├── data/                  # 入力データ（読み取り専用扱い）
│   └── hiroshima_sample.gpkg
│
├── docs/
│   ├── specification.pdf  # データ仕様書（実装前に必読）
│   └── work_log.md        # 作業ログ（Step完了ごとに更新）
│
├── src/                   # メインソースコード
│   ├── phase1_investigate.py
│   ├── phase2_spatial.py
│   ├── phase3_enrichment.py
│   └── phase4_retrieval.py
│
├── output/                # 中間生成物・出力ファイル
│   ├── plateau_rag.duckdb # DuckDB 永続化ファイル
│   └── logs/
│
└── tests/                 # サニティチェック・テストスクリプト
    └── sanity_checks.py
```

> `data/` と `docs/specification.pdf` は**読み取り専用**として扱い、上書き・削除をしない。

---

## 4. 実装フェーズ定義（3層構造テンプレート）

コードを書く前に、必ず以下の形式で計画を作成しユーザーに提示すること。
承認された計画は、必ず、`./docs/plan.md`に保存すること。  

```
## Phase X: <フェーズ名>
### Step X-1: <ステップ名>
  - TODO X-1-1: <具体的な作業>
  - TODO X-1-2: <具体的な作業>
### Step X-2: <ステップ名>
  - TODO X-2-1: <具体的な作業>
```

### 現在定義されているフェーズ

| Phase | 名称 | 概要 |
|-------|------|------|
| 1 | データ構造精査 | DuckDB で GPKG のテーブル構成を調べ、Building と Risk 属性の紐付けを確認 |
| 2 | 空間演算実装 | WGS84 → EPSG:6671 変換、`ST_DWithin` によるメートル範囲検索 |
| 3 | セマンティック・チャンク化 | JOIN で属性カルテを生成し、Embedding を作成・保存 |
| 4 | ハイブリッド検索構築 | 空間フィルタ × ベクトル検索 × LLM 回答生成 |

---

## 5. テスト基準・サニティチェック

Step 完了後に必ず以下を確認し、`tests/sanity_checks.py` に関数として実装すること。

### Phase 1
- [ ] `st_layers()` でテーブル一覧が取得できる
- [ ] `bldg:Building` テーブルの件数が 0 件でない
- [ ] `parentId` による LEFT JOIN 結果が 0 件でない（紐付きが存在する）
- [ ] `depth`, `rank`, `description` カラムが期待通り存在する

### Phase 2
- [ ] 変換後の座標が EPSG:6671 の妥当範囲内（広島市周辺）に収まっている
- [ ] `ST_DWithin` の結果件数が入力半径に応じて増減する（回帰確認）

### Phase 3
- [ ] 生成された属性カルテのテキスト長が空でない
- [ ] Embedding のベクトル次元数が期待値と一致する
- [ ] DuckDB への保存後、件数が入力レコード数と一致する

### Phase 4
- [ ] ハイブリッド検索が少なくとも 1 件以上の結果を返す
- [ ] LLM の回答に建物 ID または座標情報が含まれている

> **原則:** アサーションが 1 つでも失敗した場合は次の Step に進まない。

---

## 6. エラーハンドリング方針

| 状況 | 対応 |
|------|------|
| CRS 不一致エラー | 変換前に CRS を `ST_SRID()` で確認してからリトライ |
| 外部 API タイムアウト | 最大 3 回リトライ、それ以降は処理を中断しユーザーに報告 |
| JOIN 結果 0 件 | `work_log.md` に記録後、Phase 1 まで戻り JOIN キーを再確認 |
| DuckDB extension ロード失敗 | インストールコマンドをログに出力し、ユーザーに手動対応を依頼 |

---

## 7. git コミット規則

```
<type>(<phase>): <日本語の概要>

例:
feat(phase1): DuckDB でテーブル一覧取得を実装
fix(phase2): CRS 変換のパラメータを修正
test(phase1): サニティチェック関数を追加
docs: work_log.md を Step 1-2 まで更新
```

- **1 Step = 1 commit** を原則とする
- テスト通過前にコミットしない

---

## 8. work_log.md テンプレート

`./docs/work_log.md` には以下のフォーマットで記録する。

```markdown
# 作業ログ — PLATEAU Semantic RAG

## [Phase 1] データ構造精査

### Step 1-1: テーブル一覧取得
- **日時:** YYYY-MM-DD HH:MM
- **実施内容:** DuckDB の `st_layers()` で全テーブル名を取得した。
- **確認結果:** `bldg:Building` 他 XX テーブルを確認。JOIN キー `parentId` の存在を確認。
- **サニティチェック:** ✅ 全項目パス
- **コミットハッシュ:** `abc1234`
- **備考:** `uro:HighTideRiskAttribute` に `depth` カラムあり、仕様書 p.XX と一致。

---

### Step 1-2: JOIN 検証
...

## 不具合ログ

### [2026-XX-XX] Phase 2 CRS 変換エラー
- **現象:** ST_Transform でエラー発生
- **戻り先:** Step 2-1 から再設計
- **原因:** ...
- **解決策:** ...
```

---

## 9. 環境変数（.env）

`.env` ファイルに以下を定義する。コードには直接書かない。

```
ANTHROPIC_API_KEY=your_anthropic_api_key
GEMINI_API_KEY=your_gemini_api_key
```

- `ANTHROPIC_API_KEY` — Claude Sonnet（Phase 4 回答生成）に使用
- `GEMINI_API_KEY` — `text-embedding-004`（Phase 3 埋め込み）および Gemini 2.5 Flash/Pro（Phase 3/4）に使用
  - `google-genai` SDK は環境変数 `GEMINI_API_KEY` を自動参照する

`.gitignore` に必ず含めること：

```
.env
output/plateau_rag.duckdb
output/logs/
__pycache__/
.pixi/
```

---

## 10. pixi コマンドの実行方法（重要）

このプロジェクトは **pixi** でパッケージ管理している。
Claude Code のシェル環境（bash on Windows）では `pixi` が PATH に存在しないため、
**必ずフルパスを指定して実行すること。**

```bash
# Python スクリプトの実行
/c/Users/pikkarin/AppData/Local/pixi/bin/pixi.exe run python <script.py>

# 例: サニティチェックの実行
/c/Users/pikkarin/AppData/Local/pixi/bin/pixi.exe run python tests/sanity_checks.py

# 例: 1行コマンドの実行
/c/Users/pikkarin/AppData/Local/pixi/bin/pixi.exe run python -c "import duckdb; print(duckdb.__version__)"
```

> **注意:**
> - `pixi run python` は `.pixi/envs/default/python.exe` を直接呼び出す方法でも動作するが、
>   pixi タスクやアクティベーションスクリプトが必要な場合は `pixi.exe run` を使用すること。
> - `pixi` が PATH に通っていないことを確認したうえで、上記フルパスを使うこと。

---

## 11. 開始手順（エージェントへの初回指示）

1. `./docs/specification.pdf` を読み込み、テーブル定義・カラム仕様を把握する
2. `./data/hiroshima_sample.gpkg` のファイルサイズと存在を確認する
3. Phase 1 の **3層構造設計（Phase > Step > TODO）** を作成し、ユーザーに提示する
4. ユーザーの承認を得てから実装を開始する
