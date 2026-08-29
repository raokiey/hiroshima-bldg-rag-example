/**
 * mapColor.ts — dynamically picks the map's fill color scheme per query.
 *
 * From the ParsedQuery (the `parsed_query` the backend returns from
 * /api/search), picks one attribute the query actually asked about, by
 * priority, and decides the map's coloring policy (ColorSpec). Falls back
 * to a neutral color when no matching attribute is found (e.g. a
 * semantic-only query).
 *
 * A pure-function module depending only on MapLibre's types and
 * ParsedQueryDto (./api) — no DOM access (a thin logic layer called from map.ts).
 */

import type { ParsedQueryDto } from './api';
import type { Lang } from './i18n';

export type ColorMode =
  | 'risk' | 'gradient' | 'derived-margin'
  | 'boolean-sunlight' | 'categorical-roof' | 'neutral';

/** One legend entry. For 'discrete', one color = one condition; for 'gradient', the two endpoint colors+labels. */
export interface LegendEntry {
  color: string;
  label: string;
}

export interface ColorSpec {
  mode: ColorMode;
  key?: string;              // Property name referenced by gradient/risk.
  domain?: [number, number]; // gradient/derived-margin only.
  legendText: string;        // Explanation shown in the map overlay (what's being colored).
  /**
   * Legend entries spelling out each color's condition (like a QGIS layer
   * legend, so the color-to-condition mapping is clear at a glance).
   * legendType='discrete' is an array of independent swatches, used by
   * risk/boolean/categorical/neutral. legendType='gradient' is a 2-element
   * array ([0] = low-end color+label, [1] = high-end color+label), used by
   * gradient/derived-margin — the caller renders it as a gradient bar.
   */
  legendEntries: LegendEntry[];
  legendType: 'discrete' | 'gradient';
}

const GRADIENT_LOW = '#b2dfdb';
const GRADIENT_HIGH = '#00695c';
const SUNLIT_COLOR = '#ffb300';
const NOT_SUNLIT_COLOR = '#9e9e9e';
const ROOF_FLAT_COLOR = '#5c6bc0';
const ROOF_SLOPED_COLOR = '#8d6e63';
export const NEUTRAL_COLOR = '#78909c';

const HAZARD_LABEL: Record<Lang, Record<string, string>> = {
  ja: { ht: '高潮', rv: '洪水', ts: '津波' },
  en: { ht: 'storm surge', rv: 'flood', ts: 'tsunami' },
};
const DIR_LABEL: Record<Lang, Record<string, string>> = {
  ja: { n: '北', e: '東', s: '南', w: '西' },
  en: { n: 'north', e: 'east', s: 'south', w: 'west' },
};
const FACILITY_LABEL: Record<Lang, Record<string, string>> = {
  ja: {
    station: '駅', shelter: '避難所', park: '公園', emroute: '緊急輸送道路',
    landmark: 'ランドマーク', school: '学校', hospital: '病院',
    police: '警察署', fire: '消防署', post: '郵便局',
  },
  en: {
    station: 'station', shelter: 'shelter', park: 'park', emroute: 'emergency route',
    landmark: 'landmark', school: 'school', hospital: 'hospital',
    police: 'police station', fire: 'fire station', post: 'post office',
  },
};
const SORT_KEY_LABEL: Record<Lang, Record<string, { label: string; unit: string }>> = {
  ja: {
    measured_height:   { label: '建物高さ', unit: 'm' },
    storeys:           { label: '階数', unit: '階' },
    ground_elev_m:     { label: '地面標高', unit: 'm' },
    prominence_m:      { label: '周囲との高低差（突出度）', unit: 'm' },
    roof_area_m2:      { label: '屋根面積', unit: 'm2' },
    volume_m3:         { label: '建物体積', unit: 'm3' },
    footprint_area_m2: { label: '敷地（底面積）', unit: 'm2' },
    slenderness:       { label: '細長さ指数', unit: '' },
  },
  en: {
    measured_height:   { label: 'Building height', unit: 'm' },
    storeys:           { label: 'Floors', unit: '' },
    ground_elev_m:     { label: 'Ground elevation', unit: 'm' },
    prominence_m:      { label: 'Prominence over surroundings', unit: 'm' },
    roof_area_m2:      { label: 'Roof area', unit: 'm2' },
    volume_m3:         { label: 'Building volume', unit: 'm3' },
    footprint_area_m2: { label: 'Footprint area', unit: 'm2' },
    slenderness:       { label: 'Slenderness index', unit: '' },
  },
};

function _sortKeyLabel(lang: Lang, key: string): { label: string; unit: string } {
  if (SORT_KEY_LABEL[lang][key]) return SORT_KEY_LABEL[lang][key]!;
  const m = /^nearest_(\w+)_dist_m$/.exec(key);
  if (m) {
    const facility = FACILITY_LABEL[lang][m[1]!] ?? m[1];
    return lang === 'en'
      ? { label: `Distance to ${facility}`, unit: 'm' }
      : { label: `${facility}までの距離`, unit: 'm' };
  }
  return { label: key, unit: '' };  // Fallback for an unknown key (e.g. a future new column).
}

function _fmt(n: number): string {
  const r = Math.round(n * 10) / 10;
  return Number.isInteger(r) ? String(r) : r.toFixed(1);
}

/**
 * Compute the [min, max] range of a given getter's values across the
 * search result's GeoJSON features. MapLibre's `interpolate` requires
 * strictly increasing stop values, so when every value is identical
 * (min===max), max is bumped by +1 to avoid that. Returns [0, 1] when no
 * feature has a valid value.
 */
function _domain(
  features: GeoJSON.Feature[],
  getter: (p: Record<string, unknown>) => number | null,
): [number, number] {
  let min = Infinity;
  let max = -Infinity;
  for (const f of features) {
    const v = getter((f.properties ?? {}) as Record<string, unknown>);
    if (v == null || Number.isNaN(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (max <= min) max = min + 1;
  return [min, max];
}

/**
 * Compute vertical evacuation's "height margin over flood depth" (JS side).
 * Must stay in sync with colorExprFor()'s 'derived-margin' case, which
 * expresses the same logic (coalesce -> max -> subtract) as a MapLibre expression.
 */
function _evacMarginJs(p: Record<string, unknown>): number {
  const h = p['measured_height'] != null ? Number(p['measured_height']) : 0;
  const depths = ['ht_depth_max', 'rv_depth_max', 'ts_depth_max']
    .map(k => (p[k] != null ? Number(p[k]) : 0));
  return h - Math.max(...depths);
}

/**
 * Decide the map's coloring policy from a ParsedQuery.
 * Priority order (do not change this order):
 *   1. Risk condition (risk_filters first, else sort_by on a *_depth_max key)
 *   2. sort_by (non-risk) -> generic gradient
 *   3. Orientation filter
 *   4. Sunlight
 *   5. Quiet
 *   6. Vertical evacuation
 *   7. Dense wooden construction
 *   8. Roof type
 *   9. No match -> fall back to neutral color
 *
 * Higher priority = "a specific condition the query explicitly asked
 * about"; lower priority = "an incidental sort specification".
 */
export function determineColorSpec(
  pq: ParsedQueryDto | null,
  features: GeoJSON.Feature[],
  lang: Lang = 'ja',
): ColorSpec {
  const NEUTRAL: ColorSpec = {
    mode: 'neutral',
    legendText: lang === 'en'
      ? 'No color coding (only recommended buildings highlighted)'
      : '色分けなし（推薦建物のみアクセント色で強調表示）',
    legendEntries: [],
    legendType: 'discrete',
  };
  if (!pq) return NEUTRAL;

  // 1. Risk condition.
  // risk_filters can hold multiple entries, but since map coloring is
  // limited to one attribute, only the first is used (compositing multiple
  // hazards is out of scope). Taken regardless of mode ("none"/"max_depth")
  // — even an exclusion condition is worth visualizing, since the query
  // mentioned that hazard type at all.
  const riskFromFilters = pq.risk_filters[0]?.hazard;
  const riskFromSort = /^(ht|rv|ts)_depth_max$/
    .exec(pq.sort_by?.key ?? '')?.[1] as 'ht' | 'rv' | 'ts' | undefined;
  const hazard = riskFromFilters ?? riskFromSort;
  if (hazard) {
    return {
      mode: 'risk',
      key: `${hazard}_depth_max`,
      legendText: lang === 'en'
        ? `Color: ${HAZARD_LABEL.en[hazard]} flood risk (max projected depth)`
        : `色: ${HAZARD_LABEL.ja[hazard]}浸水リスク（最大浸水想定深）`,
      legendEntries: lang === 'en'
        ? [
            { color: '#2e7d32', label: '< 0.5m' },
            { color: '#f57c00', label: '0.5–5m' },
            { color: '#c62828', label: '≥ 5m' },
          ]
        : [
            { color: '#2e7d32', label: '0.5m未満' },
            { color: '#f57c00', label: '0.5m以上5m未満' },
            { color: '#c62828', label: '5m以上' },
          ],
      legendType: 'discrete',
    };
  }

  // 2. sort_by (non-risk) -> generic gradient.
  if (pq.sort_by?.key) {
    const key = pq.sort_by.key;
    const { label, unit } = _sortKeyLabel(lang, key);
    const domain = _domain(features, p => (p[key] != null ? Number(p[key]) : null));
    return {
      mode: 'gradient', key, domain,
      legendText: lang === 'en' ? `Color: ${label}` : `色: ${label}`,
      legendEntries: [
        { color: GRADIENT_LOW, label: `${_fmt(domain[0])}${unit}` },
        { color: GRADIENT_HIGH, label: `${_fmt(domain[1])}${unit}` },
      ],
      legendType: 'gradient',
    };
  }

  // 3. Orientation filter.
  if (pq.orientation_filters.length > 0) {
    const dir = pq.orientation_filters[0]!.direction;
    return {
      mode: 'gradient', key: `wall_ratio_${dir}`, domain: [0, 1],
      legendText: lang === 'en'
        ? `Color: ${DIR_LABEL.en[dir]}-facing wall ratio`
        : `色: ${DIR_LABEL.ja[dir]}向き壁面の比率`,
      legendEntries: lang === 'en'
        ? [
            { color: GRADIENT_LOW, label: '0% (low)' },
            { color: GRADIENT_HIGH, label: '100% (high)' },
          ]
        : [
            { color: GRADIENT_LOW, label: '0%（比率低い）' },
            { color: GRADIENT_HIGH, label: '100%（比率高い）' },
          ],
      legendType: 'gradient',
    };
  }

  // 4. Sunlight.
  if (pq.sunlight === true) {
    return {
      mode: 'boolean-sunlight',
      legendText: lang === 'en' ? 'Color: Winter sunlight' : '色: 冬の日当たり確保',
      legendEntries: lang === 'en'
        ? [
            { color: SUNLIT_COLOR, label: 'Secured (sunlight even at winter solstice noon)' },
            { color: NOT_SUNLIT_COLOR, label: 'Not secured (blocked to the south)' },
          ]
        : [
            { color: SUNLIT_COLOR, label: '確保（冬至南中でも日照あり）' },
            { color: NOT_SUNLIT_COLOR, label: '未確保（南側に遮蔽あり）' },
          ],
      legendType: 'discrete',
    };
  }

  // 5. Quiet.
  if (pq.quiet === true) {
    const domain = _domain(features, p =>
      (p['nearest_major_road_dist_m'] != null ? Number(p['nearest_major_road_dist_m']) : null));
    return {
      mode: 'gradient', key: 'nearest_major_road_dist_m', domain,
      legendText: lang === 'en'
        ? 'Color: Distance to major road (quietness indicator)'
        : '色: 幹線道路までの距離（静けさの目安）',
      legendEntries: lang === 'en'
        ? [
            { color: GRADIENT_LOW, label: `${_fmt(domain[0])}m (close to road)` },
            { color: GRADIENT_HIGH, label: `${_fmt(domain[1])}m (far from road = quiet)` },
          ]
        : [
            { color: GRADIENT_LOW, label: `${_fmt(domain[0])}m（道路に近い）` },
            { color: GRADIENT_HIGH, label: `${_fmt(domain[1])}m（道路から遠い＝静か）` },
          ],
      legendType: 'gradient',
    };
  }

  // 6. Vertical evacuation.
  if (pq.vertical_evacuation === true) {
    const domain = _domain(features, p => _evacMarginJs(p));
    return {
      mode: 'derived-margin', domain,
      legendText: lang === 'en'
        ? 'Color: Height margin over flood depth'
        : '色: 浸水深に対する高さの余裕',
      legendEntries: lang === 'en'
        ? [
            { color: GRADIENT_LOW, label: `${_fmt(domain[0])}m (small margin)` },
            { color: GRADIENT_HIGH, label: `${_fmt(domain[1])}m (large margin)` },
          ]
        : [
            { color: GRADIENT_LOW, label: `${_fmt(domain[0])}m（余裕小さい）` },
            { color: GRADIENT_HIGH, label: `${_fmt(domain[1])}m（余裕大きい）` },
          ],
      legendType: 'gradient',
    };
  }

  // 7. Dense wooden construction.
  if (pq.wooden_dense === true) {
    return {
      mode: 'gradient', key: 'wooden_density_ratio', domain: [0, 1],
      legendText: lang === 'en'
        ? 'Color: Wooden building ratio within 100m'
        : '色: 周辺100m圏の木造建物比率',
      legendEntries: lang === 'en'
        ? [
            { color: GRADIENT_LOW, label: '0% (low density)' },
            { color: GRADIENT_HIGH, label: '100% (high density)' },
          ]
        : [
            { color: GRADIENT_LOW, label: '0%（密集度低い）' },
            { color: GRADIENT_HIGH, label: '100%（密集度高い）' },
          ],
      legendType: 'gradient',
    };
  }

  // 8. Roof type.
  if (pq.roof_type) {
    return {
      mode: 'categorical-roof',
      legendText: lang === 'en' ? 'Color: Roof type' : '色: 屋根種別',
      legendEntries: lang === 'en'
        ? [
            { color: ROOF_FLAT_COLOR, label: 'Flat roof' },
            { color: ROOF_SLOPED_COLOR, label: 'Sloped roof' },
          ]
        : [
            { color: ROOF_FLAT_COLOR, label: '陸屋根' },
            { color: ROOF_SLOPED_COLOR, label: '勾配屋根' },
          ],
      legendType: 'discrete',
    };
  }

  // 9. No match (a semantic-only query, etc.) -> fall back to neutral color.
  return NEUTRAL;
}

/**
 * Build (part of) a MapLibre fill-extrusion-color expression from a
 * ColorSpec. The caller (map.ts) combines this with its hover/recommended
 * checks and uses it as the final fallback value in its case expression.
 *
 * The risk threshold is 5.0 (not 2.0) to match PLATEAU's official rank
 * codelist — consistent with the existing candidate-list badge logic that
 * treats rank 4 ("5m to under 10m") and above as "high risk".
 */
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
      // Same logic as _evacMarginJs() (coalesce -> max -> subtract).
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
