// Cliente HTTP de la API del estimador (equivalente de EstimatorApi en Rails).
//
// Es el único módulo que usa `fetch`. Traduce cualquier fallo a EstimatorApiError con un mensaje en
// español apto para el usuario: nunca expone cuerpos de respuesta crudos, trazas ni URLs.
// Solo usa rutas relativas: en producción las atiende el proxy nginx y en desarrollo el de Vite.

import { EMPTY_METADATA } from "./types";
import type {
  EstimationResponse, EstimationSummary, ProjectMetadata, PromptPreview, PromptPreviewParams,
  SessionEstimationResponse,
} from "./types";

export const CONNECTION_MESSAGE = "No se pudo conectar con la API del estimador. Inténtalo de nuevo en unos instantes.";
export const INVALID_RESPONSE_MESSAGE = "La API del estimador devolvió una respuesta inválida.";
export const SERVER_MESSAGE = "La API del estimador no pudo completar la solicitud. Inténtalo de nuevo.";
export const VALIDATION_MESSAGE = "La solicitud no es válida. Revisa los campos del formulario.";
export const NOT_FOUND_MESSAGE = "No se encontró la estimación solicitada.";
export const HISTORY_UNAVAILABLE_MESSAGE = "El historial no está disponible en este momento.";
export const REJECTED_MESSAGE = "La API rechazó la solicitud.";
export const SESSION_EXPIRED_MESSAGE = "La conversación anterior expiró en el servidor; se inició una nueva. Vuelve a enviar tu mensaje.";
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

/** La API ya no conoce la sesión (reinicio del servicio o caducidad): hay que abrir otra conversación. */
export class SessionExpiredError extends EstimatorApiError {
  constructor() {
    super(SESSION_EXPIRED_MESSAGE, 404);
    this.name = "SessionExpiredError";
  }
}

interface RequestOptions {
  method?: "GET" | "POST";
  params?: Record<string, string | number | undefined>;
  /** JSON, o `FormData` para multipart (el navegador fija el `Content-Type` con su frontera). */
  body?: unknown;
  history?: boolean;
  /** Llamada de sesión: 404 es sesión caducada y los 413/415/422 traen un `detail` de texto apto para el usuario. */
  session?: boolean;
  expectedStatus?: number;
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

function detailMessage(body: string): string | null {
  try {
    const detail = (JSON.parse(body) as { detail?: unknown } | null)?.detail;
    return typeof detail === "string" && detail.trim() !== ""
      ? Array.from(detail).slice(0, GUARDRAIL_MESSAGE_LIMIT).join("")
      : null;
  } catch {
    return null;
  }
}

function messageFor(status: number, body: string, history: boolean, session = false): string {
  if (session && [413, 415, 422].includes(status)) return detailMessage(body) ?? (status === 422 ? VALIDATION_MESSAGE : REJECTED_MESSAGE);
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
  const {
    method = "GET", params, body, history = false, session = false, expectedStatus = 200,
    timeoutMs = DEFAULT_TIMEOUT_MS, signal,
  } = options;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort);

  try {
    const response = await fetch(buildUrl(path, params), {
      method,
      headers: { Accept: "application/json", ...(body === undefined || isForm ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
      signal: controller.signal,
    });
    const text = await response.text();
    if (response.status !== expectedStatus) {
      if (session && response.status === 404) throw new SessionExpiredError();
      throw new EstimatorApiError(messageFor(response.status, text, history, session), response.status);
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

/** Crea una conversación vacía y devuelve su `session_id` (vive en memoria del servicio). */
export async function createSession(): Promise<string> {
  const body = await request("/api/v1/sessions", { method: "POST", expectedStatus: 201 });
  if (!isObject(body) || typeof body.session_id !== "string") throw new EstimatorApiError(INVALID_RESPONSE_MESSAGE);
  return body.session_id;
}

function expectMetadata(value: unknown): ProjectMetadata {
  if (!isObject(value)) throw new EstimatorApiError(INVALID_RESPONSE_MESSAGE);
  const technologies = value.mentioned_technologies;
  if (!Array.isArray(technologies) || !technologies.every((item) => typeof item === "string")) {
    throw new EstimatorApiError(INVALID_RESPONSE_MESSAGE);
  }
  return { ...EMPTY_METADATA, ...(value as Partial<ProjectMetadata>), mentioned_technologies: technologies };
}

/** Una estimación dentro de la conversación (multipart: `transcript`, opciones y `attachments`). */
export async function createSessionEstimation(sessionId: string, form: FormData): Promise<SessionEstimationResponse> {
  const body = await request(`/api/v1/sessions/${encodeURIComponent(sessionId)}/estimate`, {
    method: "POST",
    body: form,
    session: true,
    timeoutMs: ESTIMATE_TIMEOUT_MS,
  });
  const estimation = expectResult(body) as SessionEstimationResponse;
  return { ...estimation, project_metadata: expectMetadata((body as Record<string, unknown>).project_metadata) };
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
