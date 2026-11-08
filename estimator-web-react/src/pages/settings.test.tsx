import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App } from "../App";
import type { AiSettings, ModelSetting } from "../api/types";
import { json, mockApi } from "../test/mockApi";

function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

const user = () => userEvent.setup({ applyAccept: false });

const KNOBS: [string, string, string][] = [
  ["primary_model", "Modelo primario", ""],
  ["fallback_model", "Modelo de respaldo", ""],
  ["critic_model", "Crítico (ACB)", ""],
  ["metadata_model", "Extractor de metadatos", ""],
  ["summary_model", "Resumen y compresión", ""],
  ["propositional_chunker_model", "Chunker proposicional", "openai"],
  ["contextual_chunker_model", "Chunker contextual", "anthropic"],
];
const MODELS = ["gpt-4o-mini", "gpt-4o", "claude-haiku-4-5", "claude-sonnet-4-5"];

function settings(overrides: Record<string, string> = {}): AiSettings {
  const models: ModelSetting[] = KNOBS.map(([key, label, provider]) => ({
    key, label, description: `Descripción de ${label}`, provider, default: "gpt-4o-mini",
    effective: overrides[key] ?? "gpt-4o-mini", overridden: key in overrides, selected: overrides[key] ?? "",
    options: MODELS.filter((model) => (provider === "openai" ? !model.startsWith("claude") : provider === "anthropic" ? model.startsWith("claude") : true)),
  }));
  return {
    models, available_models: MODELS, embedding_model: "text-embedding-3-small",
    embedding_model_note: "Solo lectura: cambiarlo invalidaría todos los vectores guardados.", any_overridden: Object.keys(overrides).length > 0,
  };
}

const isSettings = (url: URL) => url.pathname === "/api/ai-settings";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Ajustes de IA", () => {
  test("muestra los siete knobs, marca el override y limita los chunkers a su proveedor", async () => {
    mockApi((url) => (isSettings(url) ? json(settings({ critic_model: "gpt-4o" })) : undefined));
    renderApp("/ai_settings");

    expect(await screen.findByRole("heading", { name: "Ajustes del servicio IA" })).toBeInTheDocument();
    await waitFor(() => expect(document.querySelectorAll("#models-table tbody tr")).toHaveLength(7));
    expect(document.getElementById("knob-critic_model")).toHaveTextContent("override");
    expect(screen.getByLabelText("Crítico (ACB)")).toHaveValue("gpt-4o");
    expect(screen.getByLabelText("Modelo primario")).toHaveValue("");
    const proposicional = within(screen.getByLabelText("Chunker proposicional")).getAllByRole("option").map((option) => option.textContent);
    expect(proposicional.some((text) => text?.startsWith("claude"))).toBe(false);
    expect(document.getElementById("embedding-model")).toHaveTextContent("text-embedding-3-small");
    expect(document.getElementById("embedding-model")).toHaveTextContent("Solo lectura");
  });

  test("guardar envía todos los knobs (los vacíos como null), confirma y refresca el modelo primario", async () => {
    let primary = "gpt-4o-mini";
    const api = mockApi(
      (url, init) => {
        if (isSettings(url) && init.method === "PUT") {
          primary = "gpt-4o";
          return json(settings({ primary_model: "gpt-4o" }));
        }
        return isSettings(url) ? json(settings()) : undefined;
      },
      (url) => (url.pathname === "/api/primary-model" ? json({ primary_model: primary }) : undefined),
    );
    renderApp("/ai_settings");

    await user().selectOptions(await screen.findByLabelText("Modelo primario"), "gpt-4o");
    await user().click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByText(/Modelos actualizados/)).toBeInTheDocument();
    const put = api.calls.find((call) => call.init.method === "PUT")!;
    const sent = JSON.parse(put.init.body as string).models as Record<string, string | null>;
    expect(Object.keys(sent)).toHaveLength(7);
    expect(sent.primary_model).toBe("gpt-4o");
    expect(sent.critic_model).toBeNull();
    await waitFor(() => expect(document.getElementById("primary-model")).toHaveTextContent("gpt-4o"));
    expect(screen.getByLabelText("Modelo primario")).toHaveValue("gpt-4o");
  });

  test("restablecer un knob con override envía null", async () => {
    const api = mockApi((url, init) => (isSettings(url) ? json(init.method === "PUT" ? settings() : settings({ critic_model: "gpt-4o" })) : undefined));
    renderApp("/ai_settings");

    await user().selectOptions(await screen.findByLabelText("Crítico (ACB)"), "");
    await user().click(screen.getByRole("button", { name: "Guardar" }));

    await screen.findByText(/Modelos actualizados/);
    const put = api.calls.find((call) => call.init.method === "PUT")!;
    expect(JSON.parse(put.init.body as string).models.critic_model).toBeNull();
  });

  test("un rechazo muestra el detalle del backend y mantiene el formulario", async () => {
    mockApi((url, init) =>
      isSettings(url)
        ? init.method === "PUT"
          ? json({ detail: "Cambio rechazado: falta OPENAI_API_KEY" }, 422)
          : json(settings())
        : undefined,
    );
    renderApp("/ai_settings");

    await user().selectOptions(await screen.findByLabelText("Modelo primario"), "gpt-4o");
    await user().click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Cambio rechazado: falta OPENAI_API_KEY");
    expect(screen.getByLabelText("Modelo primario")).toHaveValue("gpt-4o");
    expect(screen.getByRole("button", { name: "Guardar" })).toBeEnabled();
  });

  test("con el servicio caído al leer muestra un aviso sin formulario", async () => {
    mockApi((url) => (isSettings(url) ? json({ detail: "No se pudo conectar con la API del estimador. Inténtalo de nuevo en unos instantes." }, 503) : undefined));
    renderApp("/ai_settings");

    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo leer la configuración del servicio IA");
    expect(document.getElementById("settings-form")).not.toBeInTheDocument();
    expect(document.getElementById("settings-unavailable")).toBeInTheDocument();
  });
});

describe("Indicador del modelo primario y navegación", () => {
  test("la barra muestra el modelo primario y los enlaces a Chunking Lab y Ajustes", async () => {
    mockApi((url) => (url.pathname === "/api/primary-model" ? json({ primary_model: "gpt-4o-mini" }) : undefined));
    renderApp("/estimations");

    expect(await screen.findByRole("link", { name: "gpt-4o-mini" })).toHaveAttribute("href", "/ai_settings");
    expect(screen.getByRole("link", { name: "Chunking Lab" })).toHaveAttribute("href", "/rag/chunking_comparisons");
    expect(screen.getByRole("link", { name: /^Ajustes$/ })).toHaveAttribute("href", "/ai_settings");
  });

  test("sin modelo (servicio caído) la barra se renderiza sin indicador", async () => {
    mockApi((url) => (url.pathname === "/api/primary-model" ? json({ primary_model: "" }) : undefined));
    renderApp("/estimations");

    expect(await screen.findByRole("heading", { name: "Historial" })).toBeInTheDocument();
    expect(document.getElementById("primary-model")).not.toBeInTheDocument();
  });

  test("si el backend falla al consultar el modelo la página sigue funcionando", async () => {
    mockApi((url) => (url.pathname === "/api/primary-model" ? json({}, 500) : undefined));
    renderApp("/estimations");

    expect(await screen.findByRole("heading", { name: "Historial" })).toBeInTheDocument();
    expect(document.getElementById("primary-model")).not.toBeInTheDocument();
  });
});
