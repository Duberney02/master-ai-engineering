// Cliente HTTP de la API del estimador (equivalente de EstimatorApi en Rails).
//
// Es el único módulo que usa `fetch`. Traduce cualquier fallo a EstimatorApiError con un mensaje en
// español apto para el usuario: nunca expone cuerpos de respuesta crudos, trazas ni URLs.
// Solo usa rutas relativas: en producción las atiende el proxy nginx y en desarrollo el de Vite.

import type {
  EstimationResponse, EstimationSummary, PromptPreview, PromptPreviewParams,
} from "./types";

export const CONNECTION_MESSAGE = "No se pudo conectar con la API del estimador. Inténtalo de nuevo en unos instantes.";
export const INVALID_RESPONSE_MESSAGE = "La API del estimador devolvió una respuesta inválida.";
export const SERVER_MESSAGE = "La API del estimador no pudo completar la solicitud. Inténtalo de nuevo.";
export const VALIDATION_MESSAGE = "La solicitud no es válida. Revisa los campos del formulario.";
export const NOT_FOUND_MESSAGE = "No se encontró la estimación solicitada.";
export const HISTORY_UNAVAILABLE_MESSAGE = "El historial no está disponible en este momento.";
export const REJECTED_MESSAGE = "La API rechazó la solicitud.";
export const GUARDRAIL_MESSAGE_LIMIT = 300;

/** La estimación puede tardar un par de minutos con transcripciones largas. */
export const ESTIMATE_TIMEOUT_MS = 300_000;
export const DEFAULT_TIMEOUT_MS = 30_000;

export class EstimatorApiError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "EstimatorApiError";
    this.status = status;
  }
}

interface RequestOptions {
  method?: "GET" | "POST";
  params?: Record<string, string | number | undefined>;
  body?: unknown;
  history?: boolean;
  timeoutMs?: number;
  signal?: AbortSignal;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function guardrailMessage(body: string): string {
  try {
    const message = (JSON.parse(body) as { message?: unknown } | null)?.message;
    return typeof message === "string" && message.trim() !== ""
      ? Array.from(message).slice(0, GUARDRAIL_MESSAGE_LIMIT).join("")
      : REJECTED_MESSAGE;
  } catch {
    return REJECTED_MESSAGE;
  }
}

function messageFor(status: number, body: string, history: boolean): string {
  if (status === 400) return guardrailMessage(body);
  if (status === 404) return NOT_FOUND_MESSAGE;
  if (status === 422) return VALIDATION_MESSAGE;
  if (status === 503) return history ? HISTORY_UNAVAILABLE_MESSAGE : SERVER_MESSAGE;
  if (status >= 500 && status <= 599) return SERVER_MESSAGE;
  return REJECTED_MESSAGE;
}

function buildUrl(path: string, params?: RequestOptions["params"]): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  const text = query.toString();
  return text ? `${path}?${text}` : path;
}

async function request(path: string, options: RequestOptions = {}): Promise<unknown> {
  const { method = "GET", params, body, history = false, timeoutMs = DEFAULT_TIMEOUT_MS, signal } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort);

  try {
    const response = await fetch(buildUrl(path, params), {
      method,
      headers: { Accept: "application/json", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    const text = await response.text();
    if (response.status !== 200) {
      throw new EstimatorApiError(messageFor(response.status, text, history), response.status);
    }
    try {
      return JSON.parse(text);
    } catch {
      throw new EstimatorApiError(INVALID_RESPONSE_MESSAGE);
    }
  } catch (error) {
    if (error instanceof EstimatorApiError) throw error;
    // Cancelación pedida por quien llama (p. ej. una opción cambió): no es un fallo de la API.
    if (signal?.aborted) throw new DOMException("Solicitud cancelada", "AbortError");
    throw new EstimatorApiError(CONNECTION_MESSAGE);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

function expectResult(body: unknown): EstimationResponse {
  if (!isObject(body) || !isObject(body.result)) throw new EstimatorApiError(INVALID_RESPONSE_MESSAGE);
  return body as unknown as EstimationResponse;
}

/** Solicita una estimación. Devuelve el cuerpo de la API (con `result`, `estimation_id`...). */
export async function createEstimation(
  attributes: Record<string, unknown>,
  promptVersion?: string,
): Promise<EstimationResponse> {
  const body = await request("/api/v1/estimate", {
    method: "POST",
    params: { prompt_version: promptVersion },
    body: attributes,
    timeoutMs: ESTIMATE_TIMEOUT_MS,
  });
  return expectResult(body);
}

/** Últimas estimaciones del historial. */
export async function listEstimations(limit = 10): Promise<EstimationSummary[]> {
  const body = await request("/api/v1/estimations", { params: { limit }, history: true });
  if (!Array.isArray(body) || !body.every(isObject)) throw new EstimatorApiError(INVALID_RESPONSE_MESSAGE);
  return body as unknown as EstimationSummary[];
}

/** Prompt de sistema renderizado y ejemplos few-shot para unas opciones (barra lateral). */
export async function promptPreview(params: PromptPreviewParams, signal?: AbortSignal): Promise<PromptPreview> {
  const body = await request("/api/v1/prompts/estimation", {
    params: { ...params },
    signal,
  });
  if (!isObject(body) || typeof body.system_prompt !== "string") throw new EstimatorApiError(INVALID_RESPONSE_MESSAGE);
  return body as unknown as PromptPreview;
}

export async function findEstimation(id: string | number): Promise<EstimationResponse> {
  // Como `Integer(id)` en Rails: un identificador no numérico es «no encontrada» sin llamar a la API.
  if (!/^\d+$/.test(String(id))) throw new EstimatorApiError(NOT_FOUND_MESSAGE, 404);
  const body = await request(`/api/v1/estimations/${Number(id)}`, { history: true });
  return expectResult(body);
}
