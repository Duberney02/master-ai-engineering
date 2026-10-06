// Forma de las respuestas de la API del estimador que consume la web.

export interface Phase {
  name: string;
  description: string;
  duration_weeks: number;
  cost_eur: number;
}

export interface EstimationResult {
  summary: string;
  confidence_pct: number;
  total_duration_weeks: number;
  total_cost_eur: number;
  phases: Phase[];
  out_of_scope?: boolean;
}

export interface CallMetrics {
  model?: string | null;
  usage?: { input_tokens?: number; output_tokens?: number } | null;
  latency_ms?: number;
  request_cost_usd?: number | null;
  cache_hit?: boolean;
}

export interface EstimationOptions {
  project_type?: string;
  detail_level?: string;
  output_format?: string;
}

/** Respuesta de `POST /estimate` y de `GET /estimations/{id}`. */
export interface EstimationResponse {
  result: EstimationResult;
  /** Identificador en el detalle (`GET /estimations/{id}`). */
  id?: number | null;
  /** Identificador en la respuesta de `POST /estimate`. */
  estimation_id?: number | null;
  metrics?: CallMetrics | null;
  cache_source?: string;
  prompt_version?: string;
  options?: EstimationOptions;
  description?: string;
  requested_at?: string;
}

export interface EstimationSummary {
  id: number;
  requested_at: string;
  project_type: string;
  confidence_pct: number;
  total_cost_eur: number;
  out_of_scope: boolean;
  cache_source: string;
  description_excerpt: string;
}

export interface PromptExample {
  title: string;
  description: string;
}

export interface PromptPreview {
  system_prompt: string;
  prompt_version?: string;
  examples?: PromptExample[];
}

export interface PromptPreviewParams {
  prompt_version: string;
  project_type?: string;
  detail_level?: string;
  output_format?: string;
}
