/** main.ts — initializes the PLATEAU RAG app and wires up events. */

import 'maplibre-gl/dist/maplibre-gl.css';
import './style.css';

import { store, type MapSheetState } from './store';
import { initTheme, toggleTheme, refreshThemeToggleLabel } from './theme';
import { initLang, toggleLang, t } from './i18n';
import { initMap, setGeojson, applyMapTheme, resizeMap } from './map';
import { search, type ParsedQueryDto } from './api';
import {
  hideWelcome,
  appendUserMessage,
  appendLoadingBubble,
  appendAssistantMessage,
  appendErrorMessage,
} from './chat';

// ---- aria-live announcement helper ----
function announce(msg: string, urgent = false): void {
  const el = document.getElementById(urgent ? 'a11y-alert' : 'a11y-status');
  if (el) { el.textContent = ''; requestAnimationFrame(() => { el.textContent = msg; }); }
}

// ============================================================
// Track the real mobile viewport height (works around the input field
// getting hidden behind the on-screen keyboard).
// ============================================================
function setupViewportHeightFix(): void {
  const setAppHeight = (): void => {
    const h = window.visualViewport ? window.visualViewport.height : window.innerHeight;
    document.documentElement.style.setProperty('--app-height', `${h}px`);
  };
  setAppHeight();
  window.visualViewport?.addEventListener('resize', setAppHeight);
  window.addEventListener('resize', setAppHeight);
}

// ============================================================
// Theme toggle
// ============================================================
function setupTheme(): void {
  initTheme();
  document.getElementById('theme-toggle')?.addEventListener('click', () => {
    toggleTheme();
    const theme = store.get().theme;
    applyMapTheme(theme);
    const lang = store.get().language;
    announce(t(lang, theme === 'dark' ? 'themeDarkAnnounce' : 'themeLightAnnounce'));
  });
}

// ============================================================
// Language toggle (ja/en)
// ============================================================
function setupLang(): void {
  initLang();
  document.getElementById('lang-toggle')?.addEventListener('click', () => {
    toggleLang();
    refreshThemeToggleLabel();
    announce(t(store.get().language, 'langSwitchAnnounce'));
  });
}

// ============================================================
// Map panel open/close (desktop/tablet: existing split-pane / inline
// expansion approach). Mobile uses the bottom-sheet approach instead
// (setMapSheetState), handled separately below.
// ============================================================
function isMobileViewport(): boolean {
  return window.innerWidth < 768;
}

function openMap(geojson: GeoJSON.FeatureCollection, parsedQuery: ParsedQueryDto | null): void {
  store.set({ activeGeojson: geojson, activeParsedQuery: parsedQuery, isMapVisible: true });
  setGeojson(geojson, parsedQuery);

  if (isMobileViewport()) {
    // An explicit map-open request (button/candidate click) opens at least
    // to 'half' (stays at 'full' if already there).
    const current = store.get().mapSheetState;
    setMapSheetState(current === 'full' ? 'full' : 'half');
    return;
  }

  const panel = document.getElementById('map-panel')!;
  panel.classList.add('visible');
  panel.setAttribute('aria-hidden', 'false');
  resizeMap();
  announce(t(store.get().language, 'mapOpenedAnnounce', { count: geojson.features.length }));
}

function closeMap(): void {
  store.set({ isMapVisible: false });

  if (isMobileViewport()) {
    setMapSheetState('hidden');
    return;
  }

  const panel = document.getElementById('map-panel')!;
  panel.classList.remove('visible');
  panel.setAttribute('aria-hidden', 'true');
  resizeMap();
  announce(t(store.get().language, 'mapClosedAnnounce'));
}

// ============================================================
// Mobile map bottom sheet
// ============================================================
const SHEET_ANNOUNCE_KEY: Record<MapSheetState, string> = {
  hidden: 'mapClosedAnnounce',
  peek: 'mapSheetPeekAnnounce',
  half: 'mapSheetHalfAnnounce',
  full: 'mapSheetFullAnnounce',
};

function sheetHeightPx(state: Exclude<MapSheetState, 'hidden'>): number {
  if (state === 'peek') return 64;
  if (state === 'half') return window.innerHeight * 0.5;
  return window.innerHeight * 0.9;
}

function setMapSheetState(state: MapSheetState): void {
  if (store.get().mapSheetState === state) return;
  store.set({ mapSheetState: state });

  const panel = document.getElementById('map-panel');
  if (!panel) return;
  panel.style.height = ''; // Clear the inline height set during dragging, so CSS takes over.
  if (state === 'hidden') {
    panel.removeAttribute('data-sheet-state');
  } else {
    panel.setAttribute('data-sheet-state', state);
  }
  panel.setAttribute('aria-hidden', String(state === 'hidden'));

  const peekBar = document.getElementById('map-sheet-peek-bar');
  if (peekBar) peekBar.setAttribute('aria-expanded', String(state === 'half' || state === 'full'));

  resizeMap();
  window.setTimeout(resizeMap, 260); // Re-apply once the snap animation finishes.

  announce(t(store.get().language, SHEET_ANNOUNCE_KEY[state]));
}

function setupMapSheetDrag(): void {
  const peekBar = document.getElementById('map-sheet-peek-bar');
  const panel = document.getElementById('map-panel');
  if (!peekBar || !panel) return;

  let dragging = false;
  let moved = false;
  let startY = 0;
  let startHeight = 0;

  peekBar.addEventListener('pointerdown', (e) => {
    if (!isMobileViewport()) return;
    dragging = true;
    moved = false;
    startY = e.clientY;
    const current = store.get().mapSheetState;
    startHeight = sheetHeightPx(current === 'hidden' ? 'peek' : current);
    panel.classList.add('dragging');
    peekBar.setPointerCapture(e.pointerId);
  });

  peekBar.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    const dy = startY - e.clientY; // Positive = dragging upward.
    if (Math.abs(dy) > 6) moved = true;
    if (!moved) return;
    const minH = sheetHeightPx('peek');
    const maxH = sheetHeightPx('full');
    const newHeight = Math.min(maxH, Math.max(minH, startHeight + dy));
    panel.style.height = `${newHeight}px`;
    requestAnimationFrame(resizeMap);
  });

  const endDrag = (): void => {
    if (!dragging) return;
    dragging = false;
    panel.classList.remove('dragging');

    if (!moved) {
      // A plain tap: expand one step (peek/hidden -> half, half/full -> full).
      const current = store.get().mapSheetState;
      setMapSheetState(current === 'half' || current === 'full' ? 'full' : 'half');
      return;
    }

    // Drag ended: snap to whichever preset height is closest to the current one.
    const currentHeightPx = panel.getBoundingClientRect().height;
    const candidates: [MapSheetState, number][] = [
      ['peek', sheetHeightPx('peek')],
      ['half', sheetHeightPx('half')],
      ['full', sheetHeightPx('full')],
    ];
    let best: MapSheetState = 'peek';
    let bestDist = Infinity;
    for (const [name, h] of candidates) {
      const d = Math.abs(h - currentHeightPx);
      if (d < bestDist) { bestDist = d; best = name; }
    }
    setMapSheetState(best);
  };

  peekBar.addEventListener('pointerup', endDrag);
  peekBar.addEventListener('pointercancel', endDrag);
}

function setupMapControls(): void {
  document.getElementById('map-close-btn')?.addEventListener('click', closeMap);
  document.getElementById('map-close-btn-mobile')?.addEventListener('click', closeMap);
  document.getElementById('map-sheet-collapse-btn')?.addEventListener('click', () => {
    const current = store.get().mapSheetState;
    setMapSheetState(current === 'full' ? 'half' : 'hidden');
  });
  setupMapSheetDrag();
}

// ============================================================
// Search form
// ============================================================
let isComposing = false;

function setupSearchForm(): void {
  const form = document.getElementById('search-form') as HTMLFormElement;
  const textarea = document.getElementById('query-input') as HTMLTextAreaElement;
  const topkSelect = document.getElementById('topk-select') as HTMLSelectElement;
  const embeddingSelect = document.getElementById('embedding-select') as HTMLSelectElement;

  // Avoid submitting on Enter while an IME composition is in progress.
  textarea.addEventListener('compositionstart', () => { isComposing = true; });
  textarea.addEventListener('compositionend', () => { isComposing = false; });

  // Submit on Enter (Shift+Enter inserts a newline).
  textarea.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !isComposing) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  // Auto-resize the textarea to fit its content.
  textarea.addEventListener('input', () => {
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
  });

  // On mobile, ensure the input stays visible above the on-screen keyboard
  // by scrolling it into view on focus (a backstop alongside --app-height).
  textarea.addEventListener('focus', () => {
    window.setTimeout(() => {
      textarea.scrollIntoView({ block: 'end', behavior: 'smooth' });
    }, 300);
  });

  // Reflect result-count/embedding-source setting changes into the store.
  topkSelect.addEventListener('change', () => {
    store.set({ settings: { ...store.get().settings, topK: Number(topkSelect.value) } });
  });
  embeddingSelect.addEventListener('change', () => {
    store.set({ settings: { ...store.get().settings, embeddingSource: embeddingSelect.value } });
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = textarea.value.trim();
    if (!query || store.get().isLoading) return;

    await runSearch(query);
  });

  // Example query buttons.
  document.querySelectorAll<HTMLButtonElement>('.example-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const query = btn.dataset['query'] ?? '';
      if (query) {
        textarea.value = query;
        await runSearch(query);
      }
    });
  });
}

async function runSearch(query: string): Promise<void> {
  const textarea = document.getElementById('query-input') as HTMLTextAreaElement;
  const submitBtn = document.getElementById('submit-btn') as HTMLButtonElement;
  const settings = store.get().settings;

  // Hide the welcome message.
  hideWelcome();

  const lang = store.get().language;

  // Add the user's message bubble.
  appendUserMessage(query, lang);
  textarea.value = '';
  textarea.style.height = '';

  // Loading state.
  store.set({ isLoading: true });
  submitBtn.disabled = true;
  submitBtn.setAttribute('aria-busy', 'true');
  submitBtn.innerHTML = '<span class="spinner" aria-hidden="true"></span>';
  announce(t(lang, 'generatingAnnounce'));

  const loadingEl = appendLoadingBubble(lang);

  try {
    const result = await search({
      query,
      lon: settings.lon,
      lat: settings.lat,
      radius_m: 500,
      top_k: settings.topK,
      embedding_source: settings.embeddingSource,
      response_language: lang,
    });

    loadingEl.remove();

    const msgId = `msg-${Date.now()}`;
    const msg = {
      id: msgId,
      role: 'assistant' as const,
      content: result.answer,
      geojson: result.geojson,
      candidateCount: result.candidate_count,
      elapsedSec: result.elapsed_sec,
      recommendedIds: result.recommended_ids,
      parsedQuery: result.parsed_query ?? null,
    };

    store.set({ messages: [...store.get().messages, msg] });
    appendAssistantMessage(msg, openMap, lang);

    // Reflect any candidate buildings onto the map.
    // Desktop/tablet: auto-opens the map panel (existing behavior).
    // Mobile: auto-shows the sheet at 'peek' only when it's currently
    // hidden — if already at half/full, leave it there so the user can
    // keep asking follow-up questions while looking at the map.
    if (result.candidate_count > 0) {
      if (isMobileViewport()) {
        store.set({ activeGeojson: result.geojson, activeParsedQuery: result.parsed_query ?? null });
        setGeojson(result.geojson, result.parsed_query ?? null);
        if (store.get().mapSheetState === 'hidden') {
          setMapSheetState('peek');
        }
      } else {
        openMap(result.geojson, result.parsed_query ?? null);
      }
    }

    announce(
      result.candidate_count > 0
        ? t(lang, 'resultWithCountAnnounce', { count: result.candidate_count })
        : t(lang, 'resultNoCountAnnounce'),
    );

  } catch (err) {
    loadingEl.remove();
    const msg = err instanceof Error ? err.message : t(lang, 'unknownError');
    appendErrorMessage(t(lang, 'errorPrefix', { msg }));
    announce(t(lang, 'errorAnnounce', { msg }), true);
  } finally {
    store.set({ isLoading: false });
    submitBtn.disabled = false;
    submitBtn.setAttribute('aria-busy', 'false');
    submitBtn.textContent = '▶';
    textarea.focus();
  }
}

// ============================================================
// Startup
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  setupViewportHeightFix();
  setupLang();
  setupTheme();
  setupMapControls();
  setupSearchForm();

  // Initialize the map after the panel becomes visible.
  initMap();
});
