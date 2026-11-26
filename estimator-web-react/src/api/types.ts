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

// --- Ajustes de IA (GET/PUT /api/v1/ai/settings) ---

export interface ModelValue {
  effective: string | null;
  default: string | null;
  overridden: boolean;
}

export interface SettingsField {
  key: string;
  label: string;
  description: string;
  /** Modelos seleccionables para este campo (los chunkers solo ofrecen los de su proveedor). */
  options: string[];
}

export interface ModelSettings {
  models: Record<string, ModelValue>;
  available_models: string[];
  embedding_model: string;
  embedding_model_note: string;
  fields: SettingsField[];
}

// --- Chunking Lab (/api/v1/rag/chunking-comparisons) ---

export interface StrategyOption {
  name: string;
  label: string;
  description: string;
  cost_tier: "free" | "cheap" | "expensive";
  cost_label: string;
  /** Variable de la clave de proveedor que necesita, o `null`. */
  key_name: string | null;
  default_checked: boolean;
}

export interface LabOptions {
  strategies: StrategyOption[];
  sample_queries: string[];
  top_k: { default: number; min: number; max: number };
  compare_timeout_seconds: number;
}

export interface LabRequest {
  strategies: string[];
  queries: string[];
  custom_queries: string;
  /** Omitido, el Lab usa 3 (DA-28). */
  top_k?: number;
}

export interface StrategyStats {
  strategy: string;
  n_chunks: number;
  token_distribution: { min: number; p50: number; p95: number; max: number };
  n_orphan_chunks: number;
  n_obese_chunks: number;
  ingestion_cost_usd: number;
  extra_api_calls: number;
  ingestion_seconds: number;
}

export interface RetrievedChunk {
  chunk_id: string;
  cosine: number;
  text_preview: string;
  level: "parent" | "child" | null;
  parent_chunk_id: string | null;
}

export interface QueryOutcome {
  strategy: string;
  query: string;
  top_k: RetrievedChunk[];
}

/** DA-27: `id` es una cadena decimal (un número JSON perdería dígitos por encima de 2^53 − 1) y `null` si no se guardó. */
export interface ComparisonSummary {
  id: string | null;
  strategies: string[];
  queries: string[];
  top_k: number;
  corpus_label: string;
  corpus_count: number;
  duration_ms: number | null;
  created_at: string | null;
  total_ingestion_cost_usd: number;
}

export interface ComparisonDetail extends ComparisonSummary {
  result: { stats_per_strategy: StrategyStats[]; queries_per_strategy: QueryOutcome[] };
  warning: string | null;
}

export interface ComparisonList {
  items: ComparisonSummary[];
  warning: string | null;
}
