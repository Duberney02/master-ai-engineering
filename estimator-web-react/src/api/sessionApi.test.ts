import {
  EstimatorApiError, INVALID_RESPONSE_MESSAGE, REJECTED_MESSAGE, SESSION_EXPIRED_MESSAGE, SERVER_MESSAGE,
  SessionExpiredError, VALIDATION_MESSAGE, createSession, createSessionEstimation,
} from "./estimatorApi";
import { EMPTY_METADATA } from "./types";

const RESULT = { summary: "Resumen", confidence_pct: 80, total_duration_weeks: 8, total_cost_eur: 20000, phases: [] };
const SESSION_ID = "6f1c2c1e-6d0a-4a5e-9c1a-0d6f5b1f4a10";

function reply(body: unknown, status = 200) {
  return new Response(typeof body === "string" ? body : JSON.stringify(body), { status });
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function failure(promise: Promise<unknown>): Promise<EstimatorApiError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(EstimatorApiError);
    return error as EstimatorApiError;
  }
  throw new Error("Debía fallar");
}

describe("createSession", () => {
  test("hace POST a /api/v1/sessions y devuelve el session_id", async () => {
    fetchMock.mockResolvedValue(reply({ session_id: SESSION_ID }, 201));

    expect(await createSession()).toBe(SESSION_ID);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/sessions");
    expect(init.method).toBe("POST");
  });

  test("un cuerpo sin session_id es una respuesta inválida", async () => {
    fetchMock.mockResolvedValue(reply({ otro: 1 }, 201));

    expect((await failure(createSession())).message).toBe(INVALID_RESPONSE_MESSAGE);
  });

  test("un 5xx se traduce a un mensaje saneado", async () => {
    fetchMock.mockResolvedValue(reply({ detail: "Traceback secreto" }, 500));

    const error = await failure(createSession());

    expect(error.message).toBe(SERVER_MESSAGE);
  });
});

describe("createSessionEstimation", () => {
  const form = () => {
    const data = new FormData();
    data.set("transcript", "texto");
    return data;
  };
  const okBody = { result: RESULT, session_id: SESSION_ID, project_metadata: { ...EMPTY_METADATA, project_name: "Orion" }, turn_count: 1, max_turns: 6 };

  test("envía multipart sin fijar el Content-Type y valida los metadatos", async () => {
    fetchMock.mockResolvedValue(reply(okBody));
    const body = form();

    const response = await createSessionEstimation(SESSION_ID, body);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`/api/v1/sessions/${SESSION_ID}/estimate`);
    expect(init.method).toBe("POST");
    expect(init.body).toBe(body);
    expect(init.headers).not.toHaveProperty("Content-Type");
    expect(response.project_metadata.project_name).toBe("Orion");
    expect(response.turn_count).toBe(1);
  });

  test("un 404 es una sesión caducada", async () => {
    fetchMock.mockResolvedValue(reply({ detail: "Session not found or expired" }, 404));

    const error = await failure(createSessionEstimation(SESSION_ID, form()));

    expect(error).toBeInstanceOf(SessionExpiredError);
    expect(error.message).toBe(SESSION_EXPIRED_MESSAGE);
    expect(error.status).toBe(404);
  });

  test.each([
    [413, { detail: "Cada adjunto puede pesar como máximo 10 MB." }, "Cada adjunto puede pesar como máximo 10 MB."],
    [415, { detail: "Solo se admiten adjuntos PDF (.pdf) y Word (.docx)." }, "Solo se admiten adjuntos PDF (.pdf) y Word (.docx)."],
    [422, { detail: "El texto debe tener al menos 20 caracteres." }, "El texto debe tener al menos 20 caracteres."],
    [422, { detail: [{ loc: ["body"], msg: "x", input: "texto privado" }] }, VALIDATION_MESSAGE],
    [413, {}, REJECTED_MESSAGE],
  ])("el estado %i muestra el detail de texto o un mensaje genérico", async (status, body, expected) => {
    fetchMock.mockResolvedValue(reply(body, status));

    const error = await failure(createSessionEstimation(SESSION_ID, form()));

    expect(error.message).toBe(expected);
    expect(error.message).not.toContain("privado");
  });

  test("el message del guardrail se muestra en un 400", async () => {
    fetchMock.mockResolvedValue(reply({ reason: "pii_email", message: "Elimina el correo." }, 400));

    expect((await failure(createSessionEstimation(SESSION_ID, form()))).message).toBe("Elimina el correo.");
  });

  test.each([
    ["sin result", { session_id: SESSION_ID, project_metadata: EMPTY_METADATA }],
    ["sin project_metadata", { result: RESULT }],
    ["con tecnologías inválidas", { result: RESULT, project_metadata: { ...EMPTY_METADATA, mentioned_technologies: "python" } }],
  ])("una respuesta %s es inválida", async (_name, body) => {
    fetchMock.mockResolvedValue(reply(body));

    expect((await failure(createSessionEstimation(SESSION_ID, form()))).message).toBe(INVALID_RESPONSE_MESSAGE);
  });
});
