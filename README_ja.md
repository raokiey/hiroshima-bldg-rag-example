# Hiroshima Building RAG

*[English README here / 英語版 README はこちら](README.md)*

[広島県広島市のPLATEAUデータ](https://www.geospatial.jp/ckan/dataset/plateau-34100-hiroshima-shi-2022)を用いた地理空間セマンティックRAGのプロトタイプです。

「広島市内の高潮リスクが低く、駅から近い建物は？」のような言葉での質問に、
空間演算 × ベクトル検索 × LLM 推論を組み合わせて回答を行います。

チャット形式の Web UI（地図付き）と CLI の両方を用意しています。

---

## 概要

- **入力:** 言葉での質問。オプションで位置＋半径（例: 「広島城周辺、500m以内」）も指定可能。
- **出力:** おすすめ建物の一覧と選定理由を記載したテキスト、および該当建物を示す地図。
- **データ:** 広島市の Project PLATEAU 3D都市モデルに含まれる LOD2 建物の一部を、
  災害リスク属性や周辺情報（最寄り駅・最寄り避難所・近隣公園など）で拡張したもの。

---

## 処理の流れ

```
[自然言語クエリ] + [オプション: 緯度経度・半径]
        │
        ▼
  ① クエリ埋め込み（RURI v3 310m、ローカル推論。Geminiを用いた埋め込みへの切り替えも可）
        │
        ▼
  ② DuckDB HNSW ベクトル検索 + ST_DWithin 空間フィルタ（オプション）
        │
        ▼
  ③ LLM 回答生成（Gemini 3.5 Flash Lite）
        │
        ▼
  [推薦建物リスト + 選定理由テキスト] → REST API (FastAPI)
        → チャットUI + MapLibre GL JS 地図可視化
```

各建物はオフラインであらかじめ「属性カルテ」（構造・災害リスクランク・最寄り駅／避難所／公園までの
距離など）に加工され、埋め込みベクトルとともに DuckDB の HNSW インデックスに
格納されています。クエリ実行時は、質問の内容に応じて構造化検索（SQLのみ）・意味検索
（ベクトルのみ）・ハイブリッド検索（SQLで絞り込み＋ベクトルでランキング、BM25全文検索と
RRFで統合）のいずれかにルーティングすれば良いかを判断し回答を生成します。

---

## 環境構築

### Python 環境

[pixi](https://prefix.dev/docs/pixi/overview) を用いています。
[公式サイトのInstallation](https://pixi.prefix.dev/latest/installation/)を参考に、インストールしてください。

### API キー

```bash
cp .env.example .env
```

`.env` を編集してキーを設定してください。（[Google AI Studio](https://aistudio.google.com/apikey) で取得可能）：

```
GEMINI_API_KEY=your_gemini_api_key
```

### フロントエンド環境（Node.js、Web UI を使う場合のみ）

[Node.js 18 以上](https://nodejs.org/) が必要。

```bash
cd frontend
npm install
cd ..
```

---

## 実行方法

### データの準備
`data/` 配下には広島市の一部データが GeoPackage 形式で同梱済みのため、そのまま次の CLI コマンドに進めます。

他都市のデータに差し替えたい場合は、[PLATEAU GIS Converter](https://github.com/Project-PLATEAU/PLATEAU-GIS-Converter)
で CityGML を GeoPackage 形式に変換したうえで、以下のいずれかの方法でパスを指定してください（`data/`
配下のファイルをそのまま置き換える必要はありません）。

- **CLI引数**（1回限りの実行に）: 各パイプラインコマンドに `--gpkg-path` 等を渡す
  ```bash
  pixi run enrich --gpkg-path path/to/other_city.gpkg --city-prefix 12345_other-city_city_2025
  ```
- **環境変数**（`.env`、Web UI含め常時反映）: `.env.example` にコメントアウトで記載されている
  `PLATEAU_GPKG_PATH` 等を設定する

避難所・駅・緊急輸送道路・公園・ランドマークの5つのGeoJSON（`data/related/`）は、PLATEAUの標準命名規則
`{都市コード}_{都市名}_city_{年度}_{データ種別}.geojson` に従うため、`--city-prefix`（または
`PLATEAU_CITY_PREFIX`）に都市コード〜年度部分を指定するだけで5ファイルまとめて切り替わります。

### CLI

| コマンド | 内容 | 所要時間 |
|---------|------|---------|
| `pixi run investigate` | GeoPackage のテーブル構造・JOIN キーを確認 | 数秒 |
| `pixi run spatial` | 座標変換・空間検索のテスト | 数秒 |
| `pixi run enrich` | 建物カルテ生成・埋め込み保存 | **初回のみ 数十分**（API 呼び出し） |
| `pixi run search` | CLI デモ検索（自然言語クエリ → LLM 回答） | 約30秒 |

`pixi run enrich` は初回のみ実行で構いません。
`output/plateau_rag.duckdb` が既に存在する場合はデータ構築済みなので不要です。
CLIで質問を試すには以下のように実行してください：

```bash
pixi run search "高潮リスクが低く耐火構造の建物"
```

### Web UI

**ターミナル1 — FastAPI バックエンド（API）**

```bash
pixi run api
# → http://localhost:8000
```

**ターミナル2 — Vite フロントエンド（Web UI、開発サーバー）**

```bash
pixi run app
# → http://localhost:5173
```

ブラウザで `http://localhost:5173` を開く。バックエンド（ポート8000）が先に
起動している必要がある。

本番ビルド（FastAPI が直接配信、開発サーバー不要）：

```bash
pixi run build
# → frontend/src/static/ に出力後、`pixi run api` のみで全て配信される
```

---

## 使用データ
PLATEAUの建築物モデル、土地利用モデル、用途地域モデルをあらかじめGeoPackage形式に変換し使用。

| データセット | ファイル | 内容 |
|------|---------|------|
| 建物・リスク属性 | `data/hiroshima_sample.gpkg` | LOD2 建物の一部 2,958 件、高潮/洪水/津波リスク |
| 土地利用 | `data/hiroshima_landuse.gpkg` | PLATEAU 土地利用ゾーン |
| 都市計画 | `data/hiroshima_urf.gpkg` | 用途地域など |
| コードリスト | `data/codelists/` | 属性コード → 日本語ラベル変換用 XML |
| 避難施設 | `data/related/shelter.geojson` | 広島市指定避難所 |
| 鉄道駅 | `data/related/station.geojson` | 広島市内駅・路線情報 |
| 緊急輸送道路 | `data/related/emergency_route.geojson` | 広島市緊急輸送道路ネットワーク |
| 公園 | `data/related/park.geojson` | 広島市公園一覧 |
| ランドマーク | `data/related/landmark.geojson` | 広島市主要ランドマーク |

すべてのデータは、国土交通省都市局が整備する
**「3D都市モデル（Project PLATEAU）広島市（2022年度）」**
（[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.ja)）を加工して使用：
[https://www.geospatial.jp/ckan/dataset/plateau-34100-hiroshima-shi-2022](https://www.geospatial.jp/ckan/dataset/plateau-34100-hiroshima-shi-2022)

Web UI の背景地図タイルは © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors を使用。

---

## ライセンス

- **コード:** [MIT License](LICENSE)。
- **データ:** 国土交通省都市局「3D都市モデル（Project PLATEAU）広島市（2022年度）」を
  加工して使用しています。CC BY 4.0 でお使いいただけます。
  このライセンス条件は、コードの MIT ライセンスとは独立して適用されます。
