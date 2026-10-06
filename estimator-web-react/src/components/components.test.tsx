import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { EstimationResponse } from "../api/types";
import { EstimationDetail } from "./EstimationDetail";
import { EstimationResult } from "./EstimationResult";
import { ErrorPage, NotFoundPage } from "./ErrorPage";
import { Layout } from "./Layout";
import { PromptSidebar } from "./PromptSidebar";
import { WithSidebar } from "./WithSidebar";

function estimation(overrides: Partial<EstimationResponse["result"]> = {}, extra: Partial<EstimationResponse> = {}): EstimationResponse {
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
      ...overrides,
    },
    id: 7,
    prompt_version: "v3",
    cache_source: "semantic",
    options: { project_type: "web_saas", detail_level: "medium", output_format: "phases_table" },
    requested_at: "2026-05-20T10:05:00Z",
    description: "Descripción original",
    ...extra,
  };
}

describe("Layout y barra lateral", () => {
  function renderPage() {
    return render(
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<WithSidebar sidebar={<p>contenido de barra</p>}><p>principal</p></WithSidebar>} />
            <Route path="/estimations" element={<p>historial</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
  }

  test("la cabecera enlaza a nueva estimación e historial", () => {
    renderPage();
    expect(screen.getByRole("link", { name: "Nueva estimación" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Historial" })).toHaveAttribute("href", "/estimations");
  });

  test("el botón oculta y vuelve a mostrar la barra con aria-expanded", async () => {
    renderPage();
    const toggle = await screen.findByRole("button", { name: "«" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAttribute("aria-controls", "sidebar");
    const layout = document.getElementById("layout")!;
    expect(layout).not.toHaveClass("collapsed");

    await userEvent.click(toggle);
    expect(layout).toHaveClass("collapsed");
    expect(screen.getByRole("button", { name: "»" })).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(screen.getByRole("button", { name: "»" }));
    expect(layout).not.toHaveClass("collapsed");
  });
});

describe("PromptSidebar", () => {
  const preview = {
    system_prompt: "Eres un estimador",
    prompt_version: "v3",
    examples: [{ title: "Ejemplo 1", description: "App de reparto" }],
  };

  test("muestra el prompt de solo lectura, los ejemplos y el estado vacío de métricas", () => {
    render(<PromptSidebar preview={preview} />);
    const prompt = screen.getByLabelText("System prompt");
    expect(prompt).toHaveValue("Eres un estimador");
    expect(prompt).toHaveAttribute("readonly");
    expect(screen.getByText("Ejemplo 1")).toBeInTheDocument();
    expect(screen.getByText("Aún no se ha generado ninguna estimación.")).toBeInTheDocument();
  });

  test("muestra las métricas de la última llamada", () => {
    render(
      <PromptSidebar
        preview={preview}
        promptVersion="v3"
        metrics={{ model: "claude", usage: { input_tokens: 12345, output_tokens: 678 }, latency_ms: 1500, request_cost_usd: 0.0123, cache_hit: false }}
      />,
    );
    expect(screen.getByText("claude")).toBeInTheDocument();
    expect(document.getElementById("metric-input-tokens")).toHaveTextContent("12.345");
    expect(document.getElementById("metric-output-tokens")).toHaveTextContent("678");
    expect(document.getElementById("metric-latency")).toHaveTextContent("1.500");
    expect(document.getElementById("metric-cost")).toHaveTextContent("0,012300 USD");
    expect(document.getElementById("metric-prompt-version")).toHaveTextContent("v3");
    expect(screen.getByText("Respuesta generada")).toBeInTheDocument();
  });

  test("indica respuesta de caché, modelo desconocido y «Sin tarifa»", () => {
    render(<PromptSidebar preview={preview} metrics={{ cache_hit: true, request_cost_usd: null }} />);
    expect(screen.getByText("Respuesta de caché")).toBeInTheDocument();
    expect(screen.getByText("Desconocido")).toBeInTheDocument();
    expect(screen.getByText("Sin tarifa")).toBeInTheDocument();
  });

  test("sin prompt avisa de que no está disponible y el resto sigue", () => {
    render(<PromptSidebar preview={null} />);
    expect(screen.getByText("El contexto del prompt no está disponible en este momento.")).toBeInTheDocument();
    expect(screen.getByText("Aún no se ha generado ninguna estimación.")).toBeInTheDocument();
  });

  test("mientras carga muestra un estado de carga, no el aviso de error", () => {
    render(<PromptSidebar preview={null} loading />);
    expect(screen.getByRole("status")).toHaveTextContent("Cargando");
    expect(screen.queryByText(/no está disponible/)).not.toBeInTheDocument();
  });
});

describe("EstimationResult", () => {
  test("resultado estimable: cifras en formato español y una fila por fase", () => {
    render(<EstimationResult estimation={estimation()} />);
    expect(screen.getByText("Portal de clientes")).toBeInTheDocument();
    expect(document.getElementById("confidence")).toHaveTextContent("80%");
    expect(document.getElementById("duration")).toHaveTextContent("8,5 semanas");
    expect(document.getElementById("cost")).toHaveTextContent("20.000,00 EUR");
    const rows = within(document.getElementById("phases")!).getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[2]).toHaveTextContent("Desarrollo");
    expect(rows[2]).toHaveTextContent("6,5");
    expect(rows[2]).toHaveTextContent("15.000,00 EUR");
  });

  test("baja confianza: «No estimable» sin cifras de coste ni duración", () => {
    render(
      <EstimationResult
        estimation={estimation({ out_of_scope: true, confidence_pct: 12, summary: "Out of scope: faltan datos" })}
      />,
    );
    const alert = document.getElementById("out-of-scope")!;
    expect(alert).toHaveTextContent("No estimable. faltan datos");
    expect(alert).toHaveTextContent("Confianza 12%");
    expect(document.getElementById("cost")).toBeNull();
    expect(document.getElementById("duration")).toBeNull();
    expect(document.getElementById("phases")).toBeNull();
  });
});

describe("EstimationDetail", () => {
  test("muestra las opciones, la procedencia, la fecha y el identificador", () => {
    render(<EstimationDetail estimation={estimation()} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Estimación #7");
    expect(document.getElementById("estimation-meta")).toHaveTextContent(
      "SaaS web · detalle medio · tabla de fases · prompt v3 · Caché semántica · 20/05/2026 10:05 UTC",
    );
    expect(document.getElementById("description-text")).toHaveTextContent("Descripción original");
  });

  test("sin identificador ni fecha no los muestra", () => {
    render(<EstimationDetail estimation={estimation({}, { id: undefined, requested_at: undefined })} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/^Estimación$/);
    expect(document.getElementById("estimation-meta")).not.toHaveTextContent("UTC");
  });

  test("trunca la descripción a 2000 caracteres e indica el total", () => {
    render(<EstimationDetail estimation={estimation({}, { description: "a".repeat(2500) })} />);
    expect(document.getElementById("description-text")!.textContent).toHaveLength(2000);
    expect(screen.getByText("2.500 caracteres en total.")).toBeInTheDocument();
  });

  test("una descripción corta no muestra el total", () => {
    render(<EstimationDetail estimation={estimation()} />);
    expect(screen.queryByText(/caracteres en total/)).not.toBeInTheDocument();
  });
});

describe("ErrorPage y NotFoundPage", () => {
  test("la pantalla de error anuncia el mensaje y enlaza a historial y nueva estimación", () => {
    render(
      <MemoryRouter>
        <ErrorPage message="No se encontró la estimación solicitada." />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "No se pudo completar la operación" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("No se encontró la estimación solicitada.");
    expect(screen.getByRole("link", { name: "← Historial" })).toHaveAttribute("href", "/estimations");
    expect(screen.getByRole("link", { name: "Nueva estimación" })).toHaveAttribute("href", "/");
    expect(document.getElementById("sidebar")).toBeNull();
  });

  test("la página 404 ofrece enlaces de vuelta", () => {
    render(
      <MemoryRouter>
        <NotFoundPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { name: "Página no encontrada" })).toBeInTheDocument();
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });
});
