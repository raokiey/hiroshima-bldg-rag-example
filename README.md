# PLATEAU Semantic 3D-Geospatial RAG

広島市の PLATEAU LOD2 建物データと災害リスク拡張属性を組み合わせた、**地理空間セマンティック RAG プロトタイプ**。

「広島市内の高潮リスクが低く、駅から近い建物は？」のような自然言語クエリに、空間演算 × ベクトル検索 × LLM 推論で回答する。

---

## アーキテクチャ

```
[自然言語クエリ] + [オプション: 緯度経度・半径]
         │
         ▼
  ① RURI v3 310m 埋め込み（ローカル推論）
    (768 次元 / gemini-embedding-001 に切り替え可)
         │
         ▼
  ② DuckDB HNSW ベクトル検索
    + ST_DWithin 空間フィルタ（オプション）
         │
         ▼
  ③ LLM 回答生成
    (Gemini 3.5 Flash Lite)
         │
         ▼
  [推薦建物リスト + 選定理由テキスト]
    ↕  REST API (FastAPI)
  [チャット UI + MapLibre GL JS 地図可視化]
```

### データソース

| 種別 | ファイル | 内容 |
|------|---------|------|
| 建物・リスク属性 | `data/hiroshima_sample.gpkg` | LOD2 建物 2,958 件・高潮/洪水/津波リスク |
| 土地利用 | `data/hiroshima_landuse.gpkg` | PLATEAU 土地利用ゾーン |
| 都市計画 | `data/hiroshima_urf.gpkg` | 用途地域（UseDistrict など） |
| コードリスト | `data/codelists/` | 属性コード → 日本語ラベル変換用 XML |
| 避難施設 | `data/related/shelter.geojson` | 広島市指定避難所 |
| 鉄道駅 | `data/related/station.geojson` | 広島市内駅・路線情報 |
| 緊急輸送道路 | `data/related/emergency_route.geojson` | 広島市緊急輸送道路ネットワーク |
| 公園 | `data/related/park.geojson` | 広島市公園一覧 |
| ランドマーク | `data/related/landmark.geojson` | 広島市主要ランドマーク |

---

## 前提条件

### Python 環境（pixi）

[pixi](https://prefix.dev/docs/pixi/overview) をインストールしてください。

```bash
# Windows (PowerShell)
winget install prefix-dev.pixi

# macOS / Linux
curl -fsSL https://pixi.sh/install.sh | bash
```

### フロントエンド環境（Node.js）

Web UI を使う場合は [Node.js 18 以上](https://nodejs.org/) が必要です。

```bash
# バージョン確認
node --version  # v18.0.0 以上
npm --version
```

---

## セットアップ

```bash
# 1. リポジトリを clone
git clone https://github.com/raokiey/hiroshima-bldg-rag-example.git
cd hiroshima-bldg-rag-example

# 2. Python 依存パッケージをインストール
pixi install

# 3. API キーを設定
cp .env.example .env   # または手動で .env を作成
```

`.env` ファイルに以下を記載してください：

```
GEMINI_API_KEY=your_gemini_api_key
```

> `GEMINI_API_KEY` は [Google AI Studio](https://aistudio.google.com/apikey) で取得できます。

```bash
# 4. フロントエンド依存パッケージをインストール（Web UI を使う場合のみ）
cd frontend
npm install
cd ..
```

---

## CLI コマンド

| コマンド | 内容 | 所要時間 |
|---------|------|---------|
| `pixi run investigate` | DuckDB でデータ構造・JOIN 検証 | 数秒 |
| `pixi run spatial` | 座標変換・空間検索テスト | 数秒 |
| `pixi run enrich` | 建物カルテ生成・埋め込み保存 | **初回のみ 数十分**（API 呼び出し） |
| `pixi run search` | CLI デモ検索（自然言語クエリ → LLM 回答） | 約 30 秒 |

#### `pixi run enrich` について

`pixi run enrich` は全 2,958 件の建物に対して埋め込みを生成します。
処理済みデータ（`output/plateau_rag.duckdb`）が存在する場合は実行不要です。

```bash
# 保存済みデータの確認
pixi run python -c "
import duckdb
con = duckdb.connect('output/plateau_rag.duckdb', read_only=True)
con.execute('LOAD vss')
print('件数:', con.execute('SELECT COUNT(*) FROM building_chunks').fetchone()[0])
"
```

#### CLI デモ実行例

引数なしで実行するとデモクエリ 2 件が自動実行されます。

```bash
pixi run search
```

**クエリを直接指定**することもできます。

```bash
pixi run search "高潮リスクが低く耐火構造の建物"
pixi run search "駅から近く、避難所まで 500m 以内の建物"
```

空間フィルタ（エリア絞り込み）を使いたい場合は、`src/app/retrieval.py` の
`run_retrieval_demo()` 内で `lon` / `lat` / `radius_m` を直接指定してください。

```python
result = hybrid_search(
    query="耐火構造で避難所に近い建物",
    lon=132.4625,   # 経度（WGS84）
    lat=34.3955,    # 緯度（WGS84）
    radius_m=500.0, # 検索半径（メートル）
    top_k=10,
)
```

---

### Web UI

チャット形式で自然言語クエリを投げ、結果を地図上に可視化するインターフェースです。

#### 起動方法

**ターミナル 1 — FastAPI バックエンド**

```bash
pixi run app
# → http://localhost:8000 で起動
```

**ターミナル 2 — Vite フロントエンド（開発サーバー）**

```bash
pixi run dev
# → http://localhost:5173 で起動
```

ブラウザで `http://localhost:5173` を開いてください。

> **注意:** バックエンド（ポート 8000）が先に起動している必要があります。

#### 本番ビルド

```bash
pixi run build
# → frontend/src/static/ にビルド成果物を出力
# → pixi run app のみで http://localhost:8000 から配信
```

#### 使い方

1. **チャット入力欄**にクエリを入力して Enter（または送信ボタン）を押す
2. AI が候補建物リストと選定理由を回答する
3. 候補建物がある場合は「**地図で確認**」ボタンが表示される
4. 地図パネルで建物ポリゴンをクリックするとリスク情報のポップアップが表示される

**クエリ例（例示ボタンからも選択可能）：**

```
高潮リスクが低く、鉄筋コンクリート造の建物は？
駅から近く避難所まで徒歩 10 分以内の建物は？
耐火構造で公園に隣接している建物を探して
```

#### 設定オプション

| 設定 | 選択肢 | 説明 |
|------|--------|------|
| 埋め込み | RURI v3 310m（デフォルト、ローカル）/ Gemini Embedding | クエリ埋め込みモデルの切り替え |
| 上位件数 | 5 / 10 / 20 | 候補建物の表示件数 |
| テーマ | ライト / ダーク | 地図スタイルも連動して切り替わる |

#### API エンドポイント

バックエンドに直接アクセスすることも可能です。

```bash
# ヘルスチェック
curl http://localhost:8000/api/health

# 検索（JSON）
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "高潮リスクが低い耐火建物",
    "top_k": 10
  }'
```

レスポンス例：

```json
{
  "query": "高潮リスクが低い耐火建物",
  "answer": "以下の建物を推薦します...",
  "elapsed_sec": 4.2,
  "geojson": {
    "type": "FeatureCollection",
    "features": [...]
  },
  "candidate_count": 10
}
```

---

## プロジェクト構成

```
geospatial-city-rag/
├── CLAUDE.md              # AI エージェント向け仕様書
├── pixi.toml              # パッケージ定義・タスク定義
├── .env                   # API キー（git 管理外）
│
├── data/                  # 入力データ（読み取り専用）
│   ├── hiroshima_sample.gpkg
│   ├── hiroshima_landuse.gpkg
│   ├── hiroshima_urf.gpkg
│   ├── codelists/         # PLATEAU コードリスト XML（属性コード → 日本語変換）
│   └── related/           # GeoJSON 関連データ（避難施設・駅・公園など）
│
├── docs/
│   ├── specification.pdf  # PLATEAU データ仕様書
│   ├── plan.md            # 実装計画書
│   └── work_log.md        # 実装作業ログ
│
├── src/
│   ├── common/
│   │   └── db.py               # DuckDB 接続・座標変換共通ユーティリティ
│   ├── pipeline/                # オフラインのデータ構築バッチ
│   │   ├── investigate.py        # データ構造調査
│   │   ├── gpkg.py                # 空間演算
│   │   ├── enrichment.py           # セマンティック・チャンク化・埋め込み生成
│   │   ├── geometry.py              # LOD2 ジオメトリ解析
│   │   ├── context.py                # 建物間コンテキスト計算
│   │   ├── ruri_embed.py              # RURI 埋め込みバッチ生成
│   │   └── codelist_loader.py          # PLATEAU コードリスト XML パーサー
│   └── app/                     # ランタイム API サーバー
│       ├── main.py               # FastAPI バックエンドサーバー
│       ├── retrieval.py           # ハイブリッド検索・LLM 回答生成
│       ├── router.py               # クエリルーティング（構造化/意味的/ハイブリッド）
│       ├── search_fusion.py         # FTS/BM25・RRF・HyDE
│       ├── query_parser.py           # 自然言語クエリ解析
│       ├── geocoder.py                # 地名・ランドマーク解決
│       └── ruri_query.py               # RURI クエリ埋め込み（ランタイム）
│
├── frontend/              # Web UI（Vite + TypeScript + MapLibre GL JS）
│   ├── index.html
│   ├── vite.config.ts
│   ├── package.json
│   └── src/
│       ├── main.ts        # エントリーポイント・イベント配線
│       ├── store.ts       # UI 状態管理
│       ├── api.ts         # バックエンド API クライアント
│       ├── chat.ts        # チャット UI 操作
│       ├── map.ts         # MapLibre GL JS 地図操作
│       ├── theme.ts       # ライト/ダークテーマ切り替え
│       └── style.css      # CSS カスタムプロパティ・レスポンシブ対応
│
├── output/
│   └── plateau_rag.duckdb     # RAG データベース（enrich 実行で生成）
│
└── tests/
    └── sanity_checks.py       # 全項目のサニティチェック
```

---

## 技術スタック

| 役割 | 採用技術 |
|------|---------|
| パッケージ管理 | pixi |
| データベース | DuckDB（spatial / vss 拡張） |
| 空間データ形式 | GeoPackage（EPSG:6671）・GeoJSON（WGS84） |
| 埋め込み生成 | `ruri-v3-310m`（デフォルト、768 次元、ローカル）/ `gemini-embedding-001`（切り替え可） |
| 推論・回答生成 | Gemini 3.5 Flash Lite |
| ベクトル検索 | DuckDB VSS（HNSW インデックス、cosine 距離） |
| バックエンド API | FastAPI + Uvicorn |
| フロントエンド | Vite + TypeScript（フレームワークなし） |
| 地図表示 | MapLibre GL JS 4.x + OpenFreeMap（ベクトルタイル） |

---

## サニティチェック

```bash
pixi run python tests/sanity_checks.py
```

全項目がパスすることを確認してください。

---

## 日英切り替えについて

チャットUI右上の言語トグルボタンで日本語/英語を切り替えられます。以下は既知の制限です。

- **固有名詞は翻訳されません**: 駅名・避難所名・学校名・病院名等はDBに日本語で
  保存されているため、英語モードでもそのまま表示されます。
- **言語トグル時に既存の会話履歴・地図表示は再翻訳されません**: 次回の検索から
  新しい言語設定が反映されます（シンプルさを優先した設計判断）。
- **LLM回答の言語はUIの言語設定と連動**します（個別に選択する機能はありません）。
- DB由来の列挙値（用途・構造・耐火・浸水ランク・屋根種別・形状分類）は、
  実データで確認した値のみを翻訳辞書（`frontend/src/i18n.ts`）に登録しています。
  今後コードリストにない新しい値が追加された場合は、この辞書の更新が必要です。
