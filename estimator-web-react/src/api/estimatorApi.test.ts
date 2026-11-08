import {
  CONNECTION_MESSAGE, EstimatorApiError, HISTORY_UNAVAILABLE_MESSAGE, INVALID_RESPONSE_MESSAGE,
  NOT_FOUND_MESSAGE, REJECTED_MESSAGE, SERVER_MESSAGE, VALIDATION_MESSAGE,
  findEstimation, listEstimations, promptPreview,
} from "./estimatorApi";

const RESULT = { summary: "Resumen", confidence_pct: 80, total_duration_weeks: 8, total_cost_eur: 20000, phases: [] };

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
  vi.useRealTimers();
});

async function messageOf(promise: Promise<unknown>): Promise<{ message: string; status: number | null }> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(EstimatorApiError);
    const { message, status } = error as EstimatorApiError;
    return { message, status };
  }
  throw new Error("Debía fallar");
}

describe("errores del cliente HTTP", () => {
  test.each([
    [422, VALIDATION_MESSAGE],
    [404, NOT_FOUND_MESSAGE],
    [503, SERVER_MESSAGE],
    [500, SERVER_MESSAGE],
    [502, SERVER_MESSAGE],
    [418, REJECTED_MESSAGE],
  ])("estado %i se traduce a un mensaje saneado", async (status, expected) => {
    fetchMock.mockResolvedValue(reply({ detail: "Traceback http://estimador-cag:8000 secreto" }, status));
    const { message } = await messageOf(promptPreview({ prompt_version: "v3" }));
    expect(message).toBe(expected);
    expect(message).not.toMatch(/Traceback|estimador-cag|secreto|http/);
  });

  test("cuerpo no JSON o sin result es una respuesta inválida", async () => {
    fetchMock.mockResolvedValueOnce(reply("no es json"));
    expect((await messageOf(promptPreview({ prompt_version: "v3" }))).message).toBe(INVALID_RESPONSE_MESSAGE);
    fetchMock.mockResolvedValueOnce(reply({ sin: "result" }));
    expect((await messageOf(promptPreview({ prompt_version: "v3" }))).message).toBe(INVALID_RESPONSE_MESSAGE);
    fetchMock.mockResolvedValueOnce(reply({ result: "texto" }));
    expect((await messageOf(promptPreview({ prompt_version: "v3" }))).message).toBe(INVALID_RESPONSE_MESSAGE);
  });

  test("fallo de red se traduce al mensaje de conexión", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch http://interna:8000"));
    const { message, status } = await messageOf(promptPreview({ prompt_version: "v3" }));
    expect(message).toBe(CONNECTION_MESSAGE);
    expect(status).toBeNull();
  });

  test("tiempo agotado se traduce al mensaje de conexión", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener("abort", () => reject(new DOMException("abort", "AbortError")));
        }),
    );
    const pending = messageOf(promptPreview({ prompt_version: "v3" }));
    await vi.advanceTimersByTimeAsync(30_001);
    expect((await pending).message).toBe(CONNECTION_MESSAGE);
  });
});

describe("listEstimations", () => {
  test("pide el límite y devuelve la lista", async () => {
    fetchMock.mockResolvedValue(reply([{ id: 1 }, { id: 2 }]));
    expect(await listEstimations(10)).toEqual([{ id: 1 }, { id: 2 }]);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/estimations?limit=10");
  });

  test("503 indica que el historial no está disponible", async () => {
    fetchMock.mockResolvedValue(reply({ detail: "db" }, 503));
    expect((await messageOf(listEstimations())).message).toBe(HISTORY_UNAVAILABLE_MESSAGE);
  });

  test("un cuerpo que no es lista de objetos es inválido", async () => {
    fetchMock.mockResolvedValueOnce(reply({ no: "lista" }));
    expect((await messageOf(listEstimations())).message).toBe(INVALID_RESPONSE_MESSAGE);
    fetchMock.mockResolvedValueOnce(reply([1, 2]));
    expect((await messageOf(listEstimations())).message).toBe(INVALID_RESPONSE_MESSAGE);
  });
});

describe("findEstimation", () => {
  test("carga el detalle por identificador", async () => {
    fetchMock.mockResolvedValue(reply({ result: RESULT, id: 7 }));
    await findEstimation("7");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/estimations/7");
  });

  test("un identificador no numérico es «no encontrada» sin llamar a la API", async () => {
    const { message, status } = await messageOf(findEstimation("abc"));
    expect(message).toBe(NOT_FOUND_MESSAGE);
    expect(status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("404 y 503 usan sus mensajes", async () => {
    fetchMock.mockResolvedValueOnce(reply({}, 404));
    expect((await messageOf(findEstimation(9))).message).toBe(NOT_FOUND_MESSAGE);
    fetchMock.mockResolvedValueOnce(reply({}, 503));
    expect((await messageOf(findEstimation(9))).message).toBe(HISTORY_UNAVAILABLE_MESSAGE);
  });
});

describe("promptPreview", () => {
  test("envía las opciones como parámetros", async () => {
    fetchMock.mockResolvedValue(reply({ system_prompt: "Eres un estimador", examples: [] }));
    const preview = await promptPreview({
      prompt_version: "v3", project_type: "web_saas", detail_level: "medium", output_format: "phases_table",
    });
    expect(preview.system_prompt).toBe("Eres un estimador");
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/api/prompt-preview?prompt_version=v3&project_type=web_saas&detail_level=medium&output_format=phases_table",
    );
  });

  test("sin system_prompt es una respuesta inválida", async () => {
    fetchMock.mockResolvedValue(reply({ examples: [] }));
    expect((await messageOf(promptPreview({ prompt_version: "v3" }))).message).toBe(INVALID_RESPONSE_MESSAGE);
  });

  test("la cancelación del llamador se señala como AbortError, no como fallo de la API", async () => {
    const controller = new AbortController();
    fetchMock.mockImplementation(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener("abort", () => reject(new DOMException("abort", "AbortError")));
        }),
    );
    const pending = promptPreview({ prompt_version: "v3" }, controller.signal);
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
});
