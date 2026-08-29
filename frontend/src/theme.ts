/** ThemeManager — light/dark toggling with localStorage persistence. */

import { store } from './store';
import { t } from './i18n';

const STORAGE_KEY = 'plateau-rag-theme';

const STYLE_LIGHT = 'https://tiles.openfreemap.org/styles/liberty';
const STYLE_DARK  = 'https://tiles.openfreemap.org/styles/dark';

export function getMapStyle(theme: 'light' | 'dark'): string {
  return theme === 'dark' ? STYLE_DARK : STYLE_LIGHT;
}

/** Determine and apply the initial theme. */
export function initTheme(): void {
  const saved = localStorage.getItem(STORAGE_KEY) as 'light' | 'dark' | null;
  const preferred = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  const theme = saved ?? preferred;
  applyTheme(theme);
  store.set({ theme });
}

/** Toggle the theme. */
export function toggleTheme(): void {
  const next = store.get().theme === 'light' ? 'dark' : 'light';
  applyTheme(next);
  store.set({ theme: next });
  localStorage.setItem(STORAGE_KEY, next);
}

function applyTheme(theme: 'light' | 'dark'): void {
  document.documentElement.setAttribute('data-theme', theme);
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  const isDark = theme === 'dark';
  btn.textContent = isDark ? '☽' : '☀';
  const lang = store.get().language;
  btn.setAttribute('aria-label', t(lang, isDark ? 'lightModeToggle' : 'darkModeToggle'));
  btn.setAttribute('aria-pressed', String(isDark));
}

/** Re-apply theme-toggle's aria-label for the current theme after a language switch. */
export function refreshThemeToggleLabel(): void {
  applyTheme(store.get().theme);
}
