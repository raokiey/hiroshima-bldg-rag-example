/** API client — POST /api/search */

export interface SearchRequest {
  query: string;
  lon?: number | null;
  lat?: number | null;
  radius_m?: number;
  top_k?: number;
  embedding_source?: string;
  response_language?: string;
}

/**
 * Must match src/app/retrieval.py::hybrid_search()'s parsed_query_dict
 * key names and types 1:1 — deserialized directly with no backend translation.
 */
export interface RiskFilterDto {
  hazard: 'ht' | 'rv' | 'ts';
  mode: string;
  max_depth_m: number | null;
}

export interface DistanceFilterDto {
  target: string;
  max_dist_m: number;
}

export interface SortSpecDto {
  key: string;
  order: 'asc' | 'desc';
}

export interface OrientationFilterDto {
  direction: 'n' | 'e' | 's' | 'w';
  mode: string;
}

export interface ParsedQueryDto {
  location_name: string | null;
  radius_m: number;
  height_min: number | null;
  usage_include: string[];
  structure_type: string | null;
  sort_by_height: boolean;
  clarification_question: string | null;
  risk_filters: RiskFilterDto[];
  distance_filters: DistanceFilterDto[];
  fire_proof: string | null;
  sort_by: SortSpecDto | null;
  semantic_residual: string;
  orientation_filters: OrientationFilterDto[];
  sunlight: boolean | null;
  quiet: boolean | null;
  vertical_evacuation: boolean | null;
  height_max: number | null;
  storeys_min: number | null;
  storeys_max: number | null;
  usage_exclude: string[];
  structure_exclude: string[];
  roof_type: string | null;
  wooden_dense: boolean | null;
}

export interface SearchResponse {
  query: string;
  answer: string;
  elapsed_sec: number;
  geojson: GeoJSON.FeatureCollection;
  candidate_count: number;
  recommended_ids: string[];
  parsed_query: ParsedQueryDto | null;
  embedding_source: string;
  response_language: string;
}

export async function search(req: SearchRequest): Promise<SearchResponse> {
  const res = await fetch('/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }

  return res.json() as Promise<SearchResponse>;
}
