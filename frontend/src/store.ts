/** AppState — global state management (vanilla TS, with an event emitter). */

import type { ParsedQueryDto } from './api';
import type { Lang } from './i18n';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  geojson?: GeoJSON.FeatureCollection;
  candidateCount?: number;
  elapsedSec?: number;
  recommendedIds?: string[];
  parsedQuery?: ParsedQueryDto | null;
}

export interface Settings {
  topK: number;
  embeddingSource: string;
  lon: number | null;
  lat: number | null;
}

/** Mobile map bottom sheet state. Unused on desktop/tablet. */
export type MapSheetState = 'hidden' | 'peek' | 'half' | 'full';

export interface AppState {
  messages: Message[];
  isLoading: boolean;
  activeGeojson: GeoJSON.FeatureCollection | null;
  activeParsedQuery: ParsedQueryDto | null;
  isMapVisible: boolean;
  mapSheetState: MapSheetState;
  theme: 'light' | 'dark';
  language: Lang;
  settings: Settings;
}

type Listener = (state: AppState) => void;

class Store {
  private state: AppState = {
    messages: [],
    isLoading: false,
    activeGeojson: null,
    activeParsedQuery: null,
    isMapVisible: false,
    mapSheetState: 'hidden',
    theme: 'light',
    language: 'ja',
    settings: { topK: 10, embeddingSource: 'ruri', lon: null, lat: null },
  };

  private listeners: Listener[] = [];

  get(): AppState { return this.state; }

  set(partial: Partial<AppState>): void {
    this.state = { ...this.state, ...partial };
    this.listeners.forEach(fn => fn(this.state));
  }

  subscribe(fn: Listener): () => void {
    this.listeners.push(fn);
    return () => { this.listeners = this.listeners.filter(l => l !== fn); };
  }
}

export const store = new Store();
