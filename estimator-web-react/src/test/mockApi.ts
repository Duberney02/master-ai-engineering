import { EMPTY_METADATA, type EstimationResponse, type SessionEstimationResponse } from "../api/types";

export const DESCRIPTION = "Portal de clientes para consultar facturas y abrir incidencias de soporte.";

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

export function estimateBody(overrides: Partial<EstimationResponse> = {}): EstimationResponse {
  return {
    result: {
      summary: "Portal de clientes",
      confidence_pct: 80,
      total_duration_weeks: 8.5,
      total_cost_eur: 20000,
      phases: [
        { name: "Análisis", description: "Requisitos", duration_weeks: 2, cost_eur: 5000 },
        { name: "Desarrollo", description: "Código", duration_weeks: 6.5, cost_eur: 15000 },
      ],
    },
    estimation_id: 7,
    prompt_version: "v3",
    cache_source: "none",
    metrics: { model: "claude-test", usage: { input_tokens: 1200, output_tokens: 300 }, latency_ms: 2500, request_cost_usd: 0.05, cache_hit: false },
    ...overrides,
  };
}

export const SESSION_ID = "6f1c2c1e-6d0a-4a5e-9c1a-0d6f5b1f4a10";

/** Respuesta de `POST /sessions/{id}/estimate`: la estimación más el estado de la conversación. */
export function sessionBody(overrides: Partial<SessionEstimationResponse> = {}): SessionEstimationResponse {
  return {
    ...estimateBody(),
    session_id: SESSION_ID,
    project_metadata: EMPTY_METADATA,
    turn_count: 1,
    max_turns: 6,
    ...overrides,
  };
}

export const isSessionEstimate = (url: URL, init: RequestInit) =>
  init.method === "POST" && /^\/api\/v1\/sessions\/[^/]+\/estimate$/.test(url.pathname);

export type Handler = (url: URL, init: RequestInit) => Response | Promise<Response> | undefined;

/**
 * Sustituye `fetch` por un enrutador por ruta. Los manejadores se prueban en orden; el prompt de
 * la barra lateral responde siempre salvo que un manejador lo sobrescriba.
 */
export function mockApi(...handlers: Handler[]) {
  const calls: { url: URL; init: RequestInit }[] = [];
  const sessions: string[] = [];
  const fetchMock = vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = new URL(input, "http://localhost");
    calls.push({ url, init });
    for (const handler of handlers) {
      const response = handler(url, init);
      if (response) return response;
    }
    if (url.pathname === "/api/v1/sessions" && init.method === "POST") {
      const sessionId = sessions.length === 0 ? SESSION_ID : `${SESSION_ID.slice(0, -2)}${String(sessions.length + 1).padStart(2, "0")}`;
      sessions.push(sessionId);
      return json({ session_id: sessionId }, 201);
    }
    if (url.pathname === "/api/v1/prompts/estimation") {
      return json({
        system_prompt: `Prompt ${url.searchParams.get("detail_level")}`,
        prompt_version: url.searchParams.get("prompt_version"),
        examples: [{ title: "Ejemplo", description: "Descripción del ejemplo" }],
      });
    }
    return json({ detail: "no mock" }, 500);
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    /** Identificadores de las sesiones creadas por la aplicación, en orden. */
    sessions,
    callsTo: (pathname: string) => calls.filter((call) => call.url.pathname === pathname),
    estimateCalls: () => calls.filter((call) => isSessionEstimate(call.url, call.init)),
  };
}
