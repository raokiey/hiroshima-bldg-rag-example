/**
 * i18n.ts — a lightweight translation dictionary for the ja/en language toggle.
 *
 * UI_STRINGS: static UI copy and dynamic message templates (supports
 *   {key} placeholders).
 * VALUE_LABELS: an English translation dictionary for the DB's enumerated
 *   values (usage, structure, fire resistance, flood-depth rank, roof type,
 *   shape classification, direction, facility category, hazard type).
 *   Proper nouns (station names, facility names, etc.) are out of scope —
 *   translateValue() returns unregistered values as-is.
 */

import { store } from './store';

export type Lang = 'ja' | 'en';

const STORAGE_KEY = 'plateau-rag-lang';

export const UI_STRINGS: Record<Lang, Record<string, string>> = {
  ja: {
    appTitle: 'Hiroshima Building RAG',
    appEyebrow: '広島市 · PLATEAU 3D建物検索',
    skipLink: 'メインコンテンツへスキップ',
    darkModeToggle: 'ダークモードに切り替え',
    lightModeToggle: 'ライトモードに切り替え',
    langToggle: 'English',
    mapPanelAriaLabel: '候補建物の位置地図',
    mapToolbarAriaLabel: '地図操作',
    mapSheetExpandAriaLabel: '地図を広げる',
    mapSheetCollapseBtnAriaLabel: '地図を縮める',
    mapAriaLabel: '建物位置を表示する地図',
    mapAttribution: '建物: 国土交通省都市局「3D都市モデル（Project PLATEAU）広島市（2022年度）」（CC BY 4.0）を加工して使用／背景地図: OpenStreetMap。整備後の新築建物は表示・検索対象に含まれません。',
    mapCloseBtn: '× 閉じる',
    mapCloseBtnAriaLabel: '地図を閉じる',
    chatPanelAriaLabel: '建物検索チャット',
    messageListAriaLabel: '会話履歴',
    welcomeTitle: '広島市の建物を検索しましょう',
    welcomeHint: '自然言語で質問すると、防災リスクや立地条件を考慮した建物を提案します。',
    welcomeAttribution: '※ 建物データは国土交通省都市局「3D都市モデル（Project PLATEAU）広島市（2022年度）」（CC BY 4.0）を加工して使用しているため、整備後の新築建物は検索対象に含まれません。',
    exampleListAriaLabel: '質問の例',
    example1Label: '高潮リスクが低く、駅から近い建物',
    example1Query: '高潮リスクが低く、駅から近い建物を教えてください',
    example2Label: '耐火構造で避難所に近い建物',
    example2Query: '耐火構造で避難所に近い建物はどこですか',
    example3Label: '津波・洪水リスクがともに低い建物',
    example3Query: '津波・洪水リスクがともに低い建物を教えてください',
    queryInputLabel: '質問を入力（必須）',
    queryInputPlaceholder: '例: 高潮リスクが低く駅から近い建物は？',
    submitBtnAriaLabel: '検索を実行',
    queryHint: '防災条件・距離・構造など自然言語で入力し、Enter または送信ボタンで検索します。Shift+Enter で改行できます。',
    topkLabel: '件数:',
    topkSelectAriaLabel: '取得件数',
    topk5: '5件',
    topk10: '10件',
    topk20: '20件',
    embeddingLabel: '埋め込み:',
    embeddingSelectAriaLabel: '使用する埋め込みモデル',
    embeddingRuriOption: 'RURI v3 310m（ローカル）',
    themeDarkAnnounce: 'ダークモードに切り替えました',
    themeLightAnnounce: 'ライトモードに切り替えました',
    langSwitchAnnounce: '表示言語を切り替えました',
    mapOpenedAnnounce: '地図を開きました。候補建物 {count} 件を表示しています。',
    mapClosedAnnounce: '地図を閉じました。',
    mapSheetPeekAnnounce: '地図を画面下部に表示しました。',
    mapSheetHalfAnnounce: '地図を広げました。',
    mapSheetFullAnnounce: '地図を全画面に近い大きさまで広げました。',
    generatingAnnounce: '回答を生成中です...',
    resultWithCountAnnounce: '回答を生成しました。候補建物 {count} 件が見つかりました。',
    resultNoCountAnnounce: '回答を生成しました。',
    unknownError: '不明なエラーが発生しました',
    errorPrefix: 'エラー: {msg}',
    errorAnnounce: 'エラーが発生しました: {msg}',
    youAriaLabel: 'あなた: {text}',
    aiGeneratingAriaLabel: 'AI が回答を生成中',
    aiAnswerAriaLabel: 'AI の回答',
    metaText: '{count} 件 | {sec} 秒',
    mapButtonAriaLabel: '地図で {count} 件の候補建物を確認',
    mapButtonText: '🗺 地図で {count} 件を確認',
    moreCollapse: '折りたたむ',
    moreExpand: 'さらに {count} 件…',
    buildingListAriaLabel: '候補建物リスト（全 {total} 件{recPart}）',
    buildingListRecPart: '、推薦 {count} 件を含む',
    recBadgeTitle: 'AIが推薦した建物',
    recBadgeText: '★ 推薦',
    sunBadgeTitle: '冬至南中でも日照を確保',
    itemRecPrefix: '推薦建物、',
    itemBuilding: '建物 {id}',
    itemSunlitSuffix: '、冬日照あり',
    distStation: '駅 {m}m',
    mapCandidateCount: '候補 {n} 件',
    popupRecBadge: '★ AI 推薦',
    popupNoData: 'データなし',
    popupRiskLabel: '{depth}m（ランク {rank}）',
    popupSunlitYes: '○（冬至南中でも確保）',
    popupSunlitNo: '×（南側に遮蔽あり）',
    popupUsage: '用途',
    popupHeight: '高さ',
    popupStoreys: '階数',
    popupStoreysUnit: '{n}階',
    popupHtRisk: '高潮リスク',
    popupOrientation: '壁面方位',
    popupWinterSun: '冬の日当たり',
    popupRoof: '屋根',
    popupGroundElev: '地面標高',
    popupNearestStation: '最寄り駅',
    popupNearestShelter: '最寄り避難所',
    popupNearestSchool: '最寄り学校',
    popupNearestHospital: '最寄り病院',
    popupMajorRoad: '幹線道路まで',
    popupScore: '類似度スコア: {score}',
  },
  en: {
    appTitle: 'Hiroshima Building RAG',
    appEyebrow: 'HIROSHIMA · PLATEAU 3D BUILDING SEARCH',
    skipLink: 'Skip to main content',
    darkModeToggle: 'Switch to dark mode',
    lightModeToggle: 'Switch to light mode',
    langToggle: '日本語',
    mapPanelAriaLabel: 'Candidate building map',
    mapToolbarAriaLabel: 'Map controls',
    mapSheetExpandAriaLabel: 'Expand map',
    mapSheetCollapseBtnAriaLabel: 'Collapse map',
    mapAriaLabel: 'Map showing building locations',
    mapAttribution: 'Buildings: adapted from MLIT City Bureau "3D City Model (Project PLATEAU) Hiroshima City (FY2022)" (CC BY 4.0) / Basemap: OpenStreetMap. Buildings constructed after data acquisition are not shown or searchable.',
    mapCloseBtn: '× Close',
    mapCloseBtnAriaLabel: 'Close map',
    chatPanelAriaLabel: 'Building search chat',
    messageListAriaLabel: 'Conversation history',
    welcomeTitle: 'Search buildings in Hiroshima',
    welcomeHint: 'Ask a question in natural language to get building suggestions based on disaster risk and location conditions.',
    welcomeAttribution: '* Building data is adapted from MLIT City Bureau "3D City Model (Project PLATEAU) Hiroshima City (FY2022)" (CC BY 4.0); buildings constructed afterward are not searchable.',
    exampleListAriaLabel: 'Example questions',
    example1Label: 'Low storm surge risk, near a station',
    example1Query: 'Show me buildings with low storm surge risk that are near a station',
    example2Label: 'Fire-resistant, near a shelter',
    example2Query: 'Where are fire-resistant buildings near an evacuation shelter?',
    example3Label: 'Low tsunami and flood risk',
    example3Query: 'Show me buildings with both low tsunami and flood risk',
    queryInputLabel: 'Enter your question (required)',
    queryInputPlaceholder: 'e.g., Which buildings have low storm surge risk and are near a station?',
    submitBtnAriaLabel: 'Run search',
    queryHint: 'Enter disaster-risk conditions, distance, structure, etc. in natural language, then press Enter or the submit button to search. Shift+Enter inserts a line break.',
    topkLabel: 'Count:',
    topkSelectAriaLabel: 'Number of results',
    topk5: '5',
    topk10: '10',
    topk20: '20',
    embeddingLabel: 'Embedding:',
    embeddingSelectAriaLabel: 'Embedding model to use',
    embeddingRuriOption: 'RURI v3 310m (local)',
    themeDarkAnnounce: 'Switched to dark mode',
    themeLightAnnounce: 'Switched to light mode',
    langSwitchAnnounce: 'Display language changed',
    mapOpenedAnnounce: 'Map opened. Showing {count} candidate building(s).',
    mapClosedAnnounce: 'Map closed.',
    mapSheetPeekAnnounce: 'Map shown at the bottom of the screen.',
    mapSheetHalfAnnounce: 'Map expanded.',
    mapSheetFullAnnounce: 'Map expanded to nearly full screen.',
    generatingAnnounce: 'Generating answer...',
    resultWithCountAnnounce: 'Answer generated. Found {count} candidate building(s).',
    resultNoCountAnnounce: 'Answer generated.',
    unknownError: 'An unknown error occurred',
    errorPrefix: 'Error: {msg}',
    errorAnnounce: 'An error occurred: {msg}',
    youAriaLabel: 'You: {text}',
    aiGeneratingAriaLabel: 'AI generating answer',
    aiAnswerAriaLabel: 'AI answer',
    metaText: '{count} results | {sec}s',
    mapButtonAriaLabel: 'Check {count} candidate buildings on the map',
    mapButtonText: '🗺 View {count} on map',
    moreCollapse: 'Collapse',
    moreExpand: '{count} more…',
    buildingListAriaLabel: 'Candidate building list ({total} total{recPart})',
    buildingListRecPart: ', including {count} recommended',
    recBadgeTitle: 'AI-recommended building',
    recBadgeText: '★ Recommended',
    sunBadgeTitle: 'Sunlight secured even at winter solstice noon',
    itemRecPrefix: 'Recommended building, ',
    itemBuilding: 'Building {id}',
    itemSunlitSuffix: ', winter sunlight secured',
    distStation: 'Station {m}m',
    mapCandidateCount: '{n} candidates',
    popupRecBadge: '★ AI Recommended',
    popupNoData: 'No data',
    popupRiskLabel: '{depth}m (rank {rank})',
    popupSunlitYes: '○ (secured even at winter solstice noon)',
    popupSunlitNo: '× (blocked to the south)',
    popupUsage: 'Usage',
    popupHeight: 'Height',
    popupStoreys: 'Floors',
    popupStoreysUnit: '{n} floors',
    popupHtRisk: 'Storm surge risk',
    popupOrientation: 'Wall orientation',
    popupWinterSun: 'Winter sunlight',
    popupRoof: 'Roof',
    popupGroundElev: 'Ground elevation',
    popupNearestStation: 'Nearest station',
    popupNearestShelter: 'Nearest shelter',
    popupNearestSchool: 'Nearest school',
    popupNearestHospital: 'Nearest hospital',
    popupMajorRoad: 'To major road',
    popupScore: 'Similarity score: {score}',
  },
};

export function t(lang: Lang, key: string, params?: Record<string, string | number>): string {
  let str = UI_STRINGS[lang][key] ?? UI_STRINGS.ja[key] ?? key;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      str = str.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v));
    }
  }
  return str;
}

/**
 * An English translation dictionary for the DB's enumerated values (usage,
 * structure, fire resistance, flood-depth rank, roof type, shape
 * classification, direction, facility category, hazard type). Covers only
 * values confirmed against the real data (output/plateau_rag.duckdb).
 * Proper nouns (station names, facility names, etc.) aren't included here —
 * translateValue() returns them as-is as unregistered values.
 */
export const VALUE_LABELS: Record<string, string> = {
  // usage
  'その他': 'Other',
  '不明': 'Unknown',
  '住宅': 'Residential',
  '供給処理施設': 'Utility facility',
  '共同住宅': 'Apartment',
  '商業施設': 'Commercial facility',
  '商業系複合施設': 'Mixed commercial complex',
  '官公庁施設': 'Government facility',
  '宿泊施設': 'Lodging facility',
  '店舗等併用住宅': 'Residence with shop',
  '店舗等併用共同住宅': 'Apartment with shop',
  '文教厚生施設': 'Educational/welfare facility',
  '業務施設': 'Business facility',
  '運輸倉庫施設': 'Transport/warehouse facility',
  // structure_type
  'レンガ造・コンクリートブロック造・石造': 'Brick / concrete block / stone',
  '木造・土蔵造': 'Wood / traditional storehouse',
  '軽量鉄骨造': 'Light-gauge steel',
  '鉄筋コンクリート造': 'Reinforced concrete',
  '鉄骨造': 'Steel frame',
  '鉄骨鉄筋コンクリート造': 'Steel-reinforced concrete',
  // fire_proof
  '準耐火造': 'Semi-fire-resistant',
  '耐火': 'Fire-resistant',
  // risk rank
  '0.5m未満': '< 0.5m',
  '0.5m以上3m未満': '0.5–3m',
  '3m以上5m未満': '3–5m',
  '5m以上10m未満': '5–10m',
  // roof_type_est
  '勾配屋根': 'Sloped roof',
  '陸屋根': 'Flat roof',
  // shape_type_est
  'L字型': 'L-shape',
  'コの字型・T字型': 'U-shape / T-shape',
  '円形に近い': 'Near-circular',
  '十字型・複雑形状': 'Cross-shape / complex',
  '星形・複雑形状': 'Star-shape / complex',
  '楕円形': 'Ellipse',
  '矩形・単純形状': 'Rectangle / simple',
  // directions
  '北': 'N',
  '東': 'E',
  '南': 'S',
  '西': 'W',
  // hazard names
  '高潮': 'Storm surge',
  '洪水': 'Flood',
  '津波': 'Tsunami',
  // facility categories
  '駅': 'Station',
  '避難所': 'Shelter',
  '公園': 'Park',
  '緊急輸送道路': 'Emergency route',
  'ランドマーク': 'Landmark',
  '学校': 'School',
  '病院': 'Hospital',
  '警察署': 'Police station',
  '消防署': 'Fire station',
  '郵便局': 'Post office',
};

/** Translate a DB-sourced Japanese value to English. Returns it unchanged for lang='ja' or unregistered values. */
export function translateValue(lang: Lang, ja: string | null | undefined): string {
  if (lang === 'ja' || ja == null) return ja ?? '';
  return VALUE_LABELS[ja] ?? ja;
}

/**
 * Bulk-update the text/attributes of every element carrying a data-i18n /
 * data-i18n-placeholder / data-i18n-aria-label / data-i18n-query attribute
 * (the same "toggle button + bulk update" pattern as theme.ts's applyTheme()).
 */
export function applyStaticTranslations(lang: Lang): void {
  document.documentElement.setAttribute('lang', lang);

  document.querySelectorAll<HTMLElement>('[data-i18n]').forEach(el => {
    const key = el.dataset['i18n'];
    if (key) el.textContent = t(lang, key);
  });
  document.querySelectorAll<HTMLElement>('[data-i18n-placeholder]').forEach(el => {
    const key = el.dataset['i18nPlaceholder'];
    if (key) el.setAttribute('placeholder', t(lang, key));
  });
  document.querySelectorAll<HTMLElement>('[data-i18n-aria-label]').forEach(el => {
    const key = el.dataset['i18nAriaLabel'];
    if (key) el.setAttribute('aria-label', t(lang, key));
  });
  document.querySelectorAll<HTMLElement>('[data-i18n-query]').forEach(el => {
    const key = el.dataset['i18nQuery'];
    if (key) el.setAttribute('data-query', t(lang, key));
  });

  const langBtn = document.getElementById('lang-toggle');
  if (langBtn) langBtn.textContent = t(lang, 'langToggle');
}

/** Determine and apply the initial language. */
export function initLang(): void {
  const saved = localStorage.getItem(STORAGE_KEY) as Lang | null;
  const lang: Lang = saved ?? 'ja';
  applyStaticTranslations(lang);
  store.set({ language: lang });
}

/** Toggle the language. */
export function toggleLang(): void {
  const next: Lang = store.get().language === 'ja' ? 'en' : 'ja';
  applyStaticTranslations(next);
  store.set({ language: next });
  localStorage.setItem(STORAGE_KEY, next);
}
