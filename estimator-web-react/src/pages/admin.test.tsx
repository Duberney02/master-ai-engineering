import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App } from "../App";
import { comparisonBody, labOptionsBody, settingsBody, statsRow, KNOBS } from "../test/adminFixtures";
import { json, mockApi, type Handler } from "../test/mockApi";

function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

const user = () => userEvent.setup({ applyAccept: false });
const SETTINGS = "/api/v1/ai/settings";
const LAB = "/api/v1/rag/chunking-comparisons";
const route = (method: string, pathname: string, respond: (url: URL, init: RequestInit) => Response | Promise<Response>): Handler =>
  (url, init) => ((init.method ?? "GET") === method && url.pathname === pathname ? respond(url, init) : undefined);
const denied = (pathname: string, method = "GET") =>
  route(method, pathname, () => json({ detail: "Acceso administrativo denegado." }, 403));
/** Una respuesta que no llega nunca y se rechaza al abortar la solicitud, como `fetch`. */
const hanging = (method: string, pathname: string, started?: () => void): Handler =>
  route(method, pathname, (_url, init) => new Promise<Response>((_resolve, reject) => {
    started?.();
    init.signal?.addEventListener("abort", () => reject(new DOMException("abort", "AbortError")));
  }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("navegación y indicador del modelo primario", () => {
  test("ofrece las cuatro entradas y marca la vista activa con aria-current", async () => {
    mockApi(route("GET", `${LAB}`, () => json({ items: [], warning: null })));
    renderApp("/rag/chunking-comparisons");
    const nav = screen.getByRole("navigation", { name: "Principal" });
    expect(within(nav).getAllByRole("link").map((link) => link.textContent)).toEqual(
      expect.arrayContaining(["Nueva estimación", "Historial", "RAG · Chunking Lab", "Ajustes"]),
    );
    expect(within(nav).getByRole("link", { name: "RAG · Chunking Lab" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Ajustes" })).not.toHaveAttribute("aria-current");
    expect(within(nav).getByRole("link", { name: "Historial" })).not.toHaveAttribute("aria-current");
    await screen.findByText("Todavía no hay comparaciones guardadas.", { exact: false });
  });

  test("la sección RAG sigue activa en sus subrutas y Ajustes en su vista", async () => {
    mockApi(route("GET", `${LAB}/options`, () => json(labOptionsBody())), route("GET", SETTINGS, () => json(settingsBody())));
    const first = renderApp("/rag/chunking-comparisons/new");
    expect(screen.getByRole("link", { name: "RAG · Chunking Lab" })).toHaveAttribute("aria-current", "page");
    first.unmount();
    renderApp("/settings");
    expect(screen.getByRole("link", { name: "Ajustes" })).toHaveAttribute("aria-current", "page");
    await screen.findByRole("heading", { name: "Ajustes del servicio IA" });
  });

  test("muestra el modelo primario y solo enlaza a Ajustes cuando Go ya concedió acceso", async () => {
    mockApi(
      route("GET", "/api/v1/ai/primary-model", () => json({ model: "gpt-4o-mini" })),
      route("GET", SETTINGS, () => json(settingsBody())),
    );
    renderApp("/estimations/abc");
    const badge = () => document.getElementById("primary-model");
    await waitFor(() => expect(badge()).toHaveTextContent("gpt-4o-mini"));
    expect(badge()!.closest("a")).toBeNull();
    await user().click(screen.getByRole("link", { name: "Ajustes" }));
    await screen.findByRole("heading", { name: "Ajustes del servicio IA" });
    await waitFor(() => expect(badge()!.closest("a")).toHaveAttribute("href", "/settings"));
  });

  test("sin servicio la página conserva la navegación y omite el indicador", async () => {
    mockApi(route("GET", "/api/v1/ai/primary-model", () => json({ detail: "x" }, 502)));
    renderApp("/estimations/abc");
    expect(await screen.findByRole("heading", { name: "No se pudo completar la operación" })).toBeInTheDocument();
    expect(document.getElementById("primary-model")).toBeNull();
    expect(screen.getByRole("link", { name: "Historial" })).toBeInTheDocument();
  });

  test("el inicio y la navegación son utilizables sin IA ni PostgreSQL", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 502 }));
    vi.stubGlobal("fetch", fetchMock);
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Estimador de proyectos" })).toBeInTheDocument();
    expect(screen.getByLabelText("Descripción del proyecto o transcripción")).toBeEnabled();
    const nav = screen.getByRole("navigation", { name: "Principal" });
    for (const name of ["Nueva estimación", "Historial", "RAG · Chunking Lab", "Ajustes"]) expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Nueva estimación" })).toHaveAttribute("aria-current", "page");
    expect(document.getElementById("primary-model")).toBeNull();
    await user().click(within(nav).getByRole("link", { name: "Historial" }));
    expect(await screen.findByRole("heading", { name: "Historial" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Historial" })).toHaveAttribute("aria-current", "page");
  });

  test("un valor ausente no deja indicador", async () => {
    mockApi(route("GET", "/api/v1/ai/primary-model", () => json({ model: null })));
    renderApp("/estimations/abc");
    await screen.findByRole("heading", { name: "No se pudo completar la operación" });
    expect(document.getElementById("primary-model")).toBeNull();
  });
});

describe("acceso restringido", () => {
  test.each([
    ["/settings", SETTINGS],
    ["/rag/chunking-comparisons", LAB],
    ["/rag/chunking-comparisons/new", `${LAB}/options`],
    ["/rag/chunking-comparisons/9007199254740993", `${LAB}/9007199254740993`],
  ])("la entrada directa a %s muestra el estado restringido sin datos y permite volver", async (path, api) => {
    const mock = mockApi(denied(api));
    renderApp(path);
    expect(await screen.findByRole("heading", { name: "Acceso restringido" })).toBeInTheDocument();
    expect(document.getElementById("access-restricted")).toHaveTextContent("operadores autorizados");
    expect(document.body).not.toHaveTextContent("Modelo primario");
    expect(document.body).not.toHaveTextContent("Estructural");
    expect(screen.getByRole("link", { name: "Ajustes" })).toBeInTheDocument(); // la navegación sigue disponible
    await user().click(screen.getByRole("link", { name: "← Volver a estimaciones" }));
    expect(await screen.findByRole("heading", { name: "Estimador de proyectos" })).toBeInTheDocument();
    expect(mock.calls.filter((call) => call.url.pathname.startsWith("/api/v1/ai/settings") || call.url.pathname.startsWith(LAB)).length).toBe(1);
  });
});

describe("SettingsPage", () => {
  test("muestra los siete knobs con su vigente, el override marcado y los embeddings de solo lectura", async () => {
    mockApi(route("GET", SETTINGS, () => json(settingsBody({ critic_model: "gpt-4o" }))));
    renderApp("/settings");
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(1 + KNOBS.length);
    expect(KNOBS.map(([key]) => document.getElementById(`knob-${key}`))).not.toContain(null);
    const critic = document.getElementById("knob-critic_model")!;
    expect(within(critic).getByText("override")).toBeInTheDocument();
    expect(within(critic).getByLabelText("Crítico (ACB)")).toHaveValue("gpt-4o");
    expect(within(document.getElementById("knob-primary_model")!).queryByText("override")).toBeNull();
    expect(within(document.getElementById("knob-primary_model")!).getByLabelText("Modelo primario")).toHaveValue("");
    expect(within(document.getElementById("knob-fallback_model")!).getAllByText("—", { selector: "code" })).toHaveLength(2); // sin valor por defecto ni vigente
    const embeddings = document.getElementById("embedding-model")!;
    expect(embeddings).toHaveTextContent("text-embedding-3-small");
    expect(embeddings).toHaveTextContent("Solo lectura");
    expect(within(embeddings).queryByRole("combobox")).toBeNull();
  });

  test("los chunkers solo ofrecen los modelos de su proveedor", async () => {
    mockApi(route("GET", SETTINGS, () => json(settingsBody())));
    renderApp("/settings");
    await screen.findByRole("table");
    const options = (label: string) =>
      within(screen.getByLabelText(label)).getAllByRole("option").map((option) => (option as HTMLOptionElement).value).filter(Boolean);
    expect(options("Chunker proposicional")).toEqual(["gpt-4o-mini", "gpt-4o"]);
    expect(options("Chunker contextual")).toEqual(["claude-haiku-4-5", "claude-sonnet-4-5"]);
    expect(options("Modelo primario")).toHaveLength(4);
  });

  test("guarda los siete campos, envía null para vaciar, confirma y vuelve a consultar el indicador", async () => {
    let model = "gpt-4o-mini";
    const mock = mockApi(
      route("GET", "/api/v1/ai/primary-model", () => json({ model })),
      route("GET", SETTINGS, () => json(settingsBody({ critic_model: "gpt-4o" }))),
      route("PUT", SETTINGS, () => { model = "gpt-4o"; return json(settingsBody({ primary_model: "gpt-4o" })); }),
    );
    renderApp("/settings");
    await screen.findByRole("table");
    await user().selectOptions(screen.getByLabelText("Modelo primario"), "gpt-4o");
    await user().selectOptions(screen.getByLabelText("Crítico (ACB)"), ""); // restablecer
    const before = mock.callsTo("/api/v1/ai/primary-model").length;
    await user().click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByText("Modelos actualizados. El cambio aplica desde la siguiente solicitud.")).toBeInTheDocument();
    const put = mock.calls.find((call) => call.init.method === "PUT")!;
    expect(put.url.pathname).toBe(SETTINGS);
    expect((put.init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    const sent = JSON.parse(put.init.body as string).models;
    expect(Object.keys(sent)).toEqual(KNOBS.map(([key]) => key));
    expect(sent.primary_model).toBe("gpt-4o");
    expect(sent.critic_model).toBeNull();
    expect(sent.fallback_model).toBeNull();
    // El formulario refleja lo guardado y la barra consulta el modelo nuevo.
    expect(within(document.getElementById("knob-primary_model")!).getByLabelText("Modelo primario")).toHaveValue("gpt-4o");
    await waitFor(() => expect(mock.callsTo("/api/v1/ai/primary-model").length).toBeGreaterThan(before));
    expect(await screen.findByText("gpt-4o", { selector: "#primary-model" })).toBeInTheDocument();
  });

  test("un rechazo muestra el aviso saneado con la variable conocida, vuelve a leer lo vigente y conserva el formulario", async () => {
    const mock = mockApi(
      route("GET", SETTINGS, () => json(settingsBody())),
      route("PUT", SETTINGS, () => json({ detail: "Cambio rechazado: el modelo claude-haiku-4-5 requiere ANTHROPIC_API_KEY." }, 422)),
    );
    renderApp("/settings");
    await screen.findByRole("table");
    await user().selectOptions(screen.getByLabelText("Modelo primario"), "claude-haiku-4-5");
    await user().click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("requiere ANTHROPIC_API_KEY");
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.queryByText("Modelos actualizados", { exact: false })).toBeNull();
    expect(mock.callsTo(SETTINGS).filter((call) => !call.init.method || call.init.method === "GET")).toHaveLength(2);
    expect(screen.getByLabelText("Modelo primario")).toHaveValue(""); // lo vigente, no lo rechazado
  });

  test.each([[503, "Almacén no disponible."], [504, "El servicio IA no respondió a tiempo. Inténtalo de nuevo."], [502, "La API del estimador no pudo completar la solicitud. Inténtalo de nuevo."]])(
    "un %i al guardar se muestra y no oculta el formulario", async (status, detail) => {
      mockApi(route("GET", SETTINGS, () => json(settingsBody())), route("PUT", SETTINGS, () => json({ detail }, status)));
      renderApp("/settings");
      await screen.findByRole("table");
      await user().selectOptions(screen.getByLabelText("Resumen y compresión"), "gpt-4o");
      await user().click(screen.getByRole("button", { name: "Guardar" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(detail);
      expect(screen.getByRole("table")).toBeInTheDocument();
    });

  test("si falla la lectura inicial muestra el aviso sin formulario y permite reintentar", async () => {
    let healthy = false;
    mockApi(route("GET", SETTINGS, () => (healthy ? json(settingsBody()) : json({ detail: "Servicio no disponible." }, 503))));
    renderApp("/settings");
    expect(await screen.findByRole("alert")).toHaveTextContent("Servicio no disponible.");
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("button", { name: "Guardar" })).toBeNull();
    healthy = true;
    await user().click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByRole("table")).toBeInTheDocument();
  });

  test("si tras un rechazo tampoco se puede leer lo vigente, la pantalla queda sin formulario", async () => {
    let reads = 0;
    mockApi(
      route("GET", SETTINGS, () => (++reads === 1 ? json(settingsBody()) : json({ detail: "x" }, 503))),
      route("PUT", SETTINGS, () => json({ detail: "Rechazado." }, 422)),
    );
    renderApp("/settings");
    await screen.findByRole("table");
    await user().click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByText("No se puede mostrar la configuración ahora mismo.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("alert")).toHaveTextContent("Rechazado.");
  });

  test("un 403 al guardar pasa al estado restringido sin mostrar los datos", async () => {
    mockApi(route("GET", SETTINGS, () => json(settingsBody())), denied(SETTINGS, "PUT"));
    renderApp("/settings");
    await screen.findByRole("table");
    await user().click(screen.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByRole("heading", { name: "Acceso restringido" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  test("un cuerpo fuera de contrato es una respuesta inválida", async () => {
    mockApi(route("GET", SETTINGS, () => json({ models: { primary_model: { effective: 3 } }, fields: [], available_models: [] })));
    renderApp("/settings");
    expect(await screen.findByRole("alert")).toHaveTextContent("respuesta inválida");
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("LabNewPage", () => {
  const options = route("GET", `${LAB}/options`, () => json(labOptionsBody()));

  test("muestra las ocho estrategias con solo las gratuitas marcadas, avisos de clave y top_k 3 con límites 1–10", async () => {
    mockApi(options);
    renderApp("/rag/chunking-comparisons/new");
    await screen.findByRole("heading", { name: "Chunking Lab" });
    const boxes = screen.getAllByRole("checkbox").filter((box) => box.id.startsWith("strategy_"));
    expect(boxes).toHaveLength(8);
    expect(boxes.filter((box) => (box as HTMLInputElement).checked).map((box) => box.id)).toEqual(["strategy_structural", "strategy_fixed_size", "strategy_recursive"]);
    expect(screen.getByLabelText(/Contextual retrieval/)).not.toBeChecked();
    expect(document.getElementById("strategy_contextual_retrieval")!.closest(".strategy")).toHaveTextContent("requiere ANTHROPIC_API_KEY");
    expect(document.getElementById("strategy_semantic")!.closest(".strategy")).toHaveTextContent("de pago (embeddings)");
    const topK = screen.getByLabelText("Resultados por consulta (top-k)");
    expect(topK).toHaveValue(3);
    expect(topK).toHaveAttribute("min", "1");
    expect(topK).toHaveAttribute("max", "10");
    expect(screen.getByLabelText("¿Cómo se estima un login con OAuth?")).not.toBeChecked();
    expect(document.getElementById("paid-warning")).toBeNull();
    await user().click(screen.getByLabelText(/Contextual retrieval/));
    expect(document.getElementById("paid-warning")).toHaveTextContent("ANTHROPIC_API_KEY");
    expect(document.getElementById("paid-warning")).toHaveTextContent("hasta 600 s");
  });

  test("envía estrategias, consultas, consultas propias y top_k, y navega al detalle con el ID textual", async () => {
    const mock = mockApi(options, route("POST", LAB, () => json(comparisonBody(), 201)),
      route("GET", `${LAB}/9007199254740993`, () => json(comparisonBody())));
    renderApp("/rag/chunking-comparisons/new");
    await screen.findByRole("heading", { name: "Chunking Lab" });
    await user().click(screen.getByLabelText(/Jerárquico/));
    await user().click(screen.getByLabelText("Pasarela de pago con Stripe"));
    fireEvent.change(screen.getByLabelText("Consultas propias (una por línea)"), { target: { value: "mi consulta\notra" } });
    fireEvent.change(screen.getByLabelText("Resultados por consulta (top-k)"), { target: { value: "7" } });
    await user().click(screen.getByRole("button", { name: "Comparar" }));

    expect(await screen.findByRole("heading", { name: "Resultado de la comparación" })).toBeInTheDocument();
    const post = mock.calls.find((call) => call.init.method === "POST" && call.url.pathname === LAB)!;
    expect(JSON.parse(post.init.body as string)).toEqual({
      strategies: ["structural", "fixed_size", "recursive", "hierarchical"],
      queries: ["Pasarela de pago con Stripe"],
      custom_queries: "mi consulta\notra",
      top_k: 7,
    });
    expect(mock.calls.filter((call) => call.init.method === "POST" && call.url.pathname === LAB)).toHaveLength(1);
    expect(mock.calls.some((call) => call.url.pathname === `${LAB}/9007199254740993`)).toBe(true); // dígitos exactos
  });

  test.each([["99999999999999999999999", 10], ["-99999999999999999999999", 1], ["", undefined], ["0", 0], ["15", 15]])(
    "top_k %j: se serializa como entero (%s) y Go lo normaliza", async (typed, expected) => {
      const mock = mockApi(options, route("POST", LAB, () => json(comparisonBody({ id: null }), 200)));
      renderApp("/rag/chunking-comparisons/new");
      await screen.findByRole("heading", { name: "Chunking Lab" });
      fireEvent.change(screen.getByLabelText("Resultados por consulta (top-k)"), { target: { value: typed } });
      await user().click(screen.getByRole("button", { name: "Comparar" }));
      await screen.findByRole("heading", { name: "Resultado de la comparación" });
      const body = JSON.parse(mock.calls.find((call) => call.init.method === "POST" && call.url.pathname === LAB)!.init.body as string);
      expect(body.top_k).toBe(expected);
      expect("top_k" in body).toBe(expected !== undefined);
    });

  test("sin estrategias avisa localmente y no llama a Go", async () => {
    const mock = mockApi(options);
    renderApp("/rag/chunking-comparisons/new");
    await screen.findByRole("heading", { name: "Chunking Lab" });
    for (const name of ["Estructural", "Tamaño fijo", "Recursivo"]) await user().click(screen.getByLabelText(new RegExp(name)));
    await user().click(screen.getByRole("button", { name: "Comparar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Selecciona al menos una estrategia.");
    expect(mock.calls.filter((call) => call.init.method === "POST" && call.url.pathname === LAB)).toHaveLength(0);
  });

  test.each([
    [422, "Petición inválida: Estrategia no soportada"],
    [503, "El servicio IA no puede ejecutar esa comparación: Falta ANTHROPIC_API_KEY."],
    [504, "El servicio IA no respondió en 600 s. Las estrategias de pago pueden tardar varios minutos: prueba con menos estrategias."],
    [502, "La API del estimador no pudo completar la solicitud. Inténtalo de nuevo."],
  ])("un %i muestra el aviso y conserva el formulario", async (status, detail) => {
    mockApi(options, route("POST", LAB, () => json({ detail }, status)));
    renderApp("/rag/chunking-comparisons/new");
    await screen.findByRole("heading", { name: "Chunking Lab" });
    await user().click(screen.getByLabelText(/Contextual retrieval/));
    fireEvent.change(screen.getByLabelText("Consultas propias (una por línea)"), { target: { value: "no perder esto" } });
    await user().click(screen.getByRole("button", { name: "Comparar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(detail);
    expect(screen.getByLabelText(/Contextual retrieval/)).toBeChecked();
    expect(screen.getByLabelText("Consultas propias (una por línea)")).toHaveValue("no perder esto");
    expect(screen.getByRole("button", { name: "Comparar" })).toBeEnabled();
  });

  test("con el servicio caído no expone detalles internos", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: string) => {
      if (String(input).endsWith("/options")) return json(labOptionsBody());
      if (String(input).includes("primary-model")) return json({ model: null });
      throw new TypeError("Failed to fetch http://interna:8000");
    }));
    renderApp("/rag/chunking-comparisons/new");
    await screen.findByRole("heading", { name: "Chunking Lab" });
    await user().click(screen.getByRole("button", { name: "Comparar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo conectar con la API del estimador.");
    expect(document.body).not.toHaveTextContent("interna");
  });

  test("si el guardado falló muestra el resultado calculado con su aviso y sin ID ni enlace permanente", async () => {
    mockApi(options, route("POST", LAB, () => json(comparisonBody({ id: null, created_at: null, warning: "La comparación se calculó, pero no se pudo guardar en el historial." }), 200)));
    renderApp("/rag/chunking-comparisons/new");
    await screen.findByRole("heading", { name: "Chunking Lab" });
    await user().click(screen.getByRole("button", { name: "Comparar" }));
    expect(await screen.findByRole("heading", { name: "Resultado de la comparación" })).toBeInTheDocument();
    expect(document.getElementById("comparison-warning")).toHaveTextContent("no se pudo guardar en el historial");
    expect(document.getElementById("comparison-meta")).not.toHaveTextContent("Ejecutada el");
    expect(document.getElementById("stats-structural")).toBeInTheDocument();
  });

  test("muestra el indicador de carga con el temporizador mientras calcula", async () => {
    mockApi(options, hanging("POST", LAB));
    renderApp("/rag/chunking-comparisons/new");
    await screen.findByRole("heading", { name: "Chunking Lab" });
    expect(document.getElementById("loading")).not.toHaveClass("active");
    await user().click(screen.getByRole("button", { name: "Comparar" }));
    expect(document.getElementById("loading")).toHaveClass("active");
    expect(screen.getByRole("button", { name: "Comparar" })).toBeDisabled();
  });

  test("cancelar aborta la solicitud, rehabilita el formulario, no muestra resultado parcial y no reenvía", async () => {
    const started = vi.fn();
    const mock = mockApi(options, hanging("POST", LAB, started));
    renderApp("/rag/chunking-comparisons/new");
    await screen.findByRole("heading", { name: "Chunking Lab" });
    await user().click(screen.getByRole("button", { name: "Comparar" }));
    await waitFor(() => expect(started).toHaveBeenCalledTimes(1));
    await user().click(screen.getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Comparar" })).toBeEnabled());
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Resultado de la comparación" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancelar" })).toBeNull();
    const posts = mock.calls.filter((call) => call.init.method === "POST" && call.url.pathname === LAB);
    expect(posts).toHaveLength(1);
    expect(posts[0].init.signal?.aborted).toBe(true);
  });

  test("salir de la pantalla durante el cálculo aborta la solicitud", async () => {
    const started = vi.fn();
    const mock = mockApi(options, hanging("POST", LAB, started));
    renderApp("/rag/chunking-comparisons/new");
    await screen.findByRole("heading", { name: "Chunking Lab" });
    await user().click(screen.getByRole("button", { name: "Comparar" }));
    await waitFor(() => expect(started).toHaveBeenCalled());
    await user().click(screen.getByRole("link", { name: "Historial" }));
    await waitFor(() => expect(mock.calls.find((call) => call.init.method === "POST" && call.url.pathname === LAB)!.init.signal?.aborted).toBe(true));
  });

  test("un 403 al comparar muestra el estado restringido", async () => {
    mockApi(options, denied(LAB, "POST"));
    renderApp("/rag/chunking-comparisons/new");
    await screen.findByRole("heading", { name: "Chunking Lab" });
    await user().click(screen.getByRole("button", { name: "Comparar" }));
    expect(await screen.findByRole("heading", { name: "Acceso restringido" })).toBeInTheDocument();
  });

  test("si no cargan las opciones avisa y permite reintentar", async () => {
    let up = false;
    mockApi(route("GET", `${LAB}/options`, () => (up ? json(labOptionsBody()) : json({ detail: "x" }, 502))));
    renderApp("/rag/chunking-comparisons/new");
    expect(await screen.findByRole("alert")).toHaveTextContent("no pudo completar");
    up = true;
    await user().click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByLabelText(/Estructural/)).toBeInTheDocument();
  });
});

describe("LabHistoryPage", () => {
  const summary = (id: string | null, overrides = {}) => { const { result: _result, warning: _warning, ...rest } = comparisonBody({ id }); return { ...rest, ...overrides }; };

  test("lista las ejecuciones recientes con enlaces de ID decimal exacto", async () => {
    mockApi(route("GET", LAB, () => json({
      items: [summary("9007199254740993"), summary("9007199254740992", { duration_ms: null, queries: [], total_ingestion_cost_usd: 0 })],
      warning: null,
    })));
    renderApp("/rag/chunking-comparisons");
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("link", { name: "Ver" })).toHaveAttribute("href", "/rag/chunking-comparisons/9007199254740993");
    expect(within(rows[1]).getByRole("link", { name: "Ver" })).toHaveAttribute("href", "/rag/chunking-comparisons/9007199254740992");
    expect(rows[0]).toHaveTextContent("Estructural, Jerárquico, Contextual retrieval");
    expect(rows[0]).toHaveTextContent("05/10/2026 10:30 UTC");
    expect(rows[0]).toHaveTextContent("3.2 s");
    expect(rows[1]).toHaveTextContent("—");
  });

  test("sin datos invita a crear la primera y con repositorio caído muestra el aviso", async () => {
    mockApi(route("GET", LAB, () => json({ items: [], warning: "El historial no está disponible en este momento." })));
    renderApp("/rag/chunking-comparisons");
    expect(await screen.findByText("El historial no está disponible en este momento.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Crea la primera" })).toHaveAttribute("href", "/rag/chunking-comparisons/new");
  });

  test("un fallo de Go se muestra con reintento", async () => {
    mockApi(route("GET", LAB, () => json({ detail: "x" }, 502)));
    renderApp("/rag/chunking-comparisons");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});

describe("LabDetailPage", () => {
  test("pide el ID tal cual y muestra estadísticas, barras de coste y playground jerárquico", async () => {
    const mock = mockApi(route("GET", `${LAB}/9007199254740993`, () => json(comparisonBody())));
    renderApp("/rag/chunking-comparisons/9007199254740993");
    expect(await screen.findByRole("heading", { name: "Resultado de la comparación" })).toBeInTheDocument();
    expect(mock.calls.find((call) => call.url.pathname.startsWith(LAB))!.url.pathname).toBe(`${LAB}/9007199254740993`);
    expect(document.getElementById("comparison-meta")).toHaveTextContent("Ejecutada el 05/10/2026 10:30 UTC · 18 presupuestos · 3.2 s · coste de ingesta 0,140000 USD");

    const stats = document.getElementById("stats-structural")!;
    expect(stats).toHaveTextContent("Estructural104079,0120,53002 ⚠000,01"); // chunks, mín, p50, p95, máx, huérfanos, obesos, extra, s
    expect(within(stats).getByText("2 ⚠")).toBeInTheDocument(); // huérfanos
    expect(within(document.getElementById("stats-hierarchical")!).getByText("1 ⚠")).toBeInTheDocument(); // obesos

    const bars = document.getElementById("cost-bars")!;
    expect(within(document.getElementById("cost-contextual_retrieval")!).getByRole("img")).toBeInTheDocument();
    expect((within(bars).getAllByRole("img")[2].firstChild as HTMLElement).style.width).toBe("100%");
    expect((within(bars).getAllByRole("img")[0].firstChild as HTMLElement).style.width).toBe("0%");
    expect(document.getElementById("cost-structural")).toHaveTextContent("gratis");
    expect(document.getElementById("cost-contextual_retrieval")).toHaveTextContent("0,140000 USD");

    const hierarchical = document.getElementById("query-0-hierarchical")!;
    expect(within(hierarchical).getByText("padre")).toBeInTheDocument();
    expect(hierarchical).toHaveTextContent("hijo de BUD-1::parent");
    expect(within(hierarchical).getByRole("img", { name: "Similitud 71%" })).toBeInTheDocument();
    expect(within(document.getElementById("query-0-structural")!).queryByText("padre")).toBeNull();
    expect(within(document.getElementById("query-0-structural")!).getByText("0,640")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "← Nueva comparación" })).toBeInTheDocument();
  });

  test("las barras de coste son proporcionales al mayor coste", async () => {
    const detail = comparisonBody({
      result: { stats_per_strategy: [statsRow("semantic", 0.02), statsRow("propositional", 0.08)], queries_per_strategy: [] },
    });
    mockApi(route("GET", `${LAB}/5`, () => json(detail)));
    renderApp("/rag/chunking-comparisons/5");
    await screen.findByRole("heading", { name: "Resultado de la comparación" });
    const bars = within(document.getElementById("cost-bars")!).getAllByRole("img");
    expect((bars[0].firstChild as HTMLElement).style.width).toBe("25%");
    expect((bars[1].firstChild as HTMLElement).style.width).toBe("100%");
  });

  test("solo estadísticas y todas gratuitas: lo indica y no muestra playground ni barras", async () => {
    const detail = comparisonBody({
      result: { stats_per_strategy: [statsRow("structural", 0), statsRow("recursive", 0)], queries_per_strategy: [] },
      total_ingestion_cost_usd: 0,
    });
    mockApi(route("GET", `${LAB}/5`, () => json(detail)));
    renderApp("/rag/chunking-comparisons/5");
    await screen.findByRole("heading", { name: "Resultado de la comparación" });
    expect(document.getElementById("lab-no-queries")).toHaveTextContent("no tuvo consultas");
    expect(document.getElementById("lab-playground")).toBeNull();
    expect(document.getElementById("cost-free")).toBeInTheDocument();
    expect(document.getElementById("cost-bars")).toBeNull();
  });

  test.each([[404, "No se encontró la comparación solicitada."], [500, "El historial no está disponible en este momento."]])(
    "un %i muestra el error saneado con enlaces de vuelta", async (status, detail) => {
      mockApi(route("GET", `${LAB}/9`, () => json({ detail }, status)));
      renderApp("/rag/chunking-comparisons/9");
      expect(await screen.findByRole("alert")).toHaveTextContent(detail);
      expect(screen.getByRole("link", { name: "← Historial" })).toBeInTheDocument();
    });

  test("un ID que no es decimal canónico es «no encontrada» sin llamar a Go", async () => {
    const mock = mockApi();
    renderApp("/rag/chunking-comparisons/007");
    expect(await screen.findByRole("alert")).toHaveTextContent("No se encontró la comparación solicitada.");
    expect(mock.calls.filter((call) => call.url.pathname.startsWith(LAB))).toHaveLength(0);
  });

  test("un ID numérico en el JSON (fuera de contrato) es una respuesta inválida", async () => {
    mockApi(route("GET", `${LAB}/5`, () => new Response('{"id":9007199254740993}', { status: 200 })));
    renderApp("/rag/chunking-comparisons/5");
    expect(await screen.findByRole("alert")).toHaveTextContent("respuesta inválida");
  });
});
