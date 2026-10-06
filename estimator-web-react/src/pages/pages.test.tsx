import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App } from "../App";
import { DESCRIPTION, estimateBody, json, mockApi } from "../test/mockApi";

function renderApp(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

const user = () => userEvent.setup({ applyAccept: false });

function describe_(value: string) {
  fireEvent.change(screen.getByLabelText("Descripción del proyecto o transcripción"), { target: { value } });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("NewEstimationPage", () => {
  test("muestra el formulario, el contador, la carga de .txt y el prompt por defecto en la barra", async () => {
    mockApi();
    renderApp();

    expect(screen.getByRole("heading", { name: "Estimador de proyectos" })).toBeInTheDocument();
    expect(screen.getByLabelText("Descripción del proyecto o transcripción")).toHaveAttribute("maxlength", "80000");
    expect(screen.getByLabelText("…o carga una transcripción (.txt)")).toHaveAttribute("accept", ".txt,text/plain");
    expect(within(screen.getByLabelText("Tipo de proyecto")).getAllByRole("option")).toHaveLength(4);
    expect(screen.getByLabelText("Versión del prompt")).toHaveValue("v3");
    expect(document.body).toHaveTextContent("80.000 caracteres");
    expect(document.getElementById("timer")).toBeInTheDocument();
    expect(await screen.findByLabelText("System prompt")).toHaveValue("Prompt medium");
    expect(screen.getByText("Aún no se ha generado ninguna estimación.")).toBeInTheDocument();
  });

  test("una descripción válida llama a la API y navega al detalle", async () => {
    const api = mockApi((url, init) =>
      url.pathname === "/api/v1/estimate" && init.method === "POST" ? json(estimateBody()) : undefined,
      (url) => (url.pathname === "/api/v1/estimations/7" ? json({ ...estimateBody(), id: 7, description: DESCRIPTION, options: { project_type: "web_saas", detail_level: "medium", output_format: "phases_table" } }) : undefined),
    );
    renderApp();

    describe_(DESCRIPTION);
    await user().selectOptions(screen.getByLabelText("Tipo de proyecto"), "web_saas");
    await user().click(screen.getByRole("button", { name: "Estimar" }));

    expect(await screen.findByRole("heading", { name: "Estimación #7" })).toBeInTheDocument();
    const post = api.callsTo("/api/v1/estimate")[0];
    expect(post.url.searchParams.get("prompt_version")).toBe("v3");
    expect(JSON.parse(post.init.body as string)).toEqual({
      description: DESCRIPTION, project_type: "web_saas", detail_level: "medium", output_format: "phases_table",
    });
    expect(document.getElementById("cost")).toHaveTextContent("20.000,00 EUR");
  });

  test("una descripción fuera de rango muestra el mensaje y no llama a la API", async () => {
    const api = mockApi();
    renderApp();

    describe_("corta");
    await user().click(screen.getByRole("button", { name: "Estimar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("La descripción debe tener entre 20 y 80000 caracteres.");
    expect(api.callsTo("/api/v1/estimate")).toHaveLength(0);
  });

  test("al cargar un .txt válido su contenido sustituye a la descripción y actualiza el contador", async () => {
    mockApi();
    renderApp();
    describe_("texto que será sustituido");

    await user().upload(
      screen.getByLabelText("…o carga una transcripción (.txt)"),
      new File([DESCRIPTION], "reunion.txt", { type: "text/plain" }),
    );

    await waitFor(() => expect(screen.getByLabelText("Descripción del proyecto o transcripción")).toHaveValue(DESCRIPTION));
    expect(document.getElementById("char-count")).toHaveTextContent(String(DESCRIPTION.length));
  });

  test.each([
    ["no es .txt", () => new File(["hola"], "reunion.pdf"), "El archivo debe ser de texto plano (.txt)."],
    ["supera 400 KB", () => new File(["a".repeat(400_001)], "grande.txt"), "El archivo supera el máximo de 400 KB."],
    ["no es UTF-8", () => new File([new Uint8Array([0xff, 0xfe, 0xfa])], "raro.txt"), "El archivo debe estar codificado en UTF-8."],
  ])("un archivo que %s muestra el error y no llama a la API", async (_name, makeFile, message) => {
    const api = mockApi();
    renderApp();

    await user().upload(screen.getByLabelText("…o carga una transcripción (.txt)"), makeFile());

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(api.callsTo("/api/v1/estimate")).toHaveLength(0);
  });

  test("durante el envío deshabilita el botón y muestra el indicador con el temporizador", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let resolve: (response: Response) => void = () => {};
    mockApi((url, init) =>
      url.pathname === "/api/v1/estimate" && init.method === "POST"
        ? (new Promise<Response>((r) => { resolve = r; }) as unknown as Response)
        : undefined,
    );
    renderApp();
    describe_(DESCRIPTION);

    fireEvent.click(screen.getByRole("button", { name: "Estimar" }));

    const button = await screen.findByRole("button", { name: "Estimar" });
    expect(button).toBeDisabled();
    expect(document.getElementById("loading")).toHaveClass("active");
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(document.getElementById("timer")).toHaveTextContent("3 s");

    await act(async () => { resolve(json({ message: "Rechazado por guardrails" }, 400)); });
    await waitFor(() => expect(button).toBeEnabled());
    expect(document.getElementById("loading")).not.toHaveClass("active");
  });

  test("tras un error de la API conserva los datos y muestra el mensaje saneado", async () => {
    mockApi((url, init) =>
      url.pathname === "/api/v1/estimate" && init.method === "POST"
        ? json({ reason: "r", message: "El contenido no parece un proyecto de software." }, 400)
        : undefined,
    );
    renderApp();
    describe_(DESCRIPTION);
    await user().selectOptions(screen.getByLabelText("Nivel de detalle"), "detailed");

    await user().click(screen.getByRole("button", { name: "Estimar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("El contenido no parece un proyecto de software.");
    expect(screen.getByLabelText("Descripción del proyecto o transcripción")).toHaveValue(DESCRIPTION);
    expect(screen.getByLabelText("Nivel de detalle")).toHaveValue("detailed");
    expect(screen.getByRole("button", { name: "Estimar" })).toBeEnabled();
  });

  test("con la API caída muestra el mensaje de conexión sin detalles internos", async () => {
    mockApi((url, init) => {
      if (url.pathname === "/api/v1/estimate" && init.method === "POST") throw new TypeError("connect ECONNREFUSED 10.0.0.5:8000");
      return undefined;
    });
    renderApp();
    describe_(DESCRIPTION);

    await user().click(screen.getByRole("button", { name: "Estimar" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No se pudo conectar con la API del estimador.");
    expect(alert).not.toHaveTextContent("10.0.0.5");
  });

  test("al cambiar las opciones la barra pide el prompt de las nuevas opciones", async () => {
    const api = mockApi();
    renderApp();
    expect(await screen.findByLabelText("System prompt")).toHaveValue("Prompt medium");

    await user().selectOptions(screen.getByLabelText("Nivel de detalle"), "detailed");

    await waitFor(() => expect(screen.getByLabelText("System prompt")).toHaveValue("Prompt detailed"));
    expect(api.callsTo("/api/v1/prompts/estimation").at(-1)!.url.searchParams.get("detail_level")).toBe("detailed");
  });

  test("si el prompt no se puede renderizar avisa en la barra y el formulario sigue funcionando", async () => {
    mockApi((url) => (url.pathname === "/api/v1/prompts/estimation" ? json({}, 500) : undefined));
    renderApp();

    expect(await screen.findByText("El contexto del prompt no está disponible en este momento.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Estimar" })).toBeEnabled();
  });

  test("sin estimation_id muestra el resultado en línea con métricas y sin enlace permanente", async () => {
    mockApi((url, init) =>
      url.pathname === "/api/v1/estimate" && init.method === "POST" ? json(estimateBody({ estimation_id: null })) : undefined,
    );
    renderApp();
    describe_(DESCRIPTION);

    await user().click(screen.getByRole("button", { name: "Estimar" }));

    expect(await screen.findByRole("heading", { name: "Estimación" })).toBeInTheDocument();
    expect(document.getElementById("cost")).toHaveTextContent("20.000,00 EUR");
    expect(document.getElementById("phases")!.querySelectorAll("tbody tr")).toHaveLength(2);
    expect(document.getElementById("description-text")).toHaveTextContent(DESCRIPTION);
    expect(document.getElementById("metric-model")).toHaveTextContent("claude-test");
    expect(document.getElementById("metric-input-tokens")).toHaveTextContent("1.200");
    expect(screen.queryByRole("link", { name: /#/ })).not.toBeInTheDocument();
  });

  test("el botón de la barra la oculta y la vuelve a mostrar", async () => {
    mockApi();
    renderApp();
    const toggle = await screen.findByRole("button", { name: "«" });

    await user().click(toggle);
    expect(document.getElementById("layout")).toHaveClass("collapsed");
    expect(screen.getByRole("button", { name: "»" })).toHaveAttribute("aria-expanded", "false");
  });
});

describe("EstimationPage", () => {
  const detail = {
    ...estimateBody({ cache_source: "exact" }),
    id: 7,
    description: "Descripción guardada",
    options: { project_type: "web_saas", detail_level: "detailed", output_format: "narrative" },
    requested_at: "2026-05-20T10:05:00Z",
  };

  test("carga la estimación, sus métricas y el prompt de sus opciones", async () => {
    const api = mockApi((url) => (url.pathname === "/api/v1/estimations/7" ? json(detail) : undefined));
    renderApp("/estimations/7");

    expect(await screen.findByRole("heading", { name: "Estimación #7" })).toBeInTheDocument();
    expect(document.getElementById("estimation-meta")).toHaveTextContent("SaaS web · detalle detallado · narrativa · prompt v3 · Caché exacta · 20/05/2026 10:05 UTC");
    expect(document.getElementById("metric-model")).toHaveTextContent("claude-test");
    expect(await screen.findByLabelText("System prompt")).toHaveValue("Prompt detailed");
    expect(api.callsTo("/api/v1/prompts/estimation").at(-1)!.url.searchParams.get("output_format")).toBe("narrative");
  });

  test("un resultado out_of_scope muestra «No estimable» sin cifras", async () => {
    mockApi((url) =>
      url.pathname === "/api/v1/estimations/7"
        ? json({ ...detail, result: { ...detail.result, out_of_scope: true, confidence_pct: 10, summary: "Out of scope: faltan datos" } })
        : undefined,
    );
    renderApp("/estimations/7");

    expect(await screen.findByText(/No estimable\./)).toBeInTheDocument();
    expect(document.getElementById("cost")).toBeNull();
  });

  test("una estimación inexistente muestra la pantalla de error sin barra lateral", async () => {
    mockApi((url) => (url.pathname === "/api/v1/estimations/99" ? json({}, 404) : undefined));
    renderApp("/estimations/99");

    expect(await screen.findByRole("heading", { name: "No se pudo completar la operación" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("No se encontró la estimación solicitada.");
    expect(document.getElementById("sidebar")).toBeNull();
  });

  test("un identificador no numérico muestra el error de no encontrada sin llamar a la API", async () => {
    const api = mockApi();
    renderApp("/estimations/abc");

    expect(await screen.findByRole("alert")).toHaveTextContent("No se encontró la estimación solicitada.");
    expect(api.callsTo("/api/v1/estimations/abc")).toHaveLength(0);
    expect(api.calls.filter((call) => call.url.pathname.startsWith("/api/v1/estimations"))).toHaveLength(0);
  });
});

describe("HistoryPage", () => {
  const items = [
    { id: 2, requested_at: "2026-05-21T09:00:00Z", project_type: "web_saas", confidence_pct: 85, total_cost_eur: 12345.5, out_of_scope: false, cache_source: "semantic", description_excerpt: "x".repeat(120) },
    { id: 1, requested_at: "2026-05-20T10:05:00Z", project_type: "mobile_app", confidence_pct: 12, total_cost_eur: 0, out_of_scope: true, cache_source: "none", description_excerpt: "App de reparto" },
  ];

  test("lista las estimaciones en el orden recibido con enlace al detalle", async () => {
    const api = mockApi((url) => (url.pathname === "/api/v1/estimations" ? json(items) : undefined));
    renderApp("/estimations");

    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("21/05/2026 09:00 UTC");
    expect(rows[0]).toHaveTextContent("SaaS web");
    expect(rows[0]).toHaveTextContent("85%");
    expect(rows[0]).toHaveTextContent("12.345,50 EUR");
    expect(rows[0]).toHaveTextContent("Caché semántica");
    expect(within(rows[0]).getByRole("link")).toHaveAttribute("href", "/estimations/2");
    expect(rows[1]).toHaveTextContent("No estimable");
    expect(rows[1]).not.toHaveTextContent("EUR");
    expect(api.callsTo("/api/v1/estimations")[0].url.searchParams.get("limit")).toBe("10");
  });

  test("trunca el extracto a 90 caracteres", async () => {
    mockApi((url) => (url.pathname === "/api/v1/estimations" ? json(items) : undefined));
    renderApp("/estimations");

    const row = (await screen.findAllByRole("row"))[1];
    const excerpt = within(row).getAllByRole("cell").at(-1)!.textContent!;
    expect(Array.from(excerpt)).toHaveLength(90);
    expect(excerpt.endsWith("...")).toBe(true);
  });

  test("con la lista vacía invita a crear la primera estimación", async () => {
    mockApi((url) => (url.pathname === "/api/v1/estimations" ? json([]) : undefined));
    renderApp("/estimations");

    const empty = await screen.findByText(/Todavía no hay estimaciones\./);
    expect(within(empty).getByRole("link", { name: "Crea la primera" })).toHaveAttribute("href", "/");
  });

  test("con 503 muestra un aviso explicativo y no un error técnico", async () => {
    mockApi((url) => (url.pathname === "/api/v1/estimations" ? json({ detail: "db down" }, 503) : undefined));
    renderApp("/estimations");

    expect(await screen.findByText("El historial no está disponible en este momento.")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("db down");
  });

  test("las rutas desconocidas muestran la página no encontrada", async () => {
    mockApi();
    renderApp("/no/existe");

    expect(await screen.findByRole("heading", { name: "Página no encontrada" })).toBeInTheDocument();
  });

  test("la navegación lleva del historial al formulario", async () => {
    mockApi((url) => (url.pathname === "/api/v1/estimations" ? json(items) : undefined));
    renderApp("/estimations");
    await screen.findByRole("table");

    await user().click(screen.getAllByRole("link", { name: "Nueva estimación" })[0]);

    expect(await screen.findByRole("heading", { name: "Estimador de proyectos" })).toBeInTheDocument();
  });
});
