/** ChatPanel — renders messages, the candidate building list, and map linkage. */

import { marked } from 'marked';
import DOMPurify from 'dompurify';
import type { Message } from './store';
import type { ParsedQueryDto } from './api';
import { highlightBuilding, focusBuilding } from './map';
import { t, type Lang } from './i18n';

marked.setOptions({ gfm: true, breaks: true });

/** Hide the welcome message. */
export function hideWelcome(): void {
  const el = document.getElementById('welcome-msg');
  if (el) el.remove();
}

/** Append a user message bubble. */
export function appendUserMessage(text: string, lang: Lang = 'ja'): void {
  const list = document.getElementById('message-list')!;
  const el = document.createElement('div');
  el.className = 'msg msg--user';
  el.setAttribute('role', 'article');
  el.setAttribute('aria-label', t(lang, 'youAriaLabel', { text }));
  el.innerHTML = `
    <div class="msg__avatar" aria-hidden="true">👤</div>
    <div class="msg__body">
      <div class="msg__bubble">${_esc(text)}</div>
    </div>
  `;
  list.appendChild(el);
  _scrollToBottom(list);
}

/** Append a loading bubble and return the element so it can be removed later. */
export function appendLoadingBubble(lang: Lang = 'ja'): HTMLElement {
  const list = document.getElementById('message-list')!;
  const el = document.createElement('div');
  el.className = 'msg msg--assistant';
  el.id = 'loading-bubble';
  el.setAttribute('aria-label', t(lang, 'aiGeneratingAriaLabel'));
  el.innerHTML = `
    <div class="msg__avatar" aria-hidden="true">🏢</div>
    <div class="msg__body">
      <div class="msg__typing" aria-hidden="true">
        <span></span><span></span><span></span>
      </div>
    </div>
  `;
  list.appendChild(el);
  _scrollToBottom(list);
  return el;
}

/** Append the AI's answer bubble. */
export function appendAssistantMessage(
  msg: Message,
  onMapOpen: (geojson: GeoJSON.FeatureCollection, parsedQuery: ParsedQueryDto | null) => void,
  lang: Lang = 'ja',
): void {
  const list = document.getElementById('message-list')!;
  const el = document.createElement('div');
  el.className = 'msg msg--assistant';
  el.setAttribute('role', 'article');
  el.setAttribute('aria-label', t(lang, 'aiAnswerAriaLabel'));

  const metaText = msg.elapsedSec != null
    ? t(lang, 'metaText', { count: msg.candidateCount ?? 0, sec: msg.elapsedSec.toFixed(1) })
    : '';

  const hasGeojson = (msg.geojson?.features.length ?? 0) > 0;

  const recommendedIds = msg.recommendedIds ?? [];

  el.innerHTML = `
    <div class="msg__avatar" aria-hidden="true">🏢</div>
    <div class="msg__body">
      ${hasGeojson ? `
        <button
          class="btn--map-toggle btn--map-toggle-top"
          type="button"
          aria-label="${t(lang, 'mapButtonAriaLabel', { count: msg.candidateCount ?? 0 })}"
          aria-expanded="false"
          aria-controls="map-panel"
        >${t(lang, 'mapButtonText', { count: msg.candidateCount ?? 0 })}</button>
      ` : ''}
      <div class="msg__bubble msg__bubble--markdown">${_renderMarkdown(msg.content)}</div>
      ${hasGeojson ? _buildingListHtml(msg.geojson!.features, recommendedIds, lang) : ''}
      ${metaText ? `<div class="msg__footer"><span class="msg__meta">${metaText}</span></div>` : ''}
    </div>
  `;

  // Map button click handler.
  const mapBtn = el.querySelector<HTMLButtonElement>('.btn--map-toggle');
  if (mapBtn && msg.geojson) {
    const geojson = msg.geojson;
    mapBtn.addEventListener('click', () => onMapOpen(geojson, msg.parsedQuery ?? null));
  }

  // Candidate building list hover linkage.
  // building-item elements past the fold stay in the DOM (collapsed via the
  // hidden attribute), so this single bulk bind also covers items revealed
  // later by the "show N more" toggle.
  el.querySelectorAll<HTMLLIElement>('.building-item').forEach(item => {
    const id = item.dataset['id'] ?? null;
    item.addEventListener('mouseenter', () => highlightBuilding(id));
    item.addEventListener('focus', () => highlightBuilding(id));
    item.addEventListener('mouseleave', () => highlightBuilding(null));
    item.addEventListener('blur', () => highlightBuilding(null));
    // Clicking a candidate opens the map and zooms in far enough to
    // distinguish that building. focusBuilding() looks the id up in
    // currentGeojson, which setGeojson() populates, so this must run
    // after onMapOpen().
    item.addEventListener('click', () => {
      onMapOpen(msg.geojson!, msg.parsedQuery ?? null);
      if (id) focusBuilding(id);
    });
  });

  // "Show N more" toggle.
  const moreBtn = el.querySelector<HTMLButtonElement>('.building-list__more');
  if (moreBtn) {
    const allItems = el.querySelectorAll<HTMLLIElement>('.building-item');
    const totalCount = allItems.length;
    const initialShown = totalCount - Number(moreBtn.dataset['moreCount'] ?? '0');
    moreBtn.addEventListener('click', () => {
      const expanded = moreBtn.getAttribute('aria-expanded') === 'true';
      if (!expanded) {
        allItems.forEach(li => { li.hidden = false; });
        moreBtn.textContent = t(lang, 'moreCollapse');
        moreBtn.setAttribute('aria-expanded', 'true');
      } else {
        allItems.forEach((li, i) => { li.hidden = i >= initialShown; });
        moreBtn.textContent = t(lang, 'moreExpand', { count: totalCount - initialShown });
        moreBtn.setAttribute('aria-expanded', 'false');
      }
    });
  }

  list.appendChild(el);
  _scrollToBottom(list);
}

/** Append an error bubble. */
export function appendErrorMessage(text: string): void {
  const list = document.getElementById('message-list')!;
  const el = document.createElement('div');
  el.className = 'msg msg--assistant';
  el.setAttribute('role', 'alert');
  el.innerHTML = `
    <div class="msg__avatar" aria-hidden="true">⚠️</div>
    <div class="msg__body">
      <div class="msg__bubble" style="border-color:var(--risk-high-text);color:var(--risk-high-text)">
        ${_esc(text)}
      </div>
    </div>
  `;
  list.appendChild(el);
  _scrollToBottom(list);
}

// ============================================================
// Internal helpers
// ============================================================

function _buildingListHtml(features: GeoJSON.Feature[], recommendedIds: string[], lang: Lang): string {
  const MAX_SHOW = 5;

  // Recommended buildings go first, the rest keep their original rank order.
  // building-item__rank always shows properties.rank (the search rank), not
  // the post-reorder position, so reordering here is safe.
  const recSet = new Set(recommendedIds);
  const recommended = recommendedIds
    .map(id => features.find(f => String((f.properties ?? {})['id'] ?? '') === id))
    .filter((f): f is GeoJSON.Feature => f != null);
  const rest = features.filter(f => !recSet.has(String((f.properties ?? {})['id'] ?? '')));
  const ordered = [...recommended, ...rest];

  const items = ordered.map((f, i) => {
    const p = (f.properties ?? {}) as Record<string, unknown>;
    const id = String(p['id'] ?? '');
    const isRecommended = recSet.has(id);
    const rank = p['rank'] != null ? Number(p['rank']) : i + 1;
    const dist = p['nearest_station_dist_m'] != null
      ? t(lang, 'distStation', { m: Math.round(Number(p['nearest_station_dist_m'])) })
      : '';
    // Add a ☀ badge for buildings with confirmed winter sunlight (only
    // when the property is present).
    const sunBadge = p['winter_sunlit'] === true
      ? `<span class="msg__meta" title="${t(lang, 'sunBadgeTitle')}">☀</span>` : '';
    const recBadge = isRecommended
      ? `<span class="rec-badge" title="${t(lang, 'recBadgeTitle')}">${t(lang, 'recBadgeText')}</span>` : '';
    // Items past the 5th are collapsed via the hidden attribute (revealed
    // by "show N more"). They stay in the DOM, so hover-linkage listeners
    // still bind to all items normally.
    const hiddenAttr = i >= MAX_SHOW ? ' hidden' : '';
    const ariaLabel = `${isRecommended ? t(lang, 'itemRecPrefix') : ''}${t(lang, 'itemBuilding', { id })}${dist ? '、' + dist : ''}${p['winter_sunlit'] === true ? t(lang, 'itemSunlitSuffix') : ''}`;
    return `
      <li class="building-item${isRecommended ? ' building-item--recommended' : ''}"
          tabindex="0"${hiddenAttr}
          data-id="${_esc(id)}"
          aria-label="${_esc(ariaLabel)}">
        <span class="building-item__rank" aria-hidden="true">${rank}</span>
        ${recBadge}
        <span class="building-item__id">${_esc(id)}</span>
        ${dist ? `<span class="msg__meta">${dist}</span>` : ''}
        ${sunBadge}
      </li>
    `;
  }).join('');

  const moreCount = ordered.length - MAX_SHOW;
  const moreBtn = moreCount > 0
    ? `<button class="building-list__more" type="button"
               aria-expanded="false" data-more-count="${moreCount}">
         ${t(lang, 'moreExpand', { count: moreCount })}
       </button>`
    : '';

  const recPart = recommended.length > 0 ? t(lang, 'buildingListRecPart', { count: recommended.length }) : '';
  return `
    <ul class="building-list" role="list" aria-label="${_esc(t(lang, 'buildingListAriaLabel', { total: ordered.length, recPart }))}">
      ${items}
    </ul>
    ${moreBtn}
  `;
}

function _esc(str: string): string {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/**
 * Convert the AI's answer body from Markdown to sanitized HTML. User
 * messages and error messages don't need Markdown and stay as plain text
 * via _esc() instead, to avoid widening the attack surface.
 */
// Building ID format ("bldg_" + UUID). Must match
// src/app/main.py::_BUILDING_ID_RE.
const _BUILDING_ID_RE = /\bbldg_[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b/g;

function _renderMarkdown(md: string): string {
  // A raw building ID sitting right after a bold label reads as visually
  // heavy/awkward, so this converts it to a code span before Markdown
  // parsing (picking up the existing monospace, subdued-background code
  // style). Skipped when already backtick-wrapped, to avoid double conversion.
  const withCodeSpans = md.replace(_BUILDING_ID_RE, (match, offset, full) => {
    const before = full[offset - 1];
    const after = full[offset + match.length];
    return (before === '`' || after === '`') ? match : `\`${match}\``;
  });
  const html = marked.parse(withCodeSpans, { async: false }) as string;
  return DOMPurify.sanitize(html);
}

function _scrollToBottom(el: HTMLElement): void {
  requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
}
