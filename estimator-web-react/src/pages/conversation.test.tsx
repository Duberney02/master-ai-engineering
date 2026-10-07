import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App } from "../App";
import { DESCRIPTION, isSessionEstimate, json, mockApi, sessionBody } from "../test/mockApi";

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

async function submit() {
  await user().click(screen.getByRole("button", { name: "Estimar" }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const metadata = {
  project_name: "Orion",
  assumed_team_size: 4,
  mentioned_technologies: ["FastAPI", "Kafka"],
  agreed_scope: "Portal y panel de administración",
};

/** Respuesta sin `estimation_id`: la estimación se muestra en línea y el formulario sigue disponible. */
const inlineAnswer = (overrides = {}) => (url: URL, init: RequestInit) =>
  isSessionEstimate(url, init) ? json(sessionBody({ estimation_id: null, ...overrides })) : undefined;

describe("Conversación con memoria", () => {
  test("crea una sesión al cargar la página y la conserva durante todos los envíos", async () => {
    const api = mockApi(inlineAnswer());
    renderApp();
    await waitFor(() => expect(api.sessions).toHaveLength(1));

    describe_(DESCRIPTION);
    await submit();
    await screen.findByRole("heading", { name: "Estimación" });
    await user().click(screen.getAllByRole("link", { name: "Nueva estimación" }).at(-1)!);
    await submit();
    await waitFor(() => expect(api.estimateCalls()).toHaveLength(2));

    expect(api.sessions).toHaveLength(1);
    expect(api.estimateCalls().map((call) => call.url.pathname)).toEqual(
      Array(2).fill(`/api/v1/sessions/${api.sessions[0]}/estimate`),
    );
  });

  test("muestra los project_metadata devueltos por la API en la barra lateral", async () => {
    mockApi(inlineAnswer({ project_metadata: metadata, turn_count: 2 }));
    renderApp();
    expect(await screen.findByText(/Aún no hay datos del proyecto/)).toBeInTheDocument();

    describe_(DESCRIPTION);
    await submit();

    await screen.findByRole("heading", { name: "Estimación" });
    expect(document.getElementById("metadata-name")).toHaveTextContent("Orion");
    expect(document.getElementById("metadata-team")).toHaveTextContent("4");
    expect(document.getElementById("metadata-technologies")).toHaveTextContent("FastAPI, Kafka");
    expect(document.getElementById("metadata-scope")).toHaveTextContent("Portal y panel de administración");
    expect(screen.queryByText(/Aún no hay datos del proyecto/)).not.toBeInTheDocument();
  });

  test("los metadatos se conservan al navegar a otra pantalla y volver", async () => {
    mockApi(
      inlineAnswer({ project_metadata: metadata }),
      (url) => (url.pathname === "/api/v1/estimations" ? json([]) : undefined),
    );
    renderApp();
    describe_(DESCRIPTION);
    await submit();
    await screen.findByRole("heading", { name: "Estimación" });

    await user().click(screen.getAllByRole("link", { name: "Historial" })[0]);
    await screen.findByText(/Todavía no hay estimaciones/);
    await user().click(screen.getAllByRole("link", { name: "Nueva estimación" })[0]);

    expect(await screen.findByRole("heading", { name: "Estimador de proyectos" })).toBeInTheDocument();
    expect(document.getElementById("metadata-name")).toHaveTextContent("Orion");
  });

  test("«Nueva conversación» crea otra sesión y reinicia formulario y metadatos", async () => {
    const api = mockApi(inlineAnswer({ project_metadata: metadata }));
    renderApp();
    describe_(DESCRIPTION);
    await submit();
    await screen.findByRole("heading", { name: "Estimación" });
    expect(document.getElementById("metadata-name")).toHaveTextContent("Orion");

    await user().click(screen.getByRole("button", { name: "Nueva conversación" }));

    await waitFor(() => expect(api.sessions).toHaveLength(2));
    expect(await screen.findByLabelText("Descripción del proyecto o transcripción")).toHaveValue("");
    expect(screen.getByText(/Aún no hay datos del proyecto/)).toBeInTheDocument();
    describe_(DESCRIPTION);
    await submit();
    await waitFor(() => expect(api.estimateCalls()).toHaveLength(2));
    expect(api.estimateCalls()[1].url.pathname).toBe(`/api/v1/sessions/${api.sessions[1]}/estimate`);
  });

  test("permite seleccionar varios adjuntos y los envía como attachments, con un mensaje corto", async () => {
    const api = mockApi(inlineAnswer());
    renderApp();
    const files = [
      new File(["%PDF-1.4"], "requisitos.pdf", { type: "application/pdf" }),
      new File(["PK"], "alcance.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }),
    ];

    await user().upload(screen.getByLabelText("Adjuntos (PDF o Word)"), files);
    expect(document.getElementById("attachment-names")).toHaveTextContent("requisitos.pdf, alcance.docx");
    describe_("Revisa los adjuntos");
    await submit();

    await screen.findByRole("heading", { name: "Estimación" });
    const body = api.estimateCalls()[0].init.body as FormData;
    expect(body.getAll("attachments").map((file) => (file as File).name)).toEqual(["requisitos.pdf", "alcance.docx"]);
    expect(body.get("transcript")).toBe("Revisa los adjuntos");
  });

  test.each([
    ["no es PDF ni Word", () => new File(["hola"], "notas.txt"), "Los adjuntos deben ser PDF (.pdf) o Word (.docx)."],
    ["pesa más de 10 MB", () => new File(["a".repeat(10 * 1024 * 1024 + 1)], "grande.pdf"), "Cada adjunto puede pesar como máximo 10 MB."],
  ])("un adjunto que %s se rechaza sin llamar a la API", async (_name, makeFile, message) => {
    const api = mockApi(inlineAnswer());
    renderApp();
    describe_(DESCRIPTION);

    await user().upload(screen.getByLabelText("Adjuntos (PDF o Word)"), makeFile());
    await submit();

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(api.estimateCalls()).toHaveLength(0);
  });

  test("si la API perdió la sesión abre otra, avisa y conserva lo escrito", async () => {
    let first = true;
    const api = mockApi((url, init) => {
      if (!isSessionEstimate(url, init)) return undefined;
      if (first) {
        first = false;
        return json({ detail: "Session not found or expired" }, 404);
      }
      return json(sessionBody({ estimation_id: null }));
    });
    renderApp();
    describe_(DESCRIPTION);
    await user().selectOptions(screen.getByLabelText("Nivel de detalle"), "detailed");

    await submit();

    expect(await screen.findByText(/La conversación anterior expiró/)).toBeInTheDocument();
    await waitFor(() => expect(api.sessions).toHaveLength(2));
    expect(screen.getByLabelText("Descripción del proyecto o transcripción")).toHaveValue(DESCRIPTION);
    expect(screen.getByLabelText("Nivel de detalle")).toHaveValue("detailed");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await submit();

    await screen.findByRole("heading", { name: "Estimación" });
    expect(api.estimateCalls()[1].url.pathname).toBe(`/api/v1/sessions/${api.sessions[1]}/estimate`);
    expect(screen.queryByText(/La conversación anterior expiró/)).not.toBeInTheDocument();
  });

  test("si la creación de la sesión falló al cargar, el envío la reintenta", async () => {
    let attempts = 0;
    const api = mockApi(
      (url, init) => {
        if (url.pathname === "/api/v1/sessions" && init.method === "POST" && ++attempts === 1) return json({}, 500);
        return undefined;
      },
      inlineAnswer(),
    );
    renderApp();
    await waitFor(() => expect(attempts).toBe(1));
    describe_(DESCRIPTION);

    await submit();

    await screen.findByRole("heading", { name: "Estimación" });
    expect(attempts).toBe(2);
    expect(api.estimateCalls()).toHaveLength(1);
  });

  test("un rechazo de adjunto del servidor muestra su mensaje en español", async () => {
    mockApi((url, init) =>
      isSessionEstimate(url, init)
        ? json({ detail: "No se pudo extraer texto de «escaneado.pdf» (¿está escaneado o vacío?)." }, 422)
        : undefined,
    );
    renderApp();
    describe_(DESCRIPTION);

    await submit();

    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo extraer texto de «escaneado.pdf»");
  });
});
