// Chunking Lab: comparación de estrategias de chunking con historial persistido en el backend.

import { EstimatorApiError, INVALID_RESPONSE_MESSAGE, LAB_TIMEOUT_MS, isObject, request } from "./estimatorApi";
import type { Comparison, LabOptions } from "./types";

export const COMPARISON_NOT_FOUND_MESSAGE = "No se encontró la comparación solicitada.";

export interface ComparisonRequest {
  strategies: string[];
  queries: string[];
  top_k: number;
}

function expectComparison(body: unknown, withResponse: boolean): Comparison {
  if (!isObject(body) || typeof body.id !== "number" || !Array.isArray(body.strategies)) {
    throw new EstimatorApiError(INVALID_RESPONSE_MESSAGE);
  }
  if (withResponse && !isObject(body.response)) throw new EstimatorApiError(INVALID_RESPONSE_MESSAGE);
  return body as unknown as Comparison;
}

/** Catálogo de estrategias, selección por defecto y consultas predefinidas. */
export async function getLabOptions(): Promise<LabOptions> {
  const body = await request("/api/chunking-comparisons/options", { detail: true });
  if (!isObject(body) || !Array.isArray(body.strategies) || !Array.isArray(body.sample_queries)) {
    throw new EstimatorApiError(INVALID_RESPONSE_MESSAGE);
  }
  return body as unknown as LabOptions;
}

/** Ejecuta y guarda una comparación (puede tardar minutos con estrategias de pago). */
export async function runComparison(payload: ComparisonRequest): Promise<Comparison> {
  const body = await request("/api/chunking-comparisons", {
    method: "POST", body: payload, expectedStatus: 201, detail: true, timeoutMs: LAB_TIMEOUT_MS,
  });
  return expectComparison(body, true);
}

/** Últimas ejecuciones, la más reciente primero. */
export async function listComparisons(): Promise<Comparison[]> {
  const body = await request("/api/chunking-comparisons", { detail: true });
  if (!Array.isArray(body)) throw new EstimatorApiError(INVALID_RESPONSE_MESSAGE);
  return body.map((item) => expectComparison(item, false));
}

export async function findComparison(id: string | number): Promise<Comparison> {
  // Un identificador no numérico es «no encontrada» sin llamar al backend.
  if (!/^\d+$/.test(String(id))) throw new EstimatorApiError(COMPARISON_NOT_FOUND_MESSAGE, 404);
  const body = await request(`/api/chunking-comparisons/${Number(id)}`, { detail: true });
  return expectComparison(body, true);
}
