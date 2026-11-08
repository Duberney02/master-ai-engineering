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

/** Hechos conocidos del proyecto, acumulados durante la conversación (`project_metadata`). */
export interface ProjectMetadata {
  project_name: string | null;
  assumed_team_size: number | null;
  mentioned_technologies: string[];
  agreed_scope: string | null;
}

export const EMPTY_METADATA: ProjectMetadata = {
  project_name: null,
  assumed_team_size: null,
  mentioned_technologies: [],
  agreed_scope: null,
};

/** Respuesta de `POST /sessions/{id}/estimate`: la estimación y el estado de la conversación. */
export interface SessionEstimationResponse extends EstimationResponse {
  session_id: string;
  project_metadata: ProjectMetadata;
  turn_count: number;
  max_turns: number;
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

// --- Chunking Lab (`/api/chunking-comparisons`) ---

export interface LabStrategy {
  name: string;
  label: string;
  description: string;
  cost_tier: "free" | "cheap" | "expensive";
  cost_label: string;
  paid: boolean;
  /** Variable de entorno de la clave del proveedor que necesita en el servicio de IA (vacío si ninguna). */
  key_name: string;
  default_checked: boolean;
}

export interface LabOptions {
  strategies: LabStrategy[];
  default_strategies: string[];
  sample_queries: string[];
  default_top_k: number;
  compare_timeout_seconds: number;
}

export interface ChunkingStats {
  strategy: string;
  n_chunks: number;
  token_distribution: { min: number; p50: number; p95: number; max: number };
  n_orphan_chunks: number;
  n_obese_chunks: number;
  ingestion_cost_usd: number;
  extra_api_calls: number;
  ingestion_seconds: number;
}

export interface TopChunk {
  chunk_id: string;
  cosine: number;
  text_preview: string;
  level?: string | null;
  parent_chunk_id?: string | null;
}

export interface QueryResult {
  strategy: string;
  query: string;
  top_k: TopChunk[];
}

export interface ChunkingResponse {
  stats_per_strategy: Record<string, ChunkingStats>;
  queries_per_strategy: Record<string, QueryResult[]>;
}

/** Una ejecución del Chunking Lab. El listado no incluye `response`. */
export interface Comparison {
  id: number;
  strategies: string[];
  strategy_labels: string[];
  queries: string[];
  top_k: number;
  corpus_label: string;
  corpus_count: number;
  duration_ms: number | null;
  created_at: string | null;
  /** `false` si el historial no pudo guardarla: se muestra igualmente, con `notice`. */
  saved: boolean;
  total_ingestion_cost_usd: number;
  notice?: string;
  response?: ChunkingResponse;
}

// --- Ajustes de IA (`/api/ai-settings`) ---

export interface ModelSetting {
  key: string;
  label: string;
  description: string;
  provider: string;
  effective: string;
  default: string;
  overridden: boolean;
  /** Modelo preseleccionado: el vigente solo si hay override. */
  selected: string;
  options: string[];
}

export interface AiSettings {
  models: ModelSetting[];
  available_models: string[];
  embedding_model: string;
  embedding_model_note: string;
  any_overridden: boolean;
}
