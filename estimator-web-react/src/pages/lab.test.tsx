import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App } from "../App";
import type { Comparison, LabOptions } from "../api/types";
import { json, mockApi } from "../test/mockApi";

function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

const user = () => userEvent.setup({ applyAccept: false });

const OPTIONS: LabOptions = {
  strategies: [
    { name: "structural", label: "Estructural", description: "Un componente es un chunk.", cost_tier: "free", cost_label: "gratis", paid: false, key_name: "", default_checked: true },
    { name: "hierarchical", label: "Jerárquico", description: "Dos niveles.", cost_tier: "free", cost_label: "gratis", paid: false, key_name: "", default_checked: false },
    { name: "contextual_retrieval", label: "Contextual retrieval", description: "Un LLM sitúa cada chunk.", cost_tier: "expensive", cost_label: "de pago (LLM)", paid: true, key_name: "ANTHROPIC_API_KEY", default_checked: false },
  ],
  default_strategies: ["structural"],
  sample_queries: ["autenticación oauth", "panel de administración"],
  default_top_k: 3,
  compare_timeout_seconds: 600,
};

function stats(strategy: string, cost: number) {
  return {
    strategy, n_chunks: 10, token_distribution: { min: 40, p50: 79, p95: 120.5, max: 300 }, n_orphan_chunks: strategy === "structural" ? 2 : 0,
    n_obese_chunks: 0, ingestion_cost_usd: cost, extra_api_calls: 0, ingestion_seconds: 0.012,
  };
}

function comparison(overrides: Partial<Comparison> = {}): Comparison {
  return {
    id: 1, strategies: ["structural", "hierarchical", "contextual_retrieval"],
    strategy_labels: ["Estructural", "Jerárquico", "Contextual retrieval"], queries: ["oauth"], top_k: 3, corpus_label: "corpus",
    corpus_count: 18, duration_ms: 3200, created_at: "2026-10-05T10:30:00Z", saved: true, total_ingestion_cost_usd: 0.14,
    response: {
      stats_per_strategy: { structural: stats("structural", 0), hierarchical: stats("hierarchical", 0), contextual_retrieval: stats("contextual_retrieval", 0.14) },
      queries_per_strategy: {
        structural: [{ strategy: "structural", query: "oauth", top_k: [{ chunk_id: "BUD-1::AUTH-1", cosine: 0.64, text_preview: "Vista previa AUTH" }] }],
        hierarchical: [{
          strategy: "hierarchical", query: "oauth",
          top_k: [
            { chunk_id: "BUD-1::parent", cosine: 0.71, text_preview: "Padre", level: "parent", parent_chunk_id: null },
            { chunk_id: "BUD-1::AUTH-1", cosine: 0.64, text_preview: "Hijo", level: "child", parent_chunk_id: "BUD-1::parent" },
          ],
        }],
      },
    },
    ...overrides,
  };
}

const labApi = (...extra: Parameters<typeof mockApi>) =>
  mockApi(...extra, (url) => (url.pathname === "/api/chunking-comparisons/options" ? json(OPTIONS) : undefined));

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Chunking Lab · formulario", () => {
  test("solo las estrategias gratuitas vienen marcadas y las de pago avisan de su clave", async () => {
    labApi();
    renderApp("/rag/chunking_comparisons/new");

    expect(await screen.findByLabelText(/Estructural/)).toBeChecked();
    expect(screen.getByLabelText(/Jerárquico/)).not.toBeChecked();
    expect(screen.getByLabelText(/Contextual retrieval/)).not.toBeChecked();
    expect(screen.getByText("requiere ANTHROPIC_API_KEY")).toBeInTheDocument();
    expect(screen.getByLabelText("Resultados por consulta (top-k)")).toHaveValue(3);
    expect(screen.queryByText(/Has marcado estrategias de pago/)).not.toBeInTheDocument();
  });

  test("marcar una estrategia de pago muestra el aviso de coste con el tiempo máximo", async () => {
    labApi();
    renderApp("/rag/chunking_comparisons/new");

    await user().click(await screen.findByLabelText(/Contextual retrieval/));

    expect(screen.getByText(/Has marcado estrategias de pago/)).toHaveTextContent("hasta 600 s");
  });

  test("sin estrategias muestra el aviso y no llama al backend", async () => {
    const api = labApi();
    renderApp("/rag/chunking_comparisons/new");

    await user().click(await screen.findByLabelText(/Estructural/));
    await user().click(screen.getByRole("button", { name: "Comparar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Selecciona al menos una estrategia.");
    expect(api.callsTo("/api/chunking-comparisons").filter((call) => call.init.method === "POST")).toHaveLength(0);
  });

  test("envía estrategias, consultas marcadas y propias (sin repetidas) y navega al resultado", async () => {
    const api = labApi(
      (url, init) => (url.pathname === "/api/chunking-comparisons" && init.method === "POST" ? json(comparison({ id: 5 }), 201) : undefined),
      (url) => (url.pathname === "/api/chunking-comparisons/5" ? json(comparison({ id: 5 })) : undefined),
    );
    renderApp("/rag/chunking_comparisons/new");

    await user().click(await screen.findByLabelText(/Jerárquico/));
    await user().click(screen.getByLabelText("autenticación oauth"));
    await user().type(screen.getByLabelText("Consultas propias (una por línea)"), "mi consulta{enter}autenticación oauth{enter}  ");
    await user().click(screen.getByRole("button", { name: "Comparar" }));

    expect(await screen.findByRole("heading", { name: "Resultado de la comparación" })).toBeInTheDocument();
    const post = api.callsTo("/api/chunking-comparisons").find((call) => call.init.method === "POST")!;
    expect(JSON.parse(post.init.body as string)).toEqual({
      strategies: ["structural", "hierarchical"], queries: ["autenticación oauth", "mi consulta"], top_k: 3,
    });
  });

  test("un error del backend se muestra saneado y el formulario conserva lo elegido", async () => {
    labApi((url, init) =>
      url.pathname === "/api/chunking-comparisons" && init.method === "POST"
        ? json({ detail: "El servicio IA no respondió en 600 s. Las estrategias de pago pueden tardar varios minutos: prueba con menos estrategias." }, 504)
        : undefined,
    );
    renderApp("/rag/chunking_comparisons/new");

    await user().click(await screen.findByLabelText(/Contextual retrieval/));
    await user().click(screen.getByRole("button", { name: "Comparar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("prueba con menos estrategias");
    expect(screen.getByLabelText(/Contextual retrieval/)).toBeChecked();
    expect(screen.getByRole("button", { name: "Comparar" })).toBeEnabled();
  });

  test("una comparación sin guardar se muestra igualmente con el aviso", async () => {
    labApi((url, init) =>
      url.pathname === "/api/chunking-comparisons" && init.method === "POST"
        ? json(comparison({ id: 0, saved: false, created_at: null, notice: "La comparación se calculó, pero no se pudo guardar en el historial." }), 201)
        : undefined,
    );
    renderApp("/rag/chunking_comparisons/new");

    await user().click(await screen.findByRole("button", { name: "Comparar" }));

    expect(await screen.findByText(/no se pudo guardar en el historial/)).toBeInTheDocument();
    expect(document.getElementById("stats-table")).toBeInTheDocument();
  });

  test("si el backend falla al cargar las opciones muestra el error", async () => {
    mockApi((url) => (url.pathname === "/api/chunking-comparisons/options" ? json({ detail: "No se pudo conectar con la API del estimador." }, 503) : undefined));
    renderApp("/rag/chunking_comparisons/new");

    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo conectar con la API del estimador.");
  });
});

describe("Chunking Lab · resultado", () => {
  test("muestra estadísticas, barras de coste y el playground con padre e hijo", async () => {
    mockApi((url) => (url.pathname === "/api/chunking-comparisons/1" ? json(comparison()) : undefined));
    renderApp("/rag/chunking_comparisons/1");

    expect(await screen.findByRole("heading", { name: "Resultado de la comparación" })).toBeInTheDocument();
    expect(document.querySelectorAll('#stats-table tbody tr')).toHaveLength(3);
    expect(document.getElementById("stats-structural")).toHaveTextContent("2 ⚠");
    expect(document.getElementById("stats-structural")).toHaveTextContent("79,0");
    expect(document.getElementById("cost-contextual_retrieval")).toHaveTextContent("0,140000 USD");
    expect(document.getElementById("cost-structural")).toHaveTextContent("gratis");
    expect(screen.getByRole("img", { name: "Similitud 71%" })).toBeInTheDocument();
    const hierarchical = within(document.getElementById("query-0-hierarchical")!);
    expect(hierarchical.getByText("padre")).toBeInTheDocument();
    expect(hierarchical.getByText(/hijo de/)).toHaveTextContent("hijo de BUD-1::parent");
    expect(document.body).toHaveTextContent("Ejecutada el 05/10/2026 10:30 UTC");
  });

  test("todas gratuitas muestra el mensaje en lugar de las barras; sin consultas no hay playground", async () => {
    const free = comparison({ strategies: ["structural"], strategy_labels: ["Estructural"], queries: [], total_ingestion_cost_usd: 0 });
    free.response = { stats_per_strategy: { structural: stats("structural", 0) }, queries_per_strategy: {} };
    mockApi((url) => (url.pathname === "/api/chunking-comparisons/1" ? json(free) : undefined));
    renderApp("/rag/chunking_comparisons/1");

    expect(await screen.findByText(/Todas las estrategias de esta ejecución son gratuitas/)).toBeInTheDocument();
    expect(document.getElementById("lab-no-queries")).toBeInTheDocument();
    expect(document.getElementById("lab-playground")).not.toBeInTheDocument();
  });

  test("una comparación inexistente muestra el error de no encontrada", async () => {
    mockApi((url) => (url.pathname === "/api/chunking-comparisons/9" ? json({ detail: "No se encontró la comparación solicitada." }, 404) : undefined));
    renderApp("/rag/chunking_comparisons/9");

    expect(await screen.findByRole("alert")).toHaveTextContent("No se encontró la comparación solicitada.");
  });

  test("un identificador inválido es «no encontrada» sin llamar al backend", async () => {
    const api = mockApi();
    renderApp("/rag/chunking_comparisons/abc");

    expect(await screen.findByRole("alert")).toHaveTextContent("No se encontró la comparación solicitada.");
    expect(api.callsTo("/api/chunking-comparisons/abc")).toHaveLength(0);
  });
});

describe("Chunking Lab · historial", () => {
  test("lista las ejecuciones con fecha, estrategias, consultas, coste y duración", async () => {
    mockApi((url) =>
      url.pathname === "/api/chunking-comparisons"
        ? json([{ ...comparison({ id: 2 }), response: undefined }, { ...comparison({ id: 1, duration_ms: null }), response: undefined }])
        : undefined,
    );
    renderApp("/rag/chunking_comparisons");

    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveTextContent("05/10/2026 10:30 UTC");
    expect(rows[1]).toHaveTextContent("Estructural, Jerárquico, Contextual retrieval");
    expect(rows[1]).toHaveTextContent("0,140000 USD");
    expect(rows[1]).toHaveTextContent("3,2 s");
    expect(rows[2]).toHaveTextContent("—");
    expect(within(rows[1]).getByRole("link", { name: "Ver" })).toHaveAttribute("href", "/rag/chunking_comparisons/2");
  });

  test("sin ejecuciones invita a crear la primera", async () => {
    mockApi((url) => (url.pathname === "/api/chunking-comparisons" ? json([]) : undefined));
    renderApp("/rag/chunking_comparisons");

    expect(await screen.findByText(/Todavía no hay comparaciones guardadas/)).toBeInTheDocument();
  });

  test("con el historial no disponible lo muestra vacío con un aviso", async () => {
    mockApi((url) => (url.pathname === "/api/chunking-comparisons" ? json({ detail: "El historial no está disponible en este momento." }, 503) : undefined));
    renderApp("/rag/chunking_comparisons");

    await waitFor(() => expect(document.getElementById("lab-history-error")).toHaveTextContent("El historial no está disponible en este momento."));
    expect(document.getElementById("lab-history-empty")).toBeInTheDocument();
  });
});
