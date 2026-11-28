// Cliente de las operaciones administrativas de Go: Ajustes de IA, indicador del modelo primario y Chunking Lab.
//
// Comparte `request` con el resto de la API (único módulo con `fetch`). Go decide el acceso: un 403 llega como
// EstimatorApiError con `status` 403 y las pantallas muestran el estado de acceso restringido sin datos.

import { EstimatorApiError, INVALID_RESPONSE_MESSAGE, ESTIMATE_TIMEOUT_MS, isObject, request } from "./estimatorApi";
import type {
  ComparisonDetail, ComparisonList, ComparisonSummary, LabOptions, LabRequest, ModelSettings, ModelValue,
  QueryOutcome, StrategyOption, StrategyStats,
} from "./types";

const invalid = () => new EstimatorApiError(INVALID_RESPONSE_MESSAGE);
const isString = (value: unknown): value is string => typeof value === "string";
const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const isStringList = (value: unknown): value is string[] => Array.isArray(value) && value.every(isString);
const nullableString = (value: unknown): value is string | null => value === null || isString(value);
const DECIMAL_ID = /^(0|[1-9]\d*)$/;

/** Una ruta de ID decimal válida (como las de Go). Un ID distinto se trata como no encontrado sin llamar a la API. */
export const isComparisonId = (id: string): boolean => DECIMAL_ID.test(id);

// --- Ajustes ---

function expectSettings(body: unknown): ModelSettings {
  if (!isObject(body) || !isObject(body.models) || !Array.isArray(body.fields) || !isStringList(body.available_models)) throw invalid();
  const models: Record<string, ModelValue> = {};
  for (const [key, value] of Object.entries(body.models)) {
    if (!isObject(value) || !nullableString(value.effective) || !nullableString(value.default) || typeof value.overridden !== "boolean") throw invalid();
    models[key] = { effective: value.effective, default: value.default, overridden: value.overridden };
  }
  const fields = body.fields.map((field) => {
    if (!isObject(field) || !isString(field.key) || !isString(field.label) || !isString(field.description) || !isStringList(field.options)) throw invalid();
    return { key: field.key, label: field.label, description: field.description, options: field.options };
  });
  return {
    models,
    available_models: body.available_models,
    embedding_model: isString(body.embedding_model) ? body.embedding_model : "",
    embedding_model_note: isString(body.embedding_model_note) ? body.embedding_model_note : "",
    fields,
  };
}

export async function getSettings(signal?: AbortSignal): Promise<ModelSettings> {
  return expectSettings(await request("/api/v1/ai/settings", { detail: true, signal }));
}

/** Guarda todos los campos del formulario: un valor `null` restablece el modelo por defecto. */
export async function saveSettings(models: Record<string, string | null>): Promise<ModelSettings> {
  return expectSettings(await request("/api/v1/ai/settings", { method: "PUT", body: { models }, detail: true }));
}

/** Nombre del modelo primario o `null`. Nunca falla: sin servicio, la barra omite el indicador. */
export async function getPrimaryModel(signal?: AbortSignal): Promise<string | null> {
  try {
    const body = await request("/api/v1/ai/primary-model", { signal });
    return isObject(body) && isString(body.model) && body.model !== "" ? body.model : null;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return null;
  }
}

// --- Chunking Lab ---

function expectOptions(body: unknown): LabOptions {
  if (!isObject(body) || !Array.isArray(body.strategies) || !isStringList(body.sample_queries) || !isObject(body.top_k)) throw invalid();
  const { top_k: limits } = body;
  if (!isNumber(limits.default) || !isNumber(limits.min) || !isNumber(limits.max) || !isNumber(body.compare_timeout_seconds)) throw invalid();
  const strategies = body.strategies.map((item): StrategyOption => {
    if (
      !isObject(item) || !isString(item.name) || !isString(item.label) || !isString(item.description) ||
      !["free", "cheap", "expensive"].includes(item.cost_tier as string) || !isString(item.cost_label) ||
      !nullableString(item.key_name) || typeof item.default_checked !== "boolean"
    ) throw invalid();
    return item as unknown as StrategyOption;
  });
  return {
    strategies,
    sample_queries: body.sample_queries,
    top_k: { default: limits.default, min: limits.min, max: limits.max },
    compare_timeout_seconds: body.compare_timeout_seconds,
  };
}

function expectSummary(value: unknown): ComparisonSummary {
  if (
    !isObject(value) || !(value.id === null || (isString(value.id) && DECIMAL_ID.test(value.id))) ||
    !isStringList(value.strategies) || !isStringList(value.queries) || !isNumber(value.top_k) ||
    !isString(value.corpus_label) || !isNumber(value.corpus_count) ||
    !(value.duration_ms === null || isNumber(value.duration_ms)) || !nullableString(value.created_at) ||
    !isNumber(value.total_ingestion_cost_usd)
  ) throw invalid();
  return value as unknown as ComparisonSummary;
}

function expectDetail(body: unknown): ComparisonDetail {
  const summary = expectSummary(body);
  const { result, warning } = body as Record<string, unknown>;
  if (!isObject(result) || !Array.isArray(result.stats_per_strategy) || !Array.isArray(result.queries_per_strategy) || !nullableString(warning)) throw invalid();
  for (const stats of result.stats_per_strategy) {
    if (!isObject(stats) || !isString(stats.strategy) || !isObject(stats.token_distribution) || !isNumber(stats.n_chunks)) throw invalid();
  }
  for (const outcome of result.queries_per_strategy) {
    if (!isObject(outcome) || !isString(outcome.strategy) || !isString(outcome.query) || !Array.isArray(outcome.top_k)) throw invalid();
  }
  return {
    ...summary,
    result: {
      stats_per_strategy: result.stats_per_strategy as StrategyStats[],
      queries_per_strategy: result.queries_per_strategy as QueryOutcome[],
    },
    warning,
  };
}

export async function getLabOptions(signal?: AbortSignal): Promise<LabOptions> {
  return expectOptions(await request("/api/v1/rag/chunking-comparisons/options", { detail: true, signal }));
}

/**
 * Ejecuta una comparación. Con guardado exitoso (201) `id` es la cadena decimal del registro; si solo falló el
 * guardado (200) `id` es `null` y `warning` lo explica. Nunca se reintenta.
 */
export async function runComparison(input: LabRequest, signal?: AbortSignal): Promise<ComparisonDetail> {
  const body = await request("/api/v1/rag/chunking-comparisons", {
    method: "POST", body: input, expectedStatus: [200, 201], detail: true, timeoutMs: ESTIMATE_TIMEOUT_MS, signal,
  });
  return expectDetail(body);
}

export async function listComparisons(signal?: AbortSignal): Promise<ComparisonList> {
  const body = await request("/api/v1/rag/chunking-comparisons", { detail: true, signal });
  if (!isObject(body) || !Array.isArray(body.items) || !nullableString(body.warning)) throw invalid();
  return { items: body.items.map(expectSummary), warning: body.warning };
}

export async function getComparison(id: string, signal?: AbortSignal): Promise<ComparisonDetail> {
  if (!isComparisonId(id)) throw new EstimatorApiError("No se encontró la comparación solicitada.", 404);
  return expectDetail(await request(`/api/v1/rag/chunking-comparisons/${id}`, { detail: true, signal }));
}
