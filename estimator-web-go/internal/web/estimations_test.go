package web

import (
	"estimator-web/internal/config"
	"net/url"
	"strings"
	"testing"
	"time"
)

const description = "Portal de clientes para consultar facturas y abrir incidencias de soporte."

const estimatePath = "/api/v1/sessions/" + sessionID + "/estimate"

func formValues(overrides map[string]string) url.Values {
	values := url.Values{
		"estimation_form[description]":    {description},
		"estimation_form[project_type]":   {"web_saas"},
		"estimation_form[detail_level]":   {"medium"},
		"estimation_form[output_format]":  {"phases_table"},
		"estimation_form[prompt_version]": {"v3"},
	}
	for key, value := range overrides {
		values.Set("estimation_form["+key+"]", value)
	}
	return values
}

func stubEstimate(h *harness, body any, status int) {
	h.api.stubJSON("POST", estimatePath, status, body)
}

// --- Formulario ---

func TestTheFormShowsTheFieldsTheUploadTheLoadingIndicatorAndTheTimer(t *testing.T) {
	h := newHarness(t)
	p := h.get("/estimations/new")

	h.wantStatus(p, 200)
	h.wantContains(p,
		`maxlength="80000"`, `id="description"`, `id="upload"`, `accept=".txt,text/plain"`,
		`name="estimation_form[project_type]"`, `<option value="v3" selected="selected">v3</option>`,
		`<div id="loading" role="status" aria-live="polite">`, `class="spinner"`, `id="timer"`,
		`id="estimation-form" enctype="multipart/form-data"`, "80.000 caracteres",
		`name="authenticity_token"`, `<meta name="csrf-token"`,
	)
	if got := p.count(`<option value="(mobile_app|web_saas|internal_tool|data_pipeline)"`); got != 4 {
		t.Errorf("el selector de tipo de proyecto debe tener 4 opciones, tiene %d", got)
	}
	h.wantContains(p, `<label for="attachments">Adjuntos (PDF o Word)</label>`, `multiple="multiple"`, `accept=".pdf,.docx,`)
}

func TestAValidSubmissionCallsTheAPIAndRedirectsToTheSavedEstimation(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, estimateBody(estimateOptions{id: 7}), 200)

	p := h.postMultipart("/estimations", formValues(nil), nil)

	h.wantStatus(p, 302)
	if p.location != "/estimations/7" {
		t.Errorf("redirección: %q", p.location)
	}
	calls := h.api.requests("POST", estimatePath)
	if len(calls) != 1 {
		t.Fatalf("la API debe recibir una estimación, recibió %d", len(calls))
	}
	fields, files := multipartFields(t, calls[0])
	if fields["transcript"] != description || fields["project_type"] != "web_saas" || fields["detail_level"] != "medium" ||
		fields["output_format"] != "phases_table" || fields["prompt_version"] != "v3" || len(files) != 0 {
		t.Errorf("campos enviados: %v", fields)
	}
}

func TestWithoutEstimationIDTheResultIsRenderedDirectly(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, estimateBody(estimateOptions{}), 200)

	p := h.post("/estimations", formValues(nil))

	h.wantStatus(p, 200)
	if text, _ := p.textOf("cost"); text != "20.000,00 EUR" {
		t.Errorf("coste: %q", text)
	}
	if got := p.count(`<tr>\s*<td>(Diseño|Desarrollo)</td>`); got != 2 {
		t.Errorf("filas de fases: %d", got)
	}
	h.wantContains(p, description, `id="metric-model"`)
}

func TestATxtFileReplacesTheTypedDescription(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, estimateBody(estimateOptions{id: 7}), 200)
	transcript := "Reunión de kickoff: el cliente quiere un portal de facturación con alta de incidencias."

	p := h.postMultipart("/estimations", formValues(map[string]string{"description": "texto que se ignora"}),
		[]upload{{field: "estimation_form[upload]", filename: "reunion.txt", contentType: "text/plain", content: transcript}})

	h.wantStatus(p, 302)
	fields, _ := multipartFields(t, h.api.requests("POST", estimatePath)[0])
	if fields["transcript"] != transcript {
		t.Errorf("transcripción enviada: %q", fields["transcript"])
	}
}

func TestAnEightyThousandCharacterTranscriptionIsAccepted(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, estimateBody(estimateOptions{id: 7}), 200)
	text := strings.Repeat("Planificación del portal de clientes. ", 3000)[:80_000]

	p := h.post("/estimations", formValues(map[string]string{"description": text}))

	h.wantStatus(p, 302)
}

// --- Rechazos antes de llamar a la API ---

func TestShortAndOverlongDescriptionsAreRejectedWithoutCallingTheAPI(t *testing.T) {
	for _, text := range []string{"corta", strings.Repeat("x", 80_001)} {
		h := newHarness(t)
		p := h.post("/estimations", formValues(map[string]string{"description": text}))

		h.wantStatus(p, 422)
		if message, _ := p.textOf("form-errors"); !strings.Contains(message, "entre 20 y 80000 caracteres") {
			t.Errorf("mensaje: %q", message)
		}
		if h.api.count("POST", estimatePath) != 0 {
			t.Error("no debe llamarse a la API")
		}
	}
}

func TestInvalidFilesAreRejectedWithoutCallingTheAPI(t *testing.T) {
	cases := []struct {
		file    upload
		message string
	}{
		{upload{"estimation_form[upload]", "doc.pdf", "application/pdf", strings.Repeat("a", 100)}, "texto plano (.txt)"},
		{upload{"estimation_form[upload]", "r.txt", "text/plain", strings.Repeat("Reuni\xf3n", 20)}, "UTF-8"},
		{upload{"estimation_form[upload]", "r.txt", "text/plain", strings.Repeat("a", 400_001)}, "400 KB"},
	}
	for _, tc := range cases {
		h := newHarness(t)
		p := h.postMultipart("/estimations", formValues(nil), []upload{tc.file})

		h.wantStatus(p, 422)
		if message, _ := p.textOf("form-errors"); !strings.Contains(message, tc.message) {
			t.Errorf("se esperaba %q en %q", tc.message, message)
		}
		if h.api.count("POST", estimatePath) != 0 {
			t.Error("no debe llamarse a la API")
		}
	}
}

func TestTheFormKeepsTheTypedValuesAfterAValidationError(t *testing.T) {
	h := newHarness(t)
	p := h.post("/estimations", formValues(map[string]string{"description": "corta", "project_type": "data_pipeline"}))

	h.wantContains(p, "corta</textarea>", `<option value="data_pipeline" selected="selected">`)
	h.wantAbsent(p, `<option value="web_saas" selected`)
}

// --- Errores de la API ---

func TestAGuardrailRejectionShowsTheAPIMessage(t *testing.T) {
	h := newHarness(t)
	message := "La descripción contiene un número de teléfono. Elimínalo."
	stubEstimate(h, map[string]any{"reason": "pii_phone", "message": message}, 400)

	p := h.post("/estimations", formValues(nil))

	h.wantStatus(p, 422)
	if text, _ := p.textOf("form-errors"); !strings.Contains(text, message) {
		t.Errorf("errores: %q", text)
	}
}

func TestAnUnreachableAPIShowsASanitizedMessageAndKeepsTheForm(t *testing.T) {
	h := newHarness(t)
	h.api.stubReply("POST", estimatePath, reply{drop: true})

	p := h.post("/estimations", formValues(nil))

	h.wantStatus(p, 422)
	if text, _ := p.textOf("form-errors"); !strings.Contains(text, "No se pudo conectar con la API del estimador") {
		t.Errorf("errores: %q", text)
	}
	h.wantAbsent(p, h.api.server.URL, "EOF", "127.0.0.1")
	h.wantContains(p, description+"</textarea>")
}

func TestAServerErrorNeverShowsTheRawAPIBody(t *testing.T) {
	h := newHarness(t)
	h.api.stubReply("POST", estimatePath, reply{status: 502, body: "Traceback (most recent call last): openai key sk-secret"})

	p := h.post("/estimations", formValues(nil))

	h.wantStatus(p, 422)
	if text, _ := p.textOf("form-errors"); !strings.Contains(text, "no pudo completar la solicitud") {
		t.Errorf("errores: %q", text)
	}
	h.wantAbsent(p, "sk-secret", "Traceback")
}

func TestAnInvalidAPIResponseShowsAGenericError(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, map[string]any{"unexpected": true}, 200)

	p := h.post("/estimations", formValues(nil))

	if text, _ := p.textOf("form-errors"); !strings.Contains(text, "respuesta inválida") {
		t.Errorf("errores: %q", text)
	}
}

// --- Resultado ---

func TestTheResultViewShowsDurationCostConfidenceAndThePhasesTable(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations/7", 200, detailBody(detailOptions{source: "semantic"}))

	p := h.get("/estimations/7")

	h.wantStatus(p, 200)
	for id, want := range map[string]string{"confidence": "70%", "duration": "10 semanas", "cost": "20.000,00 EUR"} {
		if text, _ := p.textOf(id); text != want {
			t.Errorf("#%s = %q, se esperaba %q", id, text, want)
		}
	}
	meta, _ := p.textOf("estimation-meta")
	for _, part := range []string{"Caché semántica", "prompt v3", "SaaS web · detalle medio · tabla de fases", "05/10/2026 10:30 UTC"} {
		if !strings.Contains(meta, part) {
			t.Errorf("la meta %q no contiene %q", meta, part)
		}
	}
	h.wantContains(p, "<th>Fase</th>", "<td>Diseño</td>", `<td class="num">16.000,00 EUR</td>`, `<td class="num">2</td>`, "<h1>Estimación #7</h1>")
	h.wantAbsent(p, `id="out-of-scope"`)
}

func TestALowConfidenceResultIsShownAsNotEstimableWithoutFigures(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations/8", 200, detailBody(detailOptions{id: 8, result: outOfScope}))

	p := h.get("/estimations/8")

	text, _ := p.textOf("out-of-scope")
	if !strings.Contains(text, "No estimable") || !strings.Contains(text, "la reunión no define el alcance") {
		t.Errorf("fuera de alcance: %q", text)
	}
	h.wantAbsent(p, `id="cost"`, `id="duration"`, `id="phases"`, "EUR")
}

func TestAVeryLongDescriptionIsTruncatedInTheResultView(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations/9", 200, detailBody(detailOptions{id: 9, description: strings.Repeat("palabra ", 10_000)}))

	p := h.get("/estimations/9")

	if len(p.body) > 25_000 {
		t.Errorf("la página ocupa %d bytes", len(p.body))
	}
	h.wantContains(p, "caracteres en total", "80.000 caracteres en total", "...")
}

func TestAnUnknownEstimationRendersA404Page(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations/404", 404, map[string]any{"detail": "Estimation not found"})

	p := h.get("/estimations/404")

	h.wantStatus(p, 404)
	if text, _ := p.textOf("api-error"); !strings.Contains(text, "No se encontró la estimación") {
		t.Errorf("error: %q", text)
	}
	h.wantAbsent(p, `id="sidebar"`)
}

func TestANonNumericEstimationIDIsA404WithoutCallingTheAPI(t *testing.T) {
	h := newHarness(t)

	p := h.get("/estimations/abc")

	h.wantStatus(p, 404)
	h.wantContains(p, `id="api-error"`)
}

func TestAnUnreachableAPIOnTheResultPageIsASanitizedBadGateway(t *testing.T) {
	h := newHarness(t, withConfig(func(c *config.Config) { c.ReadTimeout = 50 * time.Millisecond }))
	h.api.stubReply("GET", "/api/v1/estimations/7", reply{status: 200, body: "{}", delay: 300 * time.Millisecond})

	p := h.get("/estimations/7")

	h.wantStatus(p, 502)
	if text, _ := p.textOf("api-error"); !strings.Contains(text, "No se pudo conectar") {
		t.Errorf("error: %q", text)
	}
}

// --- Historial ---

func TestTheHistoryListsTheLatestEstimationsLinkingToEachOne(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations", 200, []any{summaryItem(3, result, "exact"), summaryItem(2, outOfScope, "none")})

	p := h.get("/estimations")

	h.wantStatus(p, 200)
	if got := h.api.requests("GET", "/api/v1/estimations")[0].rawQuery; got != "limit=10" {
		t.Errorf("consulta: %q", got)
	}
	if got := p.count(`<a href="/estimations/\d+">`); got != 2 {
		t.Errorf("enlaces: %d", got)
	}
	h.wantContains(p, `<a href="/estimations/3">05/10/2026 10:30 UTC</a>`, "Caché exacta", "20.000,00 EUR", "No estimable", `<td class="num">70%</td>`)
}

func TestAnEmptyHistoryShowsAnExplanatoryMessage(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations", 200, []any{})

	p := h.get("/estimations")

	h.wantStatus(p, 200)
	h.wantContains(p, `id="history-empty"`)
}

func TestADisabledHistoryShowsAFriendlyMessageInsteadOfATechnicalError(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations", 503, map[string]any{"detail": "History is not configured"})

	p := h.get("/estimations")

	h.wantStatus(p, 200)
	if text, _ := p.textOf("history-error"); !strings.Contains(text, "historial no está disponible") {
		t.Errorf("error: %q", text)
	}
	h.wantAbsent(p, "not configured")
}

func TestAnUnreachableAPIOnTheHistoryPageShowsTheConnectionMessage(t *testing.T) {
	h := newHarness(t)
	h.api.stubReply("GET", "/api/v1/estimations", reply{drop: true})

	p := h.get("/estimations")

	h.wantStatus(p, 200)
	if text, _ := p.textOf("history-error"); !strings.Contains(text, "No se pudo conectar") {
		t.Errorf("error: %q", text)
	}
}

// --- Barra lateral (equivalente a la de Streamlit) ---

func TestTheFormPageHasTheLeftSidebarWithTheSystemPromptAndFewShotExamples(t *testing.T) {
	h := newHarness(t)
	p := h.get("/estimations/new")

	h.wantContains(p, `<aside id="sidebar">`, "<h2>Contexto del prompt</h2>", `<textarea id="system-prompt" readonly rows="14">`,
		"arquitecto sénior de estimación", "Portal de reservas para un gimnasio", "Plataforma de IA para todo el hospital",
		`id="no-metrics"`, `<button type="button" id="sidebar-toggle"`)
	if got := p.count(`<p class="example">`); got != 2 {
		t.Errorf("ejemplos few-shot: %d", got)
	}
	query := h.api.requests("GET", "/api/v1/prompts/estimation")[0].rawQuery
	if query != "detail_level=medium&output_format=phases_table&project_type=mobile_app&prompt_version=v3" {
		t.Errorf("consulta del prompt: %s", query)
	}
}

func TestTheResultPageShowsTheLastCallMetricsInTheSidebar(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations/7", 200, detailBody(detailOptions{}))

	p := h.get("/estimations/7")

	for id, want := range map[string]string{
		"metric-model": "gpt-4o-mini", "metric-prompt-version": "v3", "metric-input-tokens": "12.400", "metric-output-tokens": "860",
		"metric-latency": "8.450", "metric-cost": "0,000412 USD", "metric-cache": "Respuesta generada",
	} {
		if text, _ := p.textOf(id); text != want {
			t.Errorf("#%s = %q, se esperaba %q", id, text, want)
		}
	}
	h.wantAbsent(p, `id="no-metrics"`)
}

func TestTheSidebarPromptFollowsTheOptionsOfTheViewedEstimation(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations/7", 200, detailBody(detailOptions{}))

	h.get("/estimations/7")

	query := h.api.requests("GET", "/api/v1/prompts/estimation")[0].rawQuery
	if query != "detail_level=medium&output_format=phases_table&project_type=web_saas&prompt_version=v3" {
		t.Errorf("consulta del prompt: %s", query)
	}
}

func TestCacheHitsAndUnknownPricesAreLabelled(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations/7", 200, detailBody(detailOptions{source: "exact", metrics: metricsBody(true, nil)}))

	p := h.get("/estimations/7")

	if text, _ := p.textOf("metric-cache"); text != "Respuesta de caché" {
		t.Errorf("caché: %q", text)
	}
	if text, _ := p.textOf("metric-cost"); text != "Sin tarifa" {
		t.Errorf("coste: %q", text)
	}
}

func TestAnOldRecordWithoutMetricsShowsTheEmptyState(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations/7", 200, detailBody(detailOptions{metrics: "none"}))

	p := h.get("/estimations/7")

	h.wantStatus(p, 200)
	h.wantContains(p, `id="no-metrics"`)
	h.wantAbsent(p, `id="last-call"`)
}

func TestTheSidebarSurvivesAValidationErrorAndTheHistoryPageHasItToo(t *testing.T) {
	h := newHarness(t)
	p := h.post("/estimations", formValues(map[string]string{"description": "corta"}))
	h.wantStatus(p, 422)
	h.wantContains(p, `<aside id="sidebar">`, `id="system-prompt"`)

	h.api.stubJSON("GET", "/api/v1/estimations", 200, []any{})
	p = h.get("/estimations")
	h.wantContains(p, `<aside id="sidebar">`)
	if got := p.count(`<p class="example">`); got != 2 {
		t.Errorf("ejemplos: %d", got)
	}
}

func TestIfThePromptCannotBeRenderedThePageStillWorksWithANotice(t *testing.T) {
	h := newHarness(t)
	h.api.stubReply("GET", "/api/v1/prompts/estimation", reply{status: 500, body: "boom"})

	p := h.get("/estimations/new")

	h.wantStatus(p, 200)
	h.wantContains(p, `id="prompt-unavailable"`, `id="estimation-form"`)
	h.wantAbsent(p, "boom")
}

func TestTheErrorPageHasNoSidebar(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations/404", 404, map[string]any{"detail": "x"})

	h.wantAbsent(h.get("/estimations/404"), `<aside id="sidebar">`)
}

func TestTheResultRenderedWithoutHistoryAlsoShowsTheMetrics(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, estimateBody(estimateOptions{}), 200)

	p := h.post("/estimations", formValues(nil))

	if text, _ := p.textOf("metric-model"); text != "gpt-4o-mini" {
		t.Errorf("modelo: %q", text)
	}
}
