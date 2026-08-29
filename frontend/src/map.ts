/** MapManager — MapLibre GL JS initialization, GeoJSON layer, and theme sync. */

import maplibregl from 'maplibre-gl';
import { store } from './store';
import { getMapStyle } from './theme';
import { determineColorSpec, colorExprFor, type ColorSpec } from './mapColor';
import type { ParsedQueryDto } from './api';
import { t, translateValue } from './i18n';

const SOURCE_ID = 'buildings';
const LAYER_3D = 'buildings-3d';

// MapLibre paint expressions can't resolve CSS variables, so the accent
// color is duplicated here as a constant.
// Must match style.css's --depth token exactly — keep both in sync when
// changing either one.
const ACCENT_COLOR = { light: '#0e7c86', dark: '#57c8d1' } as const;
const HOVER_COLOR = '#ffeb3b';  // Carried over from the old buildings-highlight color.

let map: maplibregl.Map | null = null;
let currentPopup: maplibregl.Popup | null = null;
let pendingGeojson: GeoJSON.FeatureCollection | null = null;
let pendingParsedQuery: ParsedQueryDto | null = null;
let hoveredId: string | number | null = null;
// What the query-driven dynamic coloring (mapColor.ts) is currently keying
// its fill color off of. Read by _fillExtrusionColorExpr().
let currentColorSpec: ColorSpec = {
  mode: 'neutral', legendText: '色分けなし', legendEntries: [], legendType: 'discrete',
};
// Holds the most recently set GeoJSON, so focusBuilding() can look a
// building up by id when the candidate list is clicked.
let currentGeojson: GeoJSON.FeatureCollection | null = null;

/** Initialize MapLibre. */
export function initMap(): void {
  const theme = store.get().theme;

  map = new maplibregl.Map({
    container: 'map',
    style: getMapStyle(theme),
    center: [132.4597, 34.3853],  // Around Hiroshima Castle.
    zoom: 13,
    // Starts as a straight-down 2D view (pitch:0). The 3D extrusion look
    // itself is still provided by the fill-extrusion layer definition
    // (_addBuildingLayers) — users can switch to 3D anytime via
    // NavigationControl's pitch control (visualizePitch) or by dragging.
    pitch: 0,
  });

  map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
  map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right');
  // Map attribution (MapLibre/OpenFreeMap/OpenStreetMap credits). Placed at
  // top-left since .map-overlay occupies the bottom band.
  map.addControl(new maplibregl.AttributionControl({ compact: true }), 'top-left');

  map.on('load', () => {
    _addBuildingLayers();
    _hideBasemapBuildings();
    if (pendingGeojson) {
      setGeojson(pendingGeojson, pendingParsedQuery);
      pendingGeojson = null;
      pendingParsedQuery = null;
    }
  });

  // Clicking a building shows its popup and zooms in on it.
  map.on('click', LAYER_3D, (e) => {
    const feat = e.features?.[0];
    if (!feat) return;
    _showPopup(feat as GeoJSON.Feature, e.lngLat);
    const bounds = _boundsOfFeatures([feat as GeoJSON.Feature]);
    if (bounds && map) map.fitBounds(bounds, { padding: 100, maxZoom: 19, duration: 800 });
  });

  map.on('mouseenter', LAYER_3D, () => {
    if (map) map.getCanvas().style.cursor = 'pointer';
  });
  map.on('mouseleave', LAYER_3D, () => {
    if (map) map.getCanvas().style.cursor = '';
  });
}

/**
 * Set the search result's GeoJSON and reflect it on the map. Recomputes
 * currentColorSpec from parsedQuery each time, updating fill-extrusion-color
 * and the map's legend text.
 */
export function setGeojson(geojson: GeoJSON.FeatureCollection, parsedQuery: ParsedQueryDto | null = null): void {
  if (!map || !map.isStyleLoaded()) {
    pendingGeojson = geojson;
    pendingParsedQuery = parsedQuery;
    return;
  }

  const lang = store.get().language;
  currentColorSpec = determineColorSpec(parsedQuery, geojson.features, lang);
  currentGeojson = geojson;

  const src = map.getSource(SOURCE_ID) as maplibregl.GeoJSONSource | undefined;
  if (src) {
    src.setData(geojson);
    if (map.getLayer(LAYER_3D)) {
      map.setPaintProperty(LAYER_3D, 'fill-extrusion-color', _fillExtrusionColorExpr(ACCENT_COLOR[store.get().theme]));
    }
  } else {
    // promoteId makes properties.id the feature-state key, needed for the
    // setFeatureState-based hover effect.
    map.addSource(SOURCE_ID, { type: 'geojson', data: geojson, promoteId: 'id' });
    _addBuildingLayers();
    _hideBasemapBuildings();
  }
  hoveredId = null;

  // fitBounds to the bbox of all candidates.
  const bounds = _boundsOfFeatures(geojson.features);
  if (bounds) {
    // 3D extrusion stretches buildings upward, so extra top padding keeps
    // tall buildings from getting cut off at the top of the screen.
    map.fitBounds(bounds, {
      padding: { top: 120, bottom: 60, left: 60, right: 60 }, maxZoom: 16, duration: 600,
    });
  }

  // Result count display (desktop/tablet overlay + the mobile sheet's grab bar).
  const countText = t(lang, 'mapCandidateCount', { n: geojson.features.length });
  const countEl = document.getElementById('map-result-count');
  if (countEl) countEl.textContent = countText;
  const sheetCountEl = document.getElementById('map-sheet-count');
  if (sheetCountEl) sheetCountEl.textContent = countText;

  // Update the dynamic-coloring legend (a QGIS-style legend spelling out
  // each color's condition, replacing the old text-only version).
  const legendEl = document.getElementById('map-color-legend');
  if (legendEl) legendEl.innerHTML = _renderLegendHtml(currentColorSpec);
}

/**
 * Build the legend HTML from a ColorSpec. legendType='discrete' lists color
 * swatches with labels; 'gradient' shows a two-color gradient bar with a
 * label at each end (following QGIS layer legends: spell out each color's
 * condition, not just a "Color: ..." caption).
 */
function _renderLegendHtml(spec: ColorSpec): string {
  const caption = `<span class="map-color-legend__caption">${_esc(spec.legendText)}</span>`;

  if (spec.legendEntries.length === 0) {
    return caption;
  }

  if (spec.legendType === 'gradient') {
    const [low, high] = spec.legendEntries;
    return `
      ${caption}
      <div class="map-color-legend__gradient-wrap">
        <span>${_esc(low!.label)}</span>
        <span class="map-color-legend__gradient-bar"
              style="background:linear-gradient(to right, ${low!.color}, ${high!.color})"></span>
        <span>${_esc(high!.label)}</span>
      </div>
    `;
  }

  const items = spec.legendEntries.map(e => `
    <span class="map-color-legend__item">
      <span class="map-color-legend__swatch" style="background:${e.color}"></span>${_esc(e.label)}
    </span>
  `).join('');
  return `${caption}<div class="map-color-legend__items">${items}</div>`;
}

/**
 * Highlight a building by id (candidate-list hover linkage).
 * fill-extrusion has no outline-equivalent filter expression and
 * fill-extrusion-opacity doesn't support data-driven values, so hover is
 * expressed via setFeatureState + a fill-extrusion-color case expression
 * (see _addBuildingLayers) rather than setFilter.
 */
export function highlightBuilding(id: string | null): void {
  if (!map || !map.getSource(SOURCE_ID)) return;

  if (hoveredId != null) {
    map.setFeatureState({ source: SOURCE_ID, id: hoveredId }, { hover: false });
    hoveredId = null;
  }
  if (id != null) {
    map.setFeatureState({ source: SOURCE_ID, id }, { hover: true });
    hoveredId = id;
  }
}

/**
 * Zoom in on one candidate building (clicking a candidate zooms in far
 * enough to identify it). Looks it up by id in currentGeojson (whatever
 * setGeojson() last set), so this is a no-op if setGeojson() hasn't run yet
 * or the map is still waiting on style load with data stuck in
 * pendingGeojson (currentGeojson not yet updated) — callers must call
 * setGeojson() first.
 */
export function focusBuilding(id: string): void {
  if (!map || !currentGeojson) return;
  const feat = currentGeojson.features.find(f => String((f.properties ?? {})['id'] ?? '') === id);
  if (!feat) return;
  const bounds = _boundsOfFeatures([feat]);
  if (!bounds) return;
  map.fitBounds(bounds, { padding: 100, maxZoom: 19, duration: 800 });
}

/** Switch the map style when the theme changes. */
export function applyMapTheme(theme: 'light' | 'dark'): void {
  if (!map) return;
  map.setStyle(getMapStyle(theme));
  // setStyle() discards layers and layout settings, so they're re-applied
  // once the new style finishes loading.
  map.once('styledata', () => {
    _hideBasemapBuildings();
    if (pendingGeojson) {
      setGeojson(pendingGeojson, pendingParsedQuery);
      pendingGeojson = null;
      pendingParsedQuery = null;
    } else {
      const current = store.get().activeGeojson;
      const currentPq = store.get().activeParsedQuery;
      if (current) setGeojson(current, currentPq);
    }
    _applyAccentColor(theme);
  });
}

/** Resize the map (call after toggling panel visibility). */
export function resizeMap(): void {
  map?.resize();
}

// ============================================================
// Internal helpers
// ============================================================

/**
 * Return the bbox of `features` as [[minLon,minLat],[maxLon,maxLat]] —
 * shared by setGeojson()'s all-candidates fit and focusBuilding()'s
 * single-building fit. Returns null if no coordinates could be extracted.
 */
function _boundsOfFeatures(features: GeoJSON.Feature[]): [[number, number], [number, number]] | null {
  const coords = features.flatMap(f => {
    const g = f.geometry;
    if (g.type === 'Polygon') return g.coordinates[0]!;
    if (g.type === 'MultiPolygon') return g.coordinates.flatMap(p => p[0]!);
    return [];
  });
  if (coords.length === 0) return null;
  const lons = coords.map(c => c[0]!);
  const lats = coords.map(c => c[1]!);
  return [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]];
}

/**
 * Build the fill-extrusion-color case expression, driven by the
 * query-driven dynamic coloring (mapColor.ts). Priority order: hovered ->
 * recommended building -> the semantic color currentColorSpec decided
 * (risk/gradient/sunlight/roof-type/neutral).
 */
function _fillExtrusionColorExpr(accentColor: string): maplibregl.ExpressionSpecification {
  return [
    'case',
    ['boolean', ['feature-state', 'hover'], false], HOVER_COLOR,
    ['boolean', ['get', 'is_recommended'], false], accentColor,
    colorExprFor(currentColorSpec),
  ] as unknown as maplibregl.ExpressionSpecification;
}

function _addBuildingLayers(): void {
  if (!map) return;
  if (map.getSource(SOURCE_ID) === undefined) return;

  if (!map.getLayer(LAYER_3D)) {
    const theme = store.get().theme;
    map.addLayer({
      id: LAYER_3D,
      type: 'fill-extrusion',
      source: SOURCE_ID,
      paint: {
        // Clamp invalid values (-9999) and NULL to a minimum of 3m, so they
        // don't collapse flat into the ground (measured_height is valid for
        // 2,954 of the 2,958 buildings).
        'fill-extrusion-height': ['max', ['coalesce', ['get', 'measured_height'], 3], 3],
        'fill-extrusion-base': 0,
        'fill-extrusion-opacity': 0.85,
        'fill-extrusion-color': _fillExtrusionColorExpr(ACCENT_COLOR[theme]),
      },
    });
  }
}

/**
 * Hide OpenFreeMap's (liberty/dark) basemap building layer. Layer IDs
 * differ per style, so this checks source-layer instead (hardcoding an ID
 * would be fragile against style changes).
 */
function _hideBasemapBuildings(): void {
  if (!map) return;
  const layers = map.getStyle()?.layers ?? [];
  let hidden = 0;
  for (const layer of layers) {
    if ((layer as unknown as { 'source-layer'?: string })['source-layer'] === 'building') {
      map.setLayoutProperty(layer.id, 'visibility', 'none');
      hidden++;
    }
  }
  if (hidden === 0) {
    console.warn('[map] 背景地図の building レイヤーが見つからなかった（スタイル仕様変更の可能性）');
  }
}

/** Re-apply the accent color when the theme is switched. */
function _applyAccentColor(theme: 'light' | 'dark'): void {
  if (!map || !map.getLayer(LAYER_3D)) return;
  map.setPaintProperty(LAYER_3D, 'fill-extrusion-color', _fillExtrusionColorExpr(ACCENT_COLOR[theme]));
}

function _showPopup(feat: GeoJSON.Feature, lngLat: maplibregl.LngLat): void {
  if (!map) return;
  currentPopup?.remove();

  const lang = store.get().language;
  const p = (feat.properties ?? {}) as Record<string, unknown>;
  const riskClass = _riskClass(p['ht_rank_worst'] as string | null);
  const riskLabel = p['ht_depth_max'] != null
    ? t(lang, 'popupRiskLabel', { depth: String(p['ht_depth_max']), rank: String(p['ht_rank_worst'] ?? '-') })
    : t(lang, 'popupNoData');

  // Precomputed metadata (shown only when present).
  const orientation = _orientationLabel(p, lang);
  const sunlit = p['winter_sunlit'] != null
    ? (p['winter_sunlit'] ? t(lang, 'popupSunlitYes') : t(lang, 'popupSunlitNo'))
    : null;
  const facilityRow = (nameKey: string, distKey: string, label: string): string => {
    if (!p[nameKey]) return '';
    return `<dt>${label}</dt><dd>${_esc(String(p[nameKey]))}（${Math.round(Number(p[distKey]))}m）</dd>`;
  };

  const isRecommended = p['is_recommended'] === true;

  const html = `
    <div class="map-popup__title">
      ${isRecommended ? `<span class="rec-badge" title="${t(lang, 'recBadgeTitle')}">${t(lang, 'popupRecBadge')}</span> ` : ''}${_esc(String(p['id'] ?? '-'))}
    </div>
    <dl class="map-popup__props">
      <dt>${t(lang, 'popupUsage')}</dt><dd>${_esc(translateValue(lang, String(p['usage'] ?? '')) || t(lang, 'popupNoData'))}</dd>
      <dt>${t(lang, 'popupHeight')}</dt><dd>${p['measured_height'] != null ? `${p['measured_height']}m` : '-'}</dd>
      <dt>${t(lang, 'popupStoreys')}</dt><dd>${p['storeys'] != null ? t(lang, 'popupStoreysUnit', { n: String(p['storeys']) }) : '-'}</dd>
      <dt>${t(lang, 'popupHtRisk')}</dt>
      <dd><span class="risk-badge risk-badge--${riskClass}">${riskLabel}</span></dd>
      ${orientation ? `<dt>${t(lang, 'popupOrientation')}</dt><dd>${orientation}</dd>` : ''}
      ${sunlit ? `<dt>${t(lang, 'popupWinterSun')}</dt><dd>${sunlit}</dd>` : ''}
      ${p['roof_type_est'] ? `<dt>${t(lang, 'popupRoof')}</dt><dd>${_esc(translateValue(lang, String(p['roof_type_est'])))}</dd>` : ''}
      ${p['ground_elev_m'] != null ? `<dt>${t(lang, 'popupGroundElev')}</dt><dd>${Number(p['ground_elev_m']).toFixed(1)}m</dd>` : ''}
      <dt>${t(lang, 'popupNearestStation')}</dt>
      <dd>${p['nearest_station_name'] ? `${_esc(String(p['nearest_station_name']))}（${Math.round(Number(p['nearest_station_dist_m']))}m）` : '-'}</dd>
      <dt>${t(lang, 'popupNearestShelter')}</dt>
      <dd>${p['nearest_shelter_name'] ? `${_esc(String(p['nearest_shelter_name']))}（${Math.round(Number(p['nearest_shelter_dist_m']))}m）` : '-'}</dd>
      ${facilityRow('nearest_school_name', 'nearest_school_dist_m', t(lang, 'popupNearestSchool'))}
      ${facilityRow('nearest_hospital_name', 'nearest_hospital_dist_m', t(lang, 'popupNearestHospital'))}
      ${p['nearest_major_road_dist_m'] != null ? `<dt>${t(lang, 'popupMajorRoad')}</dt><dd>${Math.round(Number(p['nearest_major_road_dist_m']))}m</dd>` : ''}
    </dl>
    <p class="map-popup__score">${t(lang, 'popupScore', { score: p['score'] != null ? Number(p['score']).toFixed(3) : '-' })}</p>
  `;

  currentPopup = new maplibregl.Popup({ maxWidth: '300px', closeButton: true })
    .setLngLat(lngLat)
    .setHTML(html)
    .addTo(map);
}

function _riskClass(rank: string | null): string {
  if (!rank) return 'none';
  const n = parseInt(rank, 10);
  if (n >= 4) return 'high';
  if (n >= 2) return 'medium';
  return 'low';
}

/** Format all 4 wall orientation ratios compactly (e.g. 南30/北30/東20/西20). */
function _orientationLabel(p: Record<string, unknown>, lang: import('./i18n').Lang = 'ja'): string | null {
  const dirs: Array<[string, string]> = lang === 'en'
    ? [['S', 'wall_ratio_s'], ['N', 'wall_ratio_n'], ['E', 'wall_ratio_e'], ['W', 'wall_ratio_w']]
    : [['南', 'wall_ratio_s'], ['北', 'wall_ratio_n'], ['東', 'wall_ratio_e'], ['西', 'wall_ratio_w']];
  const parts = dirs
    .filter(([, key]) => p[key] != null)
    .map(([label, key]) => `${label}${Math.round(Number(p[key]) * 100)}`);
  return parts.length > 0 ? parts.join('/') : null;
}

function _esc(str: string): string {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
