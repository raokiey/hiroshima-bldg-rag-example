# 🛰️ PLATEAU 3D都市モデル実装用詳細仕様書 (bldg & tran 特化版)

本ドキュメントは、広島市のGPKGデータおよび「3D都市モデル拡張製品仕様書 第2.0版」に基づき、実装（RAG構築・データ分析）に必要十分な技術情報を網羅したものです。

---

## 1. 共通基盤仕様 (Common Specifications)

### 1.1 座標参照系 (CRS)
- **定義:** JGD2011 / 平面直角座標系 第3系
- **EPSGコード:** `EPSG:6671`
- **単位:** メートル (m)
- **実装上の注意:** DuckDBの空間演算（`ST_DWithin`, `ST_Distance`）はこのメートル単位をそのまま使用可能。

### 1.2 オブジェクト間リレーション (Joining Logic)
- **建物本体:** `bldg:Building` (主キー: `id`)
- **拡張属性:** `uro:HighTideRiskAttribute`, `uro:RiverFloodingRiskAttribute` 等
- **結合条件:** `uro:[AttributeTable].parentId = bldg:Building.id`
- **1対多の考慮:** 1つの建物に対し、複数の災害リスク（洪水、高潮、内水）が紐づくため、`LEFT JOIN` もしくは属性の集約（Group By）が必要。

---

## 2. 建築物モデル (bldg:Building / bldg:BuildingPart)

### 2.1 主要テーブル: `bldg:Building`
| カラム名 | 型 | 説明・用途 |
| :--- | :--- | :--- |
| `id` | TEXT | GML ID。他テーブルとの結合キー。 |
| `geometry` | BLOB | 3D形状。LOD1（立体）またはLOD2（面）。 |
| `class` | TEXT | 建物の分類。コードリスト `Building_class.xml` 準拠。 |
| `usage` | TEXT | 具体的用途。住宅(1001), 商業(1020)等。 |
| `measuredHeight`| REAL | 屋根頂部までの高さ(m)。日影推論に活用。 |
| `storeysAboveGround` | INT | 地上階数。建物のボリューム判定に使用。 |

### 2.2 拡張属性: `uro:BuildingDetailAttribute`
建物のより詳細な物理的・行政的プロパティ。
- `uro:buildingID`: 自治体が付番する建物ID。
- `uro:structureType`: 構造（RC、S、木造等）。
- `uro:fireProofStructure`: 耐火構造区分。

### 2.3 災害リスク属性 (uro:DisasterRiskAttribute)
RAGにおいて「安全性」を判定するための最重要データ。
- **対象テーブル:** `uro:HighTideRiskAttribute`, `uro:RiverFloodingRiskAttribute`
- **主要カラム:**
    - `depth`: 想定浸水深 (m)。
    - `rank`: 浸水ランク。自治体定義のカテゴリ。
    - `description`: 「高潮浸水想定区域」等のテキスト情報。
    - `adminType`: 区域を指定した行政機関。

---

## 3. 交通（道路・鉄道）モデル (tran:Road / tran:Railway)

### 3.1 主要テーブル: `tran:Road`
道路は単なる線ではなく、歩道や車道を含む「面（LOD2）」として管理されます。

| カラム名 | 説明・詳細定義 |
| :--- | :--- |
| `id` | 道路セグメントのID。 |
| `class` | 道路種別 (1000:国道, 2000:都道府県道, 3000:市道等)。 |
| `function` | 機能 (1000:一般道路, 1100:高速道路等)。 |
| `usage` | 利用形態 (1000:公共, 1100:私用等)。 |
| `trafficArea` | **LOD2重要:** 車道、歩道、自転車道の幾何と属性のリスト。 |
| `auxiliaryTrafficArea` | **LOD2重要:** 中央分離帯、路肩、植樹帯等の属性。 |

### 3.2 道路部位のセマンティクス (LOD2 TrafficArea)
エージェントが「歩きやすさ」を推論する際の基準：
- **Carriageway (車道):** 自動車の走行空間。
- **Sidewalk (歩道):** 歩行者の専有空間。
- **CyclePath (自転車道):** 自転車の走行空間。

---

## 4. 実装用コードリスト（参考値）
LLMが値を解釈するためのヒント。

- **`Building_usage` (主要なもの):**
    - `1001`: 専用住宅
    - `1020`: 店舗等併用住宅
    - `1030`: 共同住宅
    - `1200`: 商業施設
- **`Road_class`:**
    - `1000`: 国道
    - `2000`: 都道府県道
    - `3000`: 市町村道

---

## 5. コーディングエージェントへの詳細指示
実装時、以下のロジックを組み込むよう指示してください：

1. **空間フィルタリング:** `ST_DWithin(geometry, ST_Point(x, y), distance)` を用いて対象建物を抽出。
2. **属性結合:** `parentId` を使ってリスク情報を Building にアタッチ。
3. **セマンティック推論:** `measuredHeight`（高さ）と `usage`（用途）から建物の性質を、`trafficArea`（歩道有無）から周辺の歩行環境を言語化。
