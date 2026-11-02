package web

import (
	"strings"
	"testing"

	"estimator-web/internal/session"
)

const secondID = "0b1d9f3a-3c55-4d3e-8d2a-5a8d8c6b7e21"

func sessionsCreated(h *harness) int { return h.api.count("POST", "/api/v1/sessions") }

// --- Sesión al cargar la página ---

func TestOpeningThePageCreatesASessionOnceAndKeepsItAcrossPageLoads(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations", 200, []any{})

	h.get("/estimations/new")
	h.get("/estimations/new")
	p := h.get("/estimations")

	h.wantStatus(p, 200)
	if got := sessionsCreated(h); got != 1 {
		t.Errorf("sesiones creadas: %d", got)
	}
}

func TestTheEstimateIsSentToTheSessionCreatedOnLoad(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, estimateBody(estimateOptions{id: 7}), 200)
	h.get("/estimations/new")

	p := h.post("/estimations", formValues(nil))

	h.wantStatus(p, 302)
	if h.api.count("POST", estimatePath) != 1 || sessionsCreated(h) != 1 {
		t.Errorf("estimaciones %d, sesiones %d", h.api.count("POST", estimatePath), sessionsCreated(h))
	}
}

func TestIfTheAPICouldNotCreateTheSessionOnLoadSubmittingRetriesIt(t *testing.T) {
	h := newHarness(t)
	calls := 0
	h.api.stub("POST", "/api/v1/sessions", func(apiCall) reply {
		calls++
		if calls == 1 {
			return reply{status: 500}
		}
		return jsonReply(map[string]any{"session_id": sessionID}, 201)
	})
	stubEstimate(h, estimateBody(estimateOptions{id: 7}), 200)

	p := h.get("/estimations/new")
	h.wantStatus(p, 200)
	h.wantContains(p, `id="estimation-form"`)

	p = h.post("/estimations", formValues(nil))

	h.wantStatus(p, 302)
	if sessionsCreated(h) != 2 {
		t.Errorf("sesiones creadas: %d", sessionsCreated(h))
	}
}

// --- Adjuntos ---

func TestSeveralAttachmentsAreSentToTheAPIAsMultipartFiles(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, estimateBody(estimateOptions{id: 7}), 200)

	p := h.postMultipart("/estimations", formValues(nil), []upload{
		{field: "estimation_form[attachments][]", filename: "requisitos.pdf", contentType: "application/pdf", content: "%PDF-uno"},
		{field: "estimation_form[attachments][]", filename: "alcance.docx", contentType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", content: "PK-dos"},
	})

	h.wantStatus(p, 302)
	_, files := multipartFields(t, h.api.requests("POST", estimatePath)[0])
	if len(files) != 2 || files[0].Filename != "requisitos.pdf" || files[1].Filename != "alcance.docx" {
		t.Fatalf("adjuntos enviados: %v", files)
	}
	opened, _ := files[1].Open()
	buffer := make([]byte, 16)
	read, _ := opened.Read(buffer)
	if string(buffer[:read]) != "PK-dos" {
		t.Errorf("contenido: %q", buffer[:read])
	}
}

func TestAShortMessageIsAcceptedWhenThereAreAttachments(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, estimateBody(estimateOptions{id: 7}), 200)

	p := h.postMultipart("/estimations", formValues(map[string]string{"description": "Revisa"}),
		[]upload{{field: "estimation_form[attachments][]", filename: "req.pdf", content: "x"}})

	h.wantStatus(p, 302)
}

func TestAnEmptyAttachmentsValueNoFileChosenIsIgnored(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, estimateBody(estimateOptions{id: 7}), 200)
	values := formValues(nil)
	values.Set("estimation_form[attachments][]", "")

	p := h.postMultipart("/estimations", values, []upload{{field: "estimation_form[attachments][]", filename: "", content: ""}})

	h.wantStatus(p, 302)
}

func TestInvalidAttachmentsAreRejectedWithoutCallingTheAPI(t *testing.T) {
	big := strings.Repeat("x", 10*1024*1024+1)
	var sixFiles []upload
	for _, name := range []string{"0.pdf", "1.pdf", "2.pdf", "3.pdf", "4.pdf", "5.pdf"} {
		sixFiles = append(sixFiles, upload{field: "estimation_form[attachments][]", filename: name, content: "x"})
	}
	cases := []struct {
		files   []upload
		message string
	}{
		{[]upload{{field: "estimation_form[attachments][]", filename: "notas.txt", content: "x"}}, "Los adjuntos deben ser PDF (.pdf) o Word (.docx)."},
		{[]upload{{field: "estimation_form[attachments][]", filename: "grande.pdf", content: big}}, "Cada adjunto puede pesar como máximo 10 MB."},
		{sixFiles, "Se admiten como máximo 5 adjuntos."},
	}
	for _, tc := range cases {
		h := newHarness(t)
		p := h.postMultipart("/estimations", formValues(nil), tc.files)

		h.wantStatus(p, 422)
		if text, _ := p.textOf("form-errors"); !strings.Contains(text, tc.message) {
			t.Errorf("se esperaba %q en %q", tc.message, text)
		}
		if h.api.count("POST", estimatePath) != 0 {
			t.Error("no debe llamarse a la API")
		}
	}
}

func TestAnAttachmentRejectedByTheAPIShowsItsMessageAndKeepsTheForm(t *testing.T) {
	h := newHarness(t)
	message := "No se pudo extraer texto de «escaneado.pdf» (¿está escaneado o vacío?)."
	stubEstimate(h, map[string]any{"detail": message}, 422)

	p := h.postMultipart("/estimations", formValues(nil), []upload{{field: "estimation_form[attachments][]", filename: "escaneado.pdf", content: "x"}})

	h.wantStatus(p, 422)
	if text, _ := p.textOf("form-errors"); !strings.Contains(text, message) {
		t.Errorf("errores: %q", text)
	}
	h.wantContains(p, description+"</textarea>")
}

// --- Metadatos del proyecto ---

func TestTheSidebarStartsWithAnEmptyMetadataPanelAndTheNewConversationButton(t *testing.T) {
	h := newHarness(t)
	p := h.get("/estimations/new")

	h.wantContains(p, "<h2>Metadatos del proyecto</h2>", `id="no-project-metadata"`, "Aún no hay datos del proyecto",
		`action="/conversation"`, `<button id="new-conversation" type="submit">Nueva conversación</button>`)
}

func TestTheMetadataReturnedByTheAPIIsShownOnTheResultPageAndOnLaterPages(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, estimateBody(estimateOptions{id: 7, metadata: projectMetadata}), 200)
	h.api.stubJSON("GET", "/api/v1/estimations/7", 200, detailBody(detailOptions{}))

	p := h.post("/estimations", formValues(nil))
	h.wantStatus(p, 302)
	p = h.get(p.location)

	for id, want := range map[string]string{
		"metadata-name": "Orion", "metadata-team": "4", "metadata-technologies": "FastAPI, Kafka", "metadata-scope": "Portal y panel de administración",
	} {
		if text, _ := p.textOf(id); text != want {
			t.Errorf("#%s = %q, se esperaba %q", id, text, want)
		}
	}
	h.wantAbsent(p, `id="no-project-metadata"`)

	p = h.get("/estimations/new")
	if text, _ := p.textOf("metadata-name"); text != "Orion" {
		t.Errorf("nombre en la página siguiente: %q", text)
	}
}

func TestMetadataAreShownWhenTheResultIsRenderedWithoutHistory(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, estimateBody(estimateOptions{metadata: projectMetadata}), 200)

	p := h.post("/estimations", formValues(nil))

	h.wantStatus(p, 200)
	if text, _ := p.textOf("metadata-technologies"); text != "FastAPI, Kafka" {
		t.Errorf("tecnologías: %q", text)
	}
}

func TestVeryLargeMetadataDoNotOverflowTheCookieSession(t *testing.T) {
	h := newHarness(t)
	technologies := make([]any, 30)
	for index := range technologies {
		technologies[index] = "tecnología-" + strings.Repeat("t", 40)
	}
	huge := map[string]any{
		"project_name": strings.Repeat("n", 120), "assumed_team_size": 1000, "mentioned_technologies": technologies,
		"agreed_scope": strings.Repeat("ñ", 1000),
	}
	stubEstimate(h, estimateBody(estimateOptions{id: 7, metadata: huge}), 200)

	h.post("/estimations", formValues(nil))
	p := h.get("/estimations/new")

	h.wantStatus(p, 200)
	if scope, _ := p.textOf("metadata-scope"); len([]rune(scope)) > 300 {
		t.Errorf("el alcance guardado debe acotarse a 300 caracteres, tiene %d", len([]rune(scope)))
	}
	for _, cookie := range h.client.Jar.Cookies(mustURL(h.app.URL)) {
		if cookie.Name == session.CookieName && len(cookie.Value) > 4000 {
			t.Errorf("la cookie ocupa %d bytes", len(cookie.Value))
		}
	}
}

// --- Nueva conversación ---

func TestNewConversationOpensAnotherSessionAndClearsTheMetadata(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, estimateBody(estimateOptions{metadata: projectMetadata}), 200)
	p := h.post("/estimations", formValues(nil))
	if text, _ := p.textOf("metadata-name"); text != "Orion" {
		t.Fatalf("nombre: %q", text)
	}
	h.api.stubJSON("POST", "/api/v1/sessions", 201, map[string]any{"session_id": secondID})

	p = h.post("/conversation", nil)

	h.wantStatus(p, 302)
	if p.location != "/estimations/new" {
		t.Errorf("redirección: %q", p.location)
	}
	p = h.get(p.location)
	h.wantContains(p, `id="no-project-metadata"`)
	h.wantAbsent(p, `id="metadata-name"`)
	if sessionsCreated(h) != 2 {
		t.Errorf("sesiones creadas: %d", sessionsCreated(h))
	}

	h.api.stubJSON("POST", "/api/v1/sessions/"+secondID+"/estimate", 200, estimateBody(estimateOptions{}))
	h.post("/estimations", formValues(nil))
	if h.api.count("POST", "/api/v1/sessions/"+secondID+"/estimate") != 1 {
		t.Error("la estimación debe ir a la sesión nueva")
	}
}

func TestNewConversationWorksEvenIfTheAPICannotOpenTheSessionRightNow(t *testing.T) {
	h := newHarness(t)
	h.get("/estimations/new")
	h.api.stubReply("POST", "/api/v1/sessions", reply{status: 503})

	p := h.post("/conversation", nil)

	h.wantStatus(p, 302)
	p = h.get(p.location)
	h.wantStatus(p, 200)
	h.wantContains(p, `id="no-project-metadata"`)
}

// --- Sesión caducada ---

func TestWhenTheAPILostTheSessionANewOneIsOpenedAndTheUserIsTold(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, map[string]any{"detail": "Session not found or expired"}, 404)
	h.get("/estimations/new")
	h.api.stubJSON("POST", "/api/v1/sessions", 201, map[string]any{"session_id": secondID})

	p := h.post("/estimations", formValues(map[string]string{"project_type": "data_pipeline"}))

	h.wantStatus(p, 200)
	if text, _ := p.textOf("conversation-notice"); !strings.Contains(text, "La conversación anterior expiró") {
		t.Errorf("aviso: %q", text)
	}
	h.wantAbsent(p, `id="form-errors"`)
	h.wantContains(p, description+"</textarea>", `<option value="data_pipeline" selected="selected">`, `id="no-project-metadata"`)
	if sessionsCreated(h) != 2 {
		t.Errorf("sesiones creadas: %d", sessionsCreated(h))
	}

	h.api.stubJSON("POST", "/api/v1/sessions/"+secondID+"/estimate", 200, estimateBody(estimateOptions{}))
	h.post("/estimations", formValues(nil))
	if h.api.count("POST", "/api/v1/sessions/"+secondID+"/estimate") != 1 {
		t.Error("el reenvío debe ir a la sesión nueva")
	}
}
