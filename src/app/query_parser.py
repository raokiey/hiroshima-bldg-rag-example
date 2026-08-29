"""Natural-language query parsing engine.

Structures a natural-language query via Gemini Flash (temperature=0, JSON
schema output) into a `ParsedQuery` dataclass carrying spatial filters,
attribute filters, and sort conditions.

`height_min` design:
- An ambiguous relative expression like "高い" (tall) with no stated purpose
  -> height_min=None, sort_by=SortSpec("measured_height", "desc"), and
  clarification_question set (hybrid_search returns early with the question).
- A purpose implied by context, e.g. "洪水避難のための高い建物" (tall building
  for flood evacuation) -> the LLM estimates height_min.
- An explicit number, e.g. "30m以上" -> converted directly to height_min.

Numeric/ordering/negation/distance conditions are structured as far as
possible into `risk_filters` / `distance_filters` / `sort_by`, so `router.py`
can decide them definitively via SQL WHERE/ORDER BY. Only conditions that
can't be quantified (e.g. "日当たりのよい" / well-lit, "静かな" / quiet) are
left in `semantic_residual`; when every condition was structured,
`semantic_residual` is "".
"""

import json
import os
import time
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

# Actual Japanese label values stored in the DB (enumerated in the LLM prompt).
_USAGE_VALUES = (
    "不明/商業系複合施設/共同住宅/業務施設/文教厚生施設/商業施設/住宅/"
    "運輸倉庫施設/官公庁施設/店舗等併用共同住宅/宿泊施設/店舗等併用住宅/その他/供給処理施設"
)
_STRUCTURE_VALUES = (
    "不明/鉄筋コンクリート造/鉄骨造/鉄骨鉄筋コンクリート造/"
    "木造・土蔵造/レンガ造・コンクリートブロック造・石造/軽量鉄骨造"
)
# building_chunks.fire_proof's actual values (confirmed via SELECT DISTINCT).
_FIRE_PROOF_VALUES = "不明/耐火/準耐火造/その他"

# Column names valid for sort_by.key (must match router.py's mapping table).
# Includes keys precomputed into building_geom_meta / building_context_meta.
_SORT_KEYS = (
    "measured_height/storeys/"
    "nearest_station_dist_m/nearest_shelter_dist_m/nearest_park_dist_m/"
    "nearest_emroute_dist_m/nearest_landmark_dist_m/"
    "ht_depth_max/rv_depth_max/ts_depth_max/"
    "roof_area_m2/ground_elev_m/prominence_m/volume_m3/footprint_area_m2/slenderness/"
    "wall_ratio_n/wall_ratio_e/wall_ratio_s/wall_ratio_w/"
    "nearest_school_dist_m/nearest_hospital_dist_m/circularity"
)
# Classification values valid for footprint_shape (must match
# geometry.py's estimate_shape_type()).
_SHAPE_VALUES = "円形に近い/楕円形/矩形・単純形状/L字型/コの字型・T字型/十字型・複雑形状/星形・複雑形状"
_DISTANCE_TARGETS = "station/shelter/park/emroute/landmark/school/hospital/police/fire/post"
_RISK_HAZARDS = "ht（高潮）/rv（洪水）/ts（津波）"

# height_min 推定ルール（LLM プロンプトに埋め込む）
_HEIGHT_RULES = """
height_min の設定ルール（厳守。上から順に判定し、最初に該当したルールを適用する）:
1. 「最も高い」「一番高い」「最上位」など最上級表現の場合:
   height_min=null、sort_by={"key": "measured_height", "order": "desc"}、
   clarification_question=null。
   （最上級表現は「上位から順に見たい」という決定的な要求であり、
   フィルタ閾値の曖昧さがないため確認質問は不要）
2. 「20m以上」「30メートル超」「10階以上（1階≈3m）」など具体的数値が明示されている場合:
   height_min に数値を設定する。clarification_question は null。
3. 洪水・高潮・津波避難のために高い建物が必要と読み取れる場合:
   height_min=10.0（3階以上相当）、clarification_question は null。
4. 眺望・景観・見晴らしのために高い建物が必要と読み取れる場合:
   height_min=30.0（10階以上相当）、clarification_question は null。
5. ランドマーク・目立つ建物・超高層が必要と読み取れる場合:
   height_min=60.0（20階以上相当）、clarification_question は null。
6. 「高い建物」「背の高い建物」のみ（最上級でも具体的数値でも目的明記でもない）場合:
   height_min=null、sort_by={"key": "measured_height", "order": "desc"}、
   clarification_question に以下を設定:
   「どのような目的で高い建物をお探しですか？\n（例：「洪水・高潮時の垂直避難のため」なら浸水リスクに合わせた高さを設定します。「眺望・景観のため」なら30m以上が目安です。「ランドマーク・目立つ建物」なら60m以上が目安です）」
7. 高さに関する記述が一切ない場合:
   height_min=null、sort_by=null、clarification_question=null。
"""

# Phase 10 追加ルール（リスク・距離・ソート・意味的残差の切り分け）
_STRUCTURED_RULES = f"""
risk_filters の設定ルール（配列。該当なしは空配列 []）:
- 各要素は {{"hazard": "ht"|"rv"|"ts", "mode": "none"|"max_depth", "max_depth_m": 数値またはnull}}
- 対応する災害: {_RISK_HAZARDS}
- 「リスクが低い/ない/安全/心配ない」「浸水想定区域外」→ mode="none"（max_depth_m は null）
- 「浸水 Nm 以下なら可」「N m 未満」など明示的な上限 → mode="max_depth", max_depth_m=N
- 災害種別が明示されない「リスクが低い」は高潮(ht)・洪水(rv)・津波(ts) の3つ全てに
  mode="none" を設定する（3要素の配列にする）。
- 【重要・mode="max_depth" 時の災害種別デフォルト】「洪水」「河川氾濫」「津波」など
  災害種別を明示せず、単に「浸水 Nm 以下」とだけ言うクエリは hazard="ht"（高潮）
  1件のみを設定すること（rv・ts は追加しない）。「洪水」「河川」の語があれば
  hazard="rv"、「津波」の語があれば hazard="ts" を用いる。mode="none"（3種類
  全てに設定）とは異なり、mode="max_depth" では災害種別不明時に複数要素を
  作らないこと。
  例:「浸水5m以下で耐火構造の建物」→ risk_filters=[{{"hazard":"ht","mode":
  "max_depth","max_depth_m":5.0}}]（rv・ts の要素は追加しない）。
- 【重要な区別】「◯◯避難のための高い建物」「◯◯避難に適した建物」「垂直避難できる建物」
  など"避難先として使える建物"を求めるクエリは、height_min の設定対象であり
  risk_filters の対象ではない。避難先の建物はリスクゾーン内に立地することが
  一般的であり（むしろリスクがある地域にこそ避難先が必要）、「そのリスクが
  存在しないこと」を意味しない。risk_filters は「自分の建物がその災害リスクに
  遭いたくない（リスク自体を避けたい）」という文脈でのみ設定すること。
  例:「洪水避難のための高い建物」→ height_min=10.0 のみ設定し、risk_filters=[]
  （rv の risk_filters は追加しない）。

distance_filters の設定ルール（配列。該当なしは空配列 []）:
- 各要素は {{"target": "station"|"shelter"|"park"|"emroute"|"landmark", "max_dist_m": 数値}}
- target の対応: station=駅、shelter=避難所、park=公園、emroute=緊急輸送道路、landmark=ランドマーク
- 「駅から近い」など施設種別が明確で数値がない曖昧な距離表現 → max_dist_m=500.0 をデフォルト適用
- 「隣接」「すぐ隣」「隣り合う」「接している」など"近い"よりも近接性が強い表現で
  数値がない場合 → max_dist_m=100.0 をデフォルト適用（500.0 ではない）。
  max_dist_m を 0 にすることは絶対にしないこと（該当施設が存在しなくなり検索が
  破綻するため）。
- 「徒歩 N 分」→ max_dist_m = N × 80.0（不動産表示規約の速度換算）
- 「Nm以内」「N km圏内」→ そのままメートル換算

fire_proof の設定ルール:
- 「耐火構造」「耐火建築物」→ fire_proof="耐火"
- 「準耐火」→ fire_proof="準耐火造"
- 使用できる値のみ: {_FIRE_PROOF_VALUES}
- 言及がなければ null

sort_by の設定ルール（該当なしは null）:
- 「最も高い/一番高い/最上位」→ {{"key": "measured_height", "order": "desc"}}
  （このとき height_min は設定しない。フィルタではなく並び替えの指示のため）
- 「最も近い/一番近い」+ 施設名 → {{"key": "nearest_<target>_dist_m", "order": "asc"}}
  （station/shelter/park/emroute/landmark のいずれか。施設名から target を判定）
- 「最もリスクが高い/低い」→ 該当する *_depth_max を key にし、order は
  高い→desc、低い→asc
- key に使える値: {_SORT_KEYS}
- 曖昧な「高い建物」で目的不明の場合は _HEIGHT_RULES のルール5を優先する

semantic_residual の設定ルール:
- risk_filters / distance_filters / fire_proof / height_min / usage_include /
  structure_type / sort_by / location_name / orientation_filters / sunlight /
  quiet / vertical_evacuation / height_max / storeys_min / storeys_max /
  usage_exclude / structure_exclude / roof_type / wooden_dense のいずれでも
  表現できない条件のみを原文に近い形で残す
  （例:「景観が美しい」「モダンな外観」「防災拠点に向いた」）。
- 上記フィールドで全条件を表現しきれた場合は semantic_residual="" とする。
- 「高い」「近い」など既に height_min/sort_by/distance_filters で表現済みの語を
  重複して semantic_residual に残さないこと。
"""

# Phase 15: 方位・日照・静けさ・階数範囲・除外・屋根・木造密度の変換ルール
_ORIENTATION_RULES = """
orientation_filters の設定ルール（配列。該当なしは空配列 []）:
- 各要素は {"direction": "n"|"e"|"s"|"w", "mode": "prefer"|"avoid"}
- 「南向き」「南側に窓が多い」→ [{"direction":"s","mode":"prefer"}]
- 「朝日が入る」（東向き）→ [{"direction":"e","mode":"prefer"}]
- 「西日が当たらない」「西向きを避けたい」→ [{"direction":"w","mode":"avoid"}]
- 「北向きを避けたい」→ [{"direction":"n","mode":"avoid"}]

sunlight の設定ルール:
- 「日当たりがよい」「日照重視」「日当たりを気にしている」→ sunlight=true
- 【重要】orientation_filters とは独立したフィールドである。sunlight=true の
  ときに orientation_filters へ南向き条件を重複して追加しないこと
  （日照の可否は南側遮蔽込みの専用判定であり、方位比率のみの条件とは別物）。
- 言及がなければ false

quiet の設定ルール:
- 「静かな」「騒音が少ない」「幹線道路から離れた」→ quiet=true
- 言及がなければ false

vertical_evacuation の設定ルール:
- 「浸水しても上の階に逃げられる」「垂直避難できる」→ vertical_evacuation=true
- 言及がなければ false

height_max / storeys_min / storeys_max の設定ルール:
- 「Nm以下」「N階建て以下」→ height_max / storeys_max（height_min とは独立。
  両方設定されれば範囲指定になる）
- 「N階建て以上」→ storeys_min（height_min の3m換算より storeys_min を優先する）
- 「高さ20m以上40m以下」→ height_min=20.0 かつ height_max=40.0
- 「はしご車が届く高さ」「はしご車の届く範囲」→ height_max=31.0
  （消防のはしご車が一般的に到達可能な高さの目安）

usage_exclude / structure_exclude の設定ルール（配列。該当なしは空配列 []）:
- 「◯◯以外」「◯◯を除く」（用途）→ usage_exclude に日本語ラベルを追加
- 「◯◯以外」「◯◯を除く」（構造）→ structure_exclude に日本語ラベルを追加
- 「木造以外」→ structure_exclude=["木造・土蔵造"]

roof_type の設定ルール:
- 「屋上が広い」→ orientation等ではなく sort_by={"key":"roof_area_m2","order":"desc"} とする
- 「平らな屋根」「陸屋根」→ roof_type="陸屋根"
- 「勾配のある屋根」「切妻屋根」→ roof_type="勾配屋根"
- 言及がなければ null

wooden_dense の設定ルール:
- 「木造密集地」「木造が多いエリア」「木造住宅密集地域」→ wooden_dense=true
- 言及がなければ false

sort_by の追加ルール（既存ルールに加えて）:
- 「屋上が広い」→ {"key":"roof_area_m2","order":"desc"}
- 「高台」「標高が高い場所」→ {"key":"ground_elev_m","order":"desc"}
- 「目立つ」「ひときわ高い」「周囲より突出した」→ {"key":"prominence_m","order":"desc"}
- 「細長い建物」「ペンシルビル」→ {"key":"slenderness","order":"desc"}
- 「体積が大きい」「ボリュームのある建物」→ {"key":"volume_m3","order":"desc"}
- 「敷地（底面積）が広い」→ {"key":"footprint_area_m2","order":"desc"}
- 「最も階数が多い」「一番階数の多い」→ {"key":"storeys","order":"desc"}
- 「学校の近く」「病院まで徒歩10分」等は distance_filters の target に
  school/hospital/police/fire/post を使う（既存の仕組みに自然に乗る）
"""

# Phase 20/25: フットプリント（底面）形状の変換ルール
_SHAPE_RULES = f"""
footprint_shape の設定ルール（配列。建物の水平断面・輪郭の形状を問うクエリ専用。
建築構造〔structure_type〕や用途とは無関係。該当なしは空配列 []）:
- 使用できる値のみ: {_SHAPE_VALUES}
- 「真円」「正円」「円形に近い」（真円であることを明示する表現。「円形に近い」は
  分類名そのものであり厳密な円形を指す）→ ["円形に近い"]
- 「円形」（単独）「丸い」「円柱状」「曲線的な形状」（真円・楕円を問わない一般的な表現）→
  ["円形に近い", "楕円形"]
- 「楕円」「楕円形」「オーバル」「小判型」「卵型」（細長い丸形状を明示する表現）→ ["楕円形"]
- 「矩形」「四角い」「シンプルな形状」「長方形」「正方形」→ ["矩形・単純形状"]
- 「L字型」「L字」「かぎ型」→ ["L字型"]
- 「コの字型」「U字型」「馬蹄形」→ ["コの字型・T字型"]
- 「十字型」「クロス型」「T字型」→ ["十字型・複雑形状"]
- 「星形」「星型」「ギザギザした形状」「複雑な形状」「凹凸のある形状」「不整形」→ ["星形・複雑形状"]
- 上記のいずれにも明確に対応しない曖昧な形状表現（例:「面白い形」「特徴的な形」）は
  footprint_shape=[] のままとし、原文を semantic_residual に残す
  （形状語はベクトル検索では実質認識されないため、既知の限界として扱う）。
- 言及がなければ []。
- 「最も円形に近い建物」など最上級表現の場合は
  sort_by={{"key":"circularity","order":"desc"}} を設定し、footprint_shape は
  設定しない（フィルタではなく並び替えの指示のため）。
"""

_SYSTEM_PROMPT = f"""あなたは地理空間クエリ解析器です。
ユーザーの自然言語クエリを解析し、以下の JSON 形式で建物検索条件を抽出してください。

【抽出フィールドの説明】
- location_name: 場所名（「広島駅」「平和記念公園」など具体的な駅・施設・ランドマーク名）。
  場所の言及がない場合、または「広島市」「市内」「広島市内」など対象データセット全体
  （広島市全域）を指すだけの語の場合は null とする（データは元々広島市限定のため、
  これらは絞り込み条件にならない）。
- radius_m: 場所周辺の検索半径（メートル）。デフォルト 500.0。「1km以内」なら 1000.0。
- height_min: 最低高さ（メートル）。下記ルールを参照。
- usage_include: 対象用途の日本語ラベルリスト。指定なしは空リスト []。
  使用できる値のみ: {_USAGE_VALUES}
- structure_type: 建築構造の日本語ラベル。指定なしは null。
  使用できる値のみ: {_STRUCTURE_VALUES}
- fire_proof: 耐火仕様の日本語ラベル。指定なしは null。
- risk_filters: 災害リスク条件の配列。
- distance_filters: 施設までの距離条件の配列（target は
  station/shelter/park/emroute/landmark に加えて school/hospital/police/fire/post
  も指定可能）。
- sort_by: 汎用ソート指定（{{"key": ..., "order": "asc"|"desc"}} または null）。
- sort_by_height: 後方互換用（sort_by.key=="measured_height" かつ order=="desc" の場合のみ true。
  それ以外は false）。
- orientation_filters: 壁面方位条件の配列。下記ルールを参照。
- sunlight: 日照（南側遮蔽込み）を重視するか。下記ルールを参照。
- quiet: 静かな環境（幹線道路から離れている）を重視するか。下記ルールを参照。
- vertical_evacuation: 浸水時の垂直避難可否を条件にするか。下記ルールを参照。
- height_max: 最高高さ（メートル）。指定なしは null。
- storeys_min: 最低階数。指定なしは null。
- storeys_max: 最高階数。指定なしは null。
- usage_exclude: 除外する用途の日本語ラベルリスト。指定なしは空リスト []。
- structure_exclude: 除外する建築構造の日本語ラベルリスト。指定なしは空リスト []。
- roof_type: 屋根種別（"陸屋根"|"勾配屋根"）。指定なしは null。
- wooden_dense: 木造密集地を条件にするか。下記ルールを参照。
- footprint_shape: 建物の水平断面（フットプリント）の輪郭形状。下記ルールを参照。
- semantic_residual: 構造化フィールドで表現しきれない意味的な残差テキスト。なければ空文字 ""。
- clarification_question: 高さ目的が不明な場合の確認質問文。それ以外は null。

{_HEIGHT_RULES}

{_STRUCTURED_RULES}

{_ORIENTATION_RULES}

{_SHAPE_RULES}

【重要】
- usage_include と structure_type の値は上記リストの日本語ラベルをそのまま使うこと。
- 「耐火構造」「RC造」「コンクリート建物」は structure_type="鉄筋コンクリート造" に対応。
- 「木造」は structure_type="木造・土蔵造" に対応。
- 必ず有効な JSON のみを返す。
"""


@dataclass
class RiskFilter:
    """A disaster risk condition."""
    hazard: str                      # "ht" | "rv" | "ts"
    mode: str                        # "none" (no risk) | "max_depth" (upper bound)
    max_depth_m: float | None = None  # Only used when mode="max_depth".


@dataclass
class DistanceFilter:
    """A distance-to-facility condition."""
    target: str        # "station" | "shelter" | "park" | "emroute" | "landmark"
    max_dist_m: float


@dataclass
class SortSpec:
    """A generic sort specification."""
    key: str           # measured_height / storeys / nearest_*_dist_m / *_depth_max / precomputed columns.
    order: str          # "asc" | "desc"


@dataclass
class OrientationFilter:
    """A wall-orientation condition."""
    direction: str     # "n" | "e" | "s" | "w"
    mode: str          # "prefer" (favor this direction) | "avoid" (avoid this direction).


@dataclass
class ParsedQuery:
    """The structured result of parsing a natural-language query."""
    location_name: str | None = None          # Place name. None = no spatial filter.
    radius_m: float = 500.0                   # Search radius (meters).
    height_min: float | None = None           # Minimum height. None = no filter.
    usage_include: list[str] = field(default_factory=list)  # Target usage labels.
    structure_type: str | None = None         # Structure type. None = no filter.
    sort_by_height: bool = False              # Backward-compat field, normalized from sort_by.
    clarification_question: str | None = None # Confirmation question when height purpose is ambiguous.
    risk_filters: list[RiskFilter] = field(default_factory=list)
    distance_filters: list[DistanceFilter] = field(default_factory=list)
    fire_proof: str | None = None
    sort_by: SortSpec | None = None           # Takes precedence over sort_by_height when set.
    semantic_residual: str = ""               # Semantic condition left over after structuring. "" if none.
    orientation_filters: list[OrientationFilter] = field(default_factory=list)
    sunlight: bool = False
    quiet: bool = False
    vertical_evacuation: bool = False
    height_max: float | None = None
    storeys_min: int | None = None
    storeys_max: int | None = None
    usage_exclude: list[str] = field(default_factory=list)
    structure_exclude: list[str] = field(default_factory=list)
    roof_type: str | None = None              # "陸屋根" (flat) | "勾配屋根" (sloped).
    wooden_dense: bool = False
    footprint_shape: list[str] = field(default_factory=list)  # Subset of _SHAPE_VALUES. Empty list = no filter.


_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "location_name":          {"type": "string",  "nullable": True},
        "radius_m":               {"type": "number"},
        "height_min":             {"type": "number",  "nullable": True},
        "usage_include":          {"type": "array", "items": {"type": "string"}},
        "structure_type":         {"type": "string",  "nullable": True},
        "fire_proof":             {"type": "string",  "nullable": True},
        "risk_filters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "hazard":      {"type": "string"},
                    "mode":        {"type": "string"},
                    "max_depth_m": {"type": "number", "nullable": True},
                },
                "required": ["hazard", "mode", "max_depth_m"],
            },
        },
        "distance_filters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "target":      {"type": "string"},
                    "max_dist_m":  {"type": "number"},
                },
                "required": ["target", "max_dist_m"],
            },
        },
        "sort_by": {
            "type": "object",
            "nullable": True,
            "properties": {
                "key":   {"type": "string"},
                "order": {"type": "string"},
            },
            "required": ["key", "order"],
        },
        "semantic_residual":      {"type": "string"},
        "clarification_question": {"type": "string",  "nullable": True},
        "orientation_filters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string"},
                    "mode":      {"type": "string"},
                },
                "required": ["direction", "mode"],
            },
        },
        "sunlight":              {"type": "boolean"},
        "quiet":                 {"type": "boolean"},
        "vertical_evacuation":   {"type": "boolean"},
        "height_max":            {"type": "number",  "nullable": True},
        "storeys_min":           {"type": "integer", "nullable": True},
        "storeys_max":           {"type": "integer", "nullable": True},
        "usage_exclude":         {"type": "array", "items": {"type": "string"}},
        "structure_exclude":     {"type": "array", "items": {"type": "string"}},
        "roof_type":             {"type": "string",  "nullable": True},
        "wooden_dense":          {"type": "boolean"},
        "footprint_shape":       {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "location_name", "radius_m", "height_min",
        "usage_include", "structure_type", "fire_proof",
        "risk_filters", "distance_filters", "sort_by",
        "semantic_residual", "clarification_question",
        "orientation_filters", "sunlight", "quiet", "vertical_evacuation",
        "height_max", "storeys_min", "storeys_max",
        "usage_exclude", "structure_exclude", "roof_type", "wooden_dense",
        "footprint_shape",
    ],
}


def parse_query(query: str, response_language: str = "ja") -> ParsedQuery:
    """Parse a natural-language query into a ParsedQuery via Gemini Flash.

    Uses Gemini Flash (temperature=0, JSON schema output), retrying up to 3
    times. On failure, returns a default `ParsedQuery()` rather than raising.

    Args:
        query: The user's natural-language query.
        response_language: "ja" (default) or "en". When "en", only the
            generated `clarification_question` text is in English — every
            other field (classifications, code values) is language-invariant
            by design, so is unaffected.

    Returns:
        The parsed query, or a default `ParsedQuery()` if parsing failed
        after all retries.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("  [WARN] GEMINI_API_KEY 未設定 — クエリ解析をスキップ")
        return ParsedQuery()

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    prompt = f"{_SYSTEM_PROMPT}\n\n【ユーザークエリ】\n{query}"
    if response_language == "en":
        prompt += (
            "\n\n【出力言語】\nclarification_question を設定する場合は英語で"
            "記述すること。それ以外のフィールド（分類・コード値等）は変更しないこと。"
        )

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=_RESPONSE_SCHEMA,
                ),
            )
            data = json.loads(response.text)

            risk_filters = [
                RiskFilter(
                    hazard=rf["hazard"],
                    mode=rf["mode"],
                    max_depth_m=(float(rf["max_depth_m"]) if rf.get("max_depth_m") is not None else None),
                )
                for rf in data.get("risk_filters", []) or []
            ]
            distance_filters = [
                DistanceFilter(target=df["target"], max_dist_m=float(df["max_dist_m"]))
                for df in data.get("distance_filters", []) or []
            ]
            sort_by_data = data.get("sort_by")
            sort_by = (
                SortSpec(key=sort_by_data["key"], order=sort_by_data["order"])
                if sort_by_data
                else None
            )
            # Backward compat: normalize sort_by_height from sort_by.
            sort_by_height = bool(
                sort_by and sort_by.key == "measured_height" and sort_by.order == "desc"
            )

            orientation_filters = [
                OrientationFilter(direction=of["direction"], mode=of["mode"])
                for of in data.get("orientation_filters", []) or []
            ]

            # Detect include/exclude contradictions: if the LLM puts the same
            # label in both include and exclude, the query would always match
            # zero rows. Favor the include intent and drop it from exclude,
            # logging a warning.
            usage_include = data.get("usage_include", []) or []
            usage_exclude = data.get("usage_exclude", []) or []
            overlap = set(usage_include) & set(usage_exclude)
            if overlap:
                print(f"  [WARN] usage_include と usage_exclude に同一ラベル {overlap} — exclude 側から除去")
                usage_exclude = [u for u in usage_exclude if u not in overlap]

            structure_type = data.get("structure_type")
            structure_exclude = data.get("structure_exclude", []) or []
            if structure_type and structure_type in structure_exclude:
                print(f"  [WARN] structure_type='{structure_type}' が structure_exclude にも存在 — exclude 側から除去")
                structure_exclude = [s for s in structure_exclude if s != structure_type]

            return ParsedQuery(
                location_name=data.get("location_name"),
                radius_m=float(data.get("radius_m", 500.0)),
                height_min=(float(data["height_min"]) if data.get("height_min") is not None else None),
                usage_include=usage_include,
                structure_type=structure_type,
                sort_by_height=sort_by_height,
                clarification_question=data.get("clarification_question"),
                risk_filters=risk_filters,
                distance_filters=distance_filters,
                fire_proof=data.get("fire_proof"),
                sort_by=sort_by,
                semantic_residual=data.get("semantic_residual", "") or "",
                orientation_filters=orientation_filters,
                sunlight=bool(data.get("sunlight", False)),
                quiet=bool(data.get("quiet", False)),
                vertical_evacuation=bool(data.get("vertical_evacuation", False)),
                height_max=(float(data["height_max"]) if data.get("height_max") is not None else None),
                storeys_min=(int(data["storeys_min"]) if data.get("storeys_min") is not None else None),
                storeys_max=(int(data["storeys_max"]) if data.get("storeys_max") is not None else None),
                usage_exclude=usage_exclude,
                structure_exclude=structure_exclude,
                roof_type=data.get("roof_type"),
                wooden_dense=bool(data.get("wooden_dense", False)),
                footprint_shape=data.get("footprint_shape", []) or [],
            )
        except Exception as exc:
            if attempt == 2:
                print(f"  [WARN] クエリ解析失敗（3回試行）: {exc} — デフォルト ParsedQuery を使用")
                return ParsedQuery()
            wait = 2 * (attempt + 1)
            print(f"  [RETRY {attempt + 1}] クエリ解析 {wait}秒後リトライ...")
            time.sleep(wait)

    return ParsedQuery()


if __name__ == "__main__":
    # Manual smoke test.
    test_cases = [
        # (query, rough expected-output note)
        ("広島駅付近の高い建物は？",
         "location_name='広島駅', sort_by={key:measured_height,order:desc}, clarification_question 設定"),
        ("洪水避難のための高い建物を探して",
         "height_min>=10.0, clarification_question=None"),
        ("30m以上の鉄筋コンクリート造の建物は？",
         "height_min>=25.0, structure_type='鉄筋コンクリート造'"),
        ("高潮リスクが低く、駅から近い宿泊施設",
         "risk_filters=[{hazard:ht,mode:none}], distance_filters=[{target:station,max_dist_m:500}], usage_include=['宿泊施設']"),
        ("平和記念公園から500m以内の共同住宅",
         "location_name='平和記念公園', usage_include=['共同住宅']"),
        ("高潮リスクがない建物",
         "risk_filters=[{hazard:ht,mode:none}], semantic_residual=''"),
        ("駅から徒歩5分以内の共同住宅",
         "distance_filters=[{target:station,max_dist_m:400.0}]（5分×80m）"),
        ("最も高い建物は？",
         "sort_by={key:measured_height,order:desc}, height_min=None, clarification_question=None"),
        ("避難所まで300m以内で日当たりのよい建物",
         "distance_filters=[{target:shelter,max_dist_m:300}], semantic_residual='日当たりのよい建物'"),
        ("浸水1m以下で耐火構造の建物",
         "risk_filters=[{hazard:ht,mode:max_depth,max_depth_m:1.0}]（災害種別未指定なので"
         "ht のみ。rv・ts は追加しない）, fire_proof='耐火'"),
        # ---- Phase 15: 方位・日照・除外・範囲条件 ----
        ("南向きの建物",
         "orientation_filters=[{direction:s,mode:prefer}]"),
        ("西日の当たらない住宅",
         "orientation_filters=[{direction:w,mode:avoid}], usage_include=['住宅']"),
        ("日当たりのよい建物",
         "sunlight=true, orientation_filters=[]（重複させない）"),
        ("静かな環境の共同住宅",
         "quiet=true, usage_include=['共同住宅']"),
        ("木造以外で20m以上40m以下の建物",
         "structure_exclude=['木造・土蔵造'], height_min=20.0, height_max=40.0"),
        ("屋上が広い建物",
         "sort_by={key:roof_area_m2,order:desc}"),
        # ---- Phase 20: フットプリント形状 ----
        ("円形に近い建物を教えて",
         "footprint_shape=['円形に近い']"),
        ("L字型の建物はある？",
         "footprint_shape=['L字型']"),
        ("コの字型や十字型の建物を探して",
         "footprint_shape=['コの字型・T字型'] または ['十字型・複雑形状']（先に言及された形状を優先する想定）"),
        # ---- Phase 25: 楕円形・あいまい「円形」の複数形状マッチ ----
        ("真円の建物を探して",
         "footprint_shape=['円形に近い']（楕円形は含まない）"),
        ("丸い建物を探して",
         "footprint_shape=['円形に近い', '楕円形']（あいまい表現は両方マッチ）"),
        ("楕円形のビルはある？",
         "footprint_shape=['楕円形']"),
    ]
    for q, expected in test_cases:
        result = parse_query(q)
        print(f"\nクエリ: {q}")
        print(f"  期待値: {expected}")
        print(f"  → location_name={result.location_name}, radius_m={result.radius_m}")
        print(f"     height_min={result.height_min}, height_max={result.height_max}, sort_by={result.sort_by}")
        print(f"     usage_include={result.usage_include}, structure_type={result.structure_type}, "
              f"fire_proof={result.fire_proof}")
        print(f"     risk_filters={result.risk_filters}")
        print(f"     distance_filters={result.distance_filters}")
        print(f"     orientation_filters={result.orientation_filters}, sunlight={result.sunlight}, "
              f"quiet={result.quiet}, vertical_evacuation={result.vertical_evacuation}")
        print(f"     footprint_shape={result.footprint_shape}")
        print(f"     storeys_min={result.storeys_min}, storeys_max={result.storeys_max}, "
              f"usage_exclude={result.usage_exclude}, structure_exclude={result.structure_exclude}, "
              f"roof_type={result.roof_type}, wooden_dense={result.wooden_dense}")
        print(f"     semantic_residual={result.semantic_residual!r}")
        if result.clarification_question:
            print(f"     clarification_question={result.clarification_question[:50]}...")
