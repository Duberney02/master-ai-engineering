import type { ComparisonDetail, LabOptions, ModelSettings, StrategyStats } from "../api/types";

export const KNOBS: [string, string, string][] = [
  ["primary_model", "Modelo primario", "Genera todas las estimaciones."],
  ["fallback_model", "Modelo de respaldo", "Se usa cuando el primario falla."],
  ["critic_model", "Crítico (ACB)", "Audita las estimaciones."],
  ["metadata_model", "Extractor de metadatos", "Extrae nombre y tecnologías."],
  ["summary_model", "Resumen y compresión", "Resume la memoria."],
  ["propositional_chunker_model", "Chunker proposicional", "Solo modelos de OpenAI."],
  ["contextual_chunker_model", "Chunker contextual", "Solo modelos de Anthropic."],
];

const CATALOG = ["gpt-4o-mini", "gpt-4o", "claude-haiku-4-5", "claude-sonnet-4-5"];

export function settingsBody(overrides: Record<string, string> = {}): ModelSettings {
  const models: ModelSettings["models"] = {};
  for (const [key] of KNOBS) {
    const fallback = key === "fallback_model" ? null : key === "contextual_chunker_model" ? "claude-sonnet-4-5" : "gpt-4o-mini";
    models[key] = { effective: overrides[key] ?? fallback, default: fallback, overridden: key in overrides };
  }
  return {
    models,
    available_models: CATALOG,
    embedding_model: "text-embedding-3-small",
    embedding_model_note: "Solo lectura: cambiarlo invalidaría todos los vectores guardados.",
    fields: KNOBS.map(([key, label, description]) => ({
      key, label, description,
      options: key === "propositional_chunker_model" ? CATALOG.filter((m) => !m.startsWith("claude"))
        : key === "contextual_chunker_model" ? CATALOG.filter((m) => m.startsWith("claude")) : CATALOG,
    })),
  };
}

const STRATEGIES: [string, string, "free" | "cheap" | "expensive", string | null, boolean][] = [
  ["structural", "Estructural", "free", null, true],
  ["fixed_size", "Tamaño fijo", "free", null, true],
  ["recursive", "Recursivo", "free", null, true],
  ["sentence_window", "Ventana de frases", "free", null, false],
  ["hierarchical", "Jerárquico", "free", null, false],
  ["semantic", "Semántico", "cheap", "OPENAI_API_KEY", false],
  ["propositional", "Proposicional", "expensive", "OPENAI_API_KEY", false],
  ["contextual_retrieval", "Contextual retrieval", "expensive", "ANTHROPIC_API_KEY", false],
];

export function labOptionsBody(): LabOptions {
  return {
    strategies: STRATEGIES.map(([name, label, tier, key, checked]) => ({
      name, label, description: `Descripción de ${label}`, cost_tier: tier,
      cost_label: tier === "free" ? "gratis" : tier === "cheap" ? "de pago (embeddings)" : "de pago (LLM)",
      key_name: key, default_checked: checked,
    })),
    sample_queries: ["¿Cómo se estima un login con OAuth?", "Pasarela de pago con Stripe"],
    top_k: { default: 3, min: 1, max: 10 },
    compare_timeout_seconds: 600,
  };
}

export function statsRow(strategy: string, cost: number, overrides: Partial<StrategyStats> = {}): StrategyStats {
  return {
    strategy, n_chunks: 10, token_distribution: { min: 40, p50: 79, p95: 120.5, max: 300 }, n_orphan_chunks: 0, n_obese_chunks: 0,
    ingestion_cost_usd: cost, extra_api_calls: 0, ingestion_seconds: 0.012, ...overrides,
  };
}

/** Comparación guardada con ID decimal; `id: null` representa una ejecución calculada que no pudo guardarse. */
export function comparisonBody(overrides: Partial<ComparisonDetail> = {}): ComparisonDetail {
  return {
    id: "9007199254740993",
    strategies: ["structural", "hierarchical", "contextual_retrieval"],
    queries: ["oauth"],
    top_k: 3,
    corpus_label: "budgets_sample + budgets_stress_cases",
    corpus_count: 18,
    duration_ms: 3200,
    created_at: "2026-10-05T10:30:00Z",
    total_ingestion_cost_usd: 0.14,
    result: {
      stats_per_strategy: [
        statsRow("structural", 0, { n_orphan_chunks: 2 }),
        statsRow("hierarchical", 0, { n_obese_chunks: 1 }),
        statsRow("contextual_retrieval", 0.14),
      ],
      queries_per_strategy: [
        { strategy: "structural", query: "oauth", top_k: [{ chunk_id: "BUD-1::AUTH-1", cosine: 0.64, text_preview: "Vista previa AUTH", level: null, parent_chunk_id: null }] },
        {
          strategy: "hierarchical", query: "oauth",
          top_k: [
            { chunk_id: "BUD-1::parent", cosine: 0.71, text_preview: "Vista del padre", level: "parent", parent_chunk_id: null },
            { chunk_id: "BUD-1::AUTH-1", cosine: 0.64, text_preview: "Vista del hijo", level: "child", parent_chunk_id: "BUD-1::parent" },
          ],
        },
      ],
    },
    warning: null,
    ...overrides,
  };
}
