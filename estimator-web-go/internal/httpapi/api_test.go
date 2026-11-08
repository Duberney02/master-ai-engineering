package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"estimator-web/internal/config"
	"estimator-web/internal/rag"
)

// --- Cliente simulado del API ---

type harness struct {
	t      *testing.T
	api    *fakeAPI
	app    *httptest.Server
	server *Server
	cfg    config.Config
	store  rag.Store
}

type option func(*harness)

func withConfig(change func(*config.Config)) option { return func(h *harness) { change(&h.cfg) } }
func withStore(store rag.Store) option              { return func(h *harness) { h.store = store } }
func withoutStore() option                          { return func(h *harness) { h.store = nil } }

func newHarness(t *testing.T, opts ...option) *harness {
	t.Helper()
	api := newFakeAPI(t)
	api.stubJSON("POST", "/api/v1/sessions", 201, map[string]any{"session_id": sessionID})
	api.stubJSON("GET", "/api/v1/config/models", 200, configBody(nil))

	h := &harness{t: t, api: api, store: &memStore{}}
	h.cfg = config.Config{
		Port: "0", APIURL: api.server.URL, OpenTimeout: time.Second, ReadTimeout: 5 * time.Second,
		CompareTimeout: 10 * time.Second, BadgeTimeout: time.Second,
	}
	for _, opt := range opts {
		opt(h)
	}
	h.server = New(h.cfg, h.store, nil)
	h.app = httptest.NewServer(h.server.Handler())
	t.Cleanup(h.app.Close)
	return h
}

// response es una respuesta del servicio.
type response struct {
	status int
	body   []byte
	header http.Header
}

func (r response) text() string { return string(r.body) }

// json decodifica el cuerpo como un objeto.
func (r response) object(t *testing.T) map[string]any {
	t.Helper()
	var decoded map[string]any
	if err := json.Unmarshal(r.body, &decoded); err != nil {
		t.Fatalf("cuerpo no es un objeto JSON: %v\n%s", err, r.body)
	}
	return decoded
}

func (r response) list(t *testing.T) []any {
	t.Helper()
	var decoded []any
	if err := json.Unmarshal(r.body, &decoded); err != nil {
		t.Fatalf("cuerpo no es una lista JSON: %v\n%s", err, r.body)
	}
	return decoded
}

func (h *harness) do(method, path, contentType string, body io.Reader) response {
	h.t.Helper()
	request, err := http.NewRequest(method, h.app.URL+path, body)
	if err != nil {
		h.t.Fatal(err)
	}
	if contentType != "" {
		request.Header.Set("Content-Type", contentType)
	}
	reply, err := http.DefaultClient.Do(request)
	if err != nil {
		h.t.Fatal(err)
	}
	defer reply.Body.Close()
	data, _ := io.ReadAll(reply.Body)
	return response{status: reply.StatusCode, body: data, header: reply.Header}
}

func (h *harness) get(path string) response { return h.do("GET", path, "", nil) }

func (h *harness) sendJSON(method, path string, body any) response {
	h.t.Helper()
	encoded, err := json.Marshal(body)
	if err != nil {
		h.t.Fatal(err)
	}
	return h.do(method, path, "application/json", bytes.NewReader(encoded))
}

type upload struct{ field, filename, contentType, content string }

func (h *harness) postMultipart(path string, fields map[string]string, files []upload) response {
	h.t.Helper()
	var buffer bytes.Buffer
	writer := multipart.NewWriter(&buffer)
	for name, value := range fields {
		_ = writer.WriteField(name, value)
	}
	for _, file := range files {
		header := make(map[string][]string)
		header["Content-Disposition"] = []string{`form-data; name="` + file.field + `"; filename="` + file.filename + `"`}
		header["Content-Type"] = []string{file.contentType}
		part, _ := writer.CreatePart(header)
		_, _ = part.Write([]byte(file.content))
	}
	_ = writer.Close()
	return h.do("POST", path, writer.FormDataContentType(), &buffer)
}

func (h *harness) wantStatus(r response, status int) {
	h.t.Helper()
	if r.status != status {
		h.t.Fatalf("estado %d, se esperaba %d\n%s", r.status, status, r.body)
	}
}

func (h *harness) wantDetail(r response, status int, fragment string) {
	h.t.Helper()
	h.wantStatus(r, status)
	if got, _ := r.object(h.t)["detail"].(string); !strings.Contains(got, fragment) {
		h.t.Fatalf("detail %q no contiene %q", got, fragment)
	}
}

// --- Salud y rutas ---

func TestHealthDoesNotTouchTheAPIOrTheDatabase(t *testing.T) {
	h := newHarness(t, withoutStore())
	h.wantStatus(h.get("/up"), 200)
	if len(h.api.calls) != 0 {
		t.Errorf("/up no debe llamar a la API: %v", h.api.calls)
	}
}

func TestThereAreNoHTMLRoutes(t *testing.T) {
	h := newHarness(t)
	for _, path := range []string{"/", "/estimations", "/estimations/new", "/rag/chunking_comparisons", "/ai_settings", "/robots.txt", "/404.html"} {
		r := h.get(path)
		h.wantStatus(r, 404)
		if !strings.HasPrefix(r.header.Get("Content-Type"), "application/json") {
			t.Errorf("%s: Content-Type %q", path, r.header.Get("Content-Type"))
		}
	}
}

func TestUnknownResourcesAreJSON404(t *testing.T) {
	h := newHarness(t)
	h.wantDetail(h.get("/api/chunking-comparisons/0"), 404, "No se encontró")
	h.wantDetail(h.get("/api/nada"), 404, "no encontrado")
}

func TestAPIResponsesAreJSON(t *testing.T) {
	h := newHarness(t)
	for _, path := range []string{"/api/chunking-comparisons/options", "/api/ai-settings", "/api/primary-model"} {
		if got := h.get(path).header.Get("Content-Type"); !strings.HasPrefix(got, "application/json") {
			t.Errorf("%s: %q", path, got)
		}
	}
}

// --- Conversación y estimaciones ---

const estimatePath = "/api/v1/sessions/" + sessionID + "/estimate"

func formFields(overrides map[string]string) map[string]string {
	fields := map[string]string{
		"description":    "Portal de clientes con facturación, incidencias y panel de administración.",
		"project_type":   "web_saas",
		"detail_level":   "medium",
		"output_format":  "phases_table",
		"prompt_version": "v3",
	}
	for key, value := range overrides {
		fields[key] = value
	}
	return fields
}

func TestCreatingAConversationReturnsItsIDWithoutCookies(t *testing.T) {
	h := newHarness(t)
	r := h.do("POST", "/api/conversations", "", nil)

	h.wantStatus(r, 201)
	if got := r.object(t)["conversation_id"]; got != sessionID {
		t.Errorf("conversation_id: %v", got)
	}
	if r.header.Get("Set-Cookie") != "" {
		t.Error("el API no debe usar cookies")
	}
}

func TestConversationOpeningFailureIsSanitized(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("POST", "/api/v1/sessions", 500, map[string]any{"trace": "Traceback sk-secret http://interno:8000"})

	r := h.do("POST", "/api/conversations", "", nil)

	h.wantStatus(r, 502)
	for _, leak := range []string{"Traceback", "sk-secret", "interno", ":8000"} {
		if strings.Contains(r.text(), leak) {
			t.Errorf("filtración %q: %s", leak, r.body)
		}
	}
}

func TestAValidEstimationIsForwardedAndReturnedWithMetadata(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("POST", estimatePath, 200, estimateBody(estimateOptions{id: 7, metadata: projectMetadata}))

	r := h.postMultipart("/api/conversations/"+sessionID+"/estimations", formFields(nil), nil)

	h.wantStatus(r, 200)
	body := r.object(t)
	if body["estimation_id"].(float64) != 7 {
		t.Errorf("estimation_id: %v", body["estimation_id"])
	}
	if body["project_metadata"].(map[string]any)["project_name"] != "Orion" {
		t.Errorf("project_metadata: %v", body["project_metadata"])
	}
	fields, files := multipartFields(t, h.api.requests("POST", estimatePath)[0])
	if fields["transcript"] != formFields(nil)["description"] || fields["prompt_version"] != "v3" || len(files) != 0 {
		t.Errorf("campos enviados a la API: %v (%d adjuntos)", fields, len(files))
	}
}

func TestAnEstimationWithoutHistoryOmitsTheID(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("POST", estimatePath, 200, estimateBody(estimateOptions{}))

	r := h.postMultipart("/api/conversations/"+sessionID+"/estimations", formFields(nil), nil)

	h.wantStatus(r, 200)
	if body := r.object(t); body["estimation_id"] != nil || body["result"] == nil {
		t.Errorf("respuesta: %v", body)
	}
}

func TestInvalidInputIsRejectedWithoutCallingTheAPI(t *testing.T) {
	cases := map[string]struct {
		fields  map[string]string
		files   []upload
		message string
	}{
		"descripción corta": {formFields(map[string]string{"description": "corta"}), nil, "La descripción debe tener entre 20 y 80000 caracteres."},
		"descripción larga": {formFields(map[string]string{"description": strings.Repeat("a", 80_001)}), nil, "La descripción debe tener entre 20 y 80000 caracteres."},
		"tipo inválido":     {formFields(map[string]string{"project_type": "otro"}), nil, "El tipo de proyecto no es válido."},
		"txt no es txt":     {formFields(nil), []upload{{"upload", "notas.md", "text/markdown", "contenido suficiente para pasar"}}, "El archivo debe ser de texto plano (.txt)."},
		"txt no utf8":       {formFields(nil), []upload{{"upload", "notas.txt", "text/plain", "\xff\xfe\xfa"}}, "El archivo debe estar codificado en UTF-8."},
		"adjunto inválido":  {formFields(nil), []upload{{"attachments", "foto.png", "image/png", "x"}}, "Los adjuntos deben ser PDF (.pdf) o Word (.docx)."},
		"demasiados": {formFields(nil), []upload{
			{"attachments", "a.pdf", "application/pdf", "x"}, {"attachments", "b.pdf", "application/pdf", "x"}, {"attachments", "c.pdf", "application/pdf", "x"},
			{"attachments", "d.pdf", "application/pdf", "x"}, {"attachments", "e.pdf", "application/pdf", "x"}, {"attachments", "f.pdf", "application/pdf", "x"},
		}, "Se admiten como máximo 5 adjuntos."},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t)
			h.wantDetail(h.postMultipart("/api/conversations/"+sessionID+"/estimations", c.fields, c.files), 422, c.message)
			if got := h.api.count("POST", estimatePath); got != 0 {
				t.Errorf("la API no debe recibir la solicitud (%d llamadas)", got)
			}
		})
	}
}

func TestATextUploadReplacesTheDescriptionAndAttachmentsAreForwarded(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("POST", estimatePath, 200, estimateBody(estimateOptions{id: 8}))

	r := h.postMultipart("/api/conversations/"+sessionID+"/estimations",
		formFields(map[string]string{"description": ""}),
		[]upload{
			{"upload", "reunion.txt", "text/plain", "Transcripción de la reunión con el cliente: portal web y panel."},
			{"attachments", "brief.pdf", "application/pdf", "%PDF-1.4"},
			{"attachments", "acta.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "PK"},
		})

	h.wantStatus(r, 200)
	fields, files := multipartFields(t, h.api.requests("POST", estimatePath)[0])
	if !strings.HasPrefix(fields["transcript"], "Transcripción de la reunión") || len(files) != 2 {
		t.Errorf("transcript=%q adjuntos=%d", fields["transcript"], len(files))
	}
}

func TestExpiredSessionIs404(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("POST", estimatePath, 404, map[string]any{"detail": "Sesión no encontrada"})

	h.wantDetail(h.postMultipart("/api/conversations/"+sessionID+"/estimations", formFields(nil), nil), 404, "expiró")
}

func TestEstimationFailuresMapToSanitizedStatuses(t *testing.T) {
	cases := map[string]struct {
		reply  reply
		status int
		detail string
	}{
		"guardrail":      {jsonReply(map[string]any{"reason": "injection", "message": "No puedo ayudar con eso."}, 400), 422, "No puedo ayudar con eso."},
		"adjunto grande": {jsonReply(map[string]any{"detail": "El adjunto supera el máximo."}, 413), 422, "El adjunto supera el máximo."},
		"5xx con traza":  {jsonReply(map[string]any{"trace": "Traceback sk-secret http://interno:8000"}, 500), 502, "no pudo completar"},
		"503":            {jsonReply(map[string]any{"detail": "x"}, 503), 503, "no pudo completar"},
		"caída":          {reply{drop: true}, 503, "No se pudo conectar"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t)
			h.api.stubReply("POST", estimatePath, c.reply)
			r := h.postMultipart("/api/conversations/"+sessionID+"/estimations", formFields(nil), nil)
			h.wantDetail(r, c.status, c.detail)
			for _, leak := range []string{"Traceback", "sk-secret", "interno", ":8000", h.api.server.URL} {
				if strings.Contains(r.text(), leak) {
					t.Errorf("filtración %q: %s", leak, r.body)
				}
			}
		})
	}
}

func TestHistoryListsAndShowsEstimations(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations", 200, []any{summaryItem(7, result, "none"), summaryItem(6, outOfScope, "exact")})
	h.api.stubJSON("GET", "/api/v1/estimations/7", 200, detailBody(detailOptions{id: 7}))

	list := h.get("/api/estimations")
	h.wantStatus(list, 200)
	if got := len(list.list(t)); got != 2 {
		t.Errorf("elementos: %d", got)
	}
	if query := h.api.requests("GET", "/api/v1/estimations")[0].rawQuery; query != "limit=10" {
		t.Errorf("límite por defecto: %q", query)
	}

	detail := h.get("/api/estimations/7")
	h.wantStatus(detail, 200)
	if detail.object(t)["result"] == nil {
		t.Errorf("detalle sin resultado: %s", detail.body)
	}
}

func TestHistoryLimitIsValidatedAndCapped(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations", 200, []any{})
	h.wantStatus(h.get("/api/estimations?limit=abc"), 422)
	h.wantStatus(h.get("/api/estimations?limit=0"), 422)
	h.wantStatus(h.get("/api/estimations?limit=999"), 200)
	if query := h.api.requests("GET", "/api/v1/estimations")[0].rawQuery; query != "limit=50" {
		t.Errorf("límite acotado: %q", query)
	}
}

func TestHistoryErrors(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations", 503, map[string]any{"detail": "x"})
	h.api.stubJSON("GET", "/api/v1/estimations/9", 404, map[string]any{"detail": "x"})

	h.wantDetail(h.get("/api/estimations"), 503, "El historial no está disponible")
	h.wantDetail(h.get("/api/estimations/9"), 404, "No se encontró la estimación")
	h.wantDetail(h.get("/api/estimations/abc"), 404, "No se encontró la estimación")
	if got := h.api.count("GET", "/api/v1/estimations/9"); got != 1 {
		t.Errorf("llamadas: %d", got)
	}
}

func TestPromptPreviewIsProxied(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/prompts/estimation", 200, promptBody())

	r := h.get("/api/prompt-preview?prompt_version=v3&project_type=web_saas&detail_level=medium&output_format=phases_table")

	h.wantStatus(r, 200)
	if r.object(t)["system_prompt"] != systemPrompt {
		t.Errorf("prompt: %s", r.body)
	}
	query := h.api.requests("GET", "/api/v1/prompts/estimation")[0].rawQuery
	for _, want := range []string{"prompt_version=v3", "project_type=web_saas", "detail_level=medium", "output_format=phases_table"} {
		if !strings.Contains(query, want) {
			t.Errorf("consulta %q sin %s", query, want)
		}
	}
}

func TestPromptPreviewFailureIsSanitized(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/prompts/estimation", 422, map[string]any{"detail": "interno"})
	h.wantStatus(h.get("/api/prompt-preview?prompt_version=v9"), 422)
}

// --- Chunking Lab ---

func stubCompare(h *harness, body any) {
	h.api.stubJSON("POST", "/embeddings/compare", 200, body)
}

func TestLabOptionsListTheCatalog(t *testing.T) {
	h := newHarness(t)
	r := h.get("/api/chunking-comparisons/options")

	h.wantStatus(r, 200)
	body := r.object(t)
	strategies := body["strategies"].([]any)
	if len(strategies) != 8 {
		t.Fatalf("estrategias: %d", len(strategies))
	}
	contextual := strategies[7].(map[string]any)
	if contextual["name"] != "contextual_retrieval" || contextual["key_name"] != "ANTHROPIC_API_KEY" || contextual["paid"] != true {
		t.Errorf("contextual: %v", contextual)
	}
	if defaults := body["default_strategies"].([]any); len(defaults) != 3 || defaults[0] != "structural" {
		t.Errorf("por defecto: %v", defaults)
	}
	if len(body["sample_queries"].([]any)) == 0 || body["default_top_k"].(float64) != 3 || body["compare_timeout_seconds"].(float64) != 10 {
		t.Errorf("opciones: %v", body)
	}
}

func TestLabCreateRunsSavesAndReturnsTheComparison(t *testing.T) {
	h := newHarness(t)
	stubCompare(h, compareBody([]string{"structural", "hierarchical"}, []string{"oauth", "otra"}, 0))

	r := h.sendJSON("POST", "/api/chunking-comparisons", map[string]any{
		"strategies": []string{"structural", "inventada", "hierarchical", "structural"},
		"queries":    []string{" oauth ", "", "otra", "oauth"},
		"top_k":      99,
	})

	h.wantStatus(r, 201)
	body := r.object(t)
	if body["id"].(float64) != 1 || body["saved"] != true || body["top_k"].(float64) != 10 {
		t.Errorf("comparación: %v", body)
	}
	if got := body["strategies"].([]any); len(got) != 2 || got[0] != "structural" || got[1] != "hierarchical" {
		t.Errorf("estrategias: %v", got)
	}
	if body["response"].(map[string]any)["stats_per_strategy"] == nil {
		t.Errorf("sin respuesta: %v", body)
	}
	sent := jsonBody(t, h.api.requests("POST", "/embeddings/compare")[0])
	if got := sent["queries"].([]any); len(got) != 2 || got[0] != "oauth" || got[1] != "otra" {
		t.Errorf("consultas enviadas: %v", got)
	}
	if sent["top_k"].(float64) != 10 || len(sent["budgets"].([]any)) == 0 {
		t.Errorf("cuerpo enviado: top_k=%v", sent["top_k"])
	}

	again := h.get("/api/chunking-comparisons/1")
	h.wantStatus(again, 200)
	if again.object(t)["id"].(float64) != 1 {
		t.Errorf("detalle: %s", again.body)
	}
}

func TestLabCreateWithoutStrategiesDoesNotCallTheAPI(t *testing.T) {
	h := newHarness(t)
	for _, body := range []map[string]any{{"strategies": []string{}}, {"strategies": []string{"nope"}}, {}} {
		h.wantDetail(h.sendJSON("POST", "/api/chunking-comparisons", body), 422, "Selecciona al menos una estrategia.")
	}
	if got := h.api.count("POST", "/embeddings/compare"); got != 0 {
		t.Errorf("llamadas a la API: %d", got)
	}
}

func TestLabCreateRejectsMalformedBodies(t *testing.T) {
	h := newHarness(t)
	h.wantStatus(h.do("POST", "/api/chunking-comparisons", "application/json", strings.NewReader("{no es json")), 422)
	h.wantStatus(h.sendJSON("POST", "/api/chunking-comparisons", map[string]any{"strategies": []string{"structural"}, "top_k": "x"}), 422)
}

func TestLabErrorsMapToActionableStatuses(t *testing.T) {
	cases := map[string]struct {
		reply  reply
		status int
		detail string
	}{
		"400":           {jsonReply(map[string]any{"detail": "strategies inválidas"}, 400), 422, "Petición inválida: strategies inválidas"},
		"503 con clave": {jsonReply(map[string]any{"detail": "Falta ANTHROPIC_API_KEY"}, 503), 503, "ANTHROPIC_API_KEY"},
		"5xx":           {jsonReply(map[string]any{"trace": "Traceback sk-secret"}, 500), 502, "Error del servicio IA"},
		"caída":         {reply{drop: true}, 503, "No se pudo conectar"},
		"tiempo":        {reply{status: 200, body: "{}", delay: 300 * time.Millisecond}, 504, "prueba con menos estrategias"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t, withConfig(func(cfg *config.Config) { cfg.CompareTimeout = 100 * time.Millisecond }))
			h.api.stubReply("POST", "/embeddings/compare", c.reply)
			r := h.sendJSON("POST", "/api/chunking-comparisons", map[string]any{"strategies": []string{"structural"}})
			h.wantDetail(r, c.status, c.detail)
			for _, leak := range []string{"Traceback", "sk-secret", h.api.server.URL} {
				if strings.Contains(r.text(), leak) {
					t.Errorf("filtración %q: %s", leak, r.body)
				}
			}
		})
	}
}

func TestLabCreateReturnsUnsavedResultWhenTheDatabaseFails(t *testing.T) {
	store := &memStore{failWrite: true}
	h := newHarness(t, withStore(store))
	stubCompare(h, compareBody([]string{"structural"}, nil, 0))

	r := h.sendJSON("POST", "/api/chunking-comparisons", map[string]any{"strategies": []string{"structural"}})

	h.wantStatus(r, 201)
	body := r.object(t)
	if body["saved"] != false || !strings.Contains(body["notice"].(string), "no se pudo guardar en el historial") || body["response"] == nil {
		t.Errorf("respuesta sin guardar: %v", body)
	}
}

func TestLabCreateWithoutStoreReturnsUnsavedResult(t *testing.T) {
	h := newHarness(t, withoutStore())
	stubCompare(h, compareBody([]string{"structural"}, nil, 0))

	r := h.sendJSON("POST", "/api/chunking-comparisons", map[string]any{"strategies": []string{"structural"}})

	h.wantStatus(r, 201)
	if r.object(t)["saved"] != false {
		t.Errorf("debe devolver saved=false: %s", r.body)
	}
}

func seedComparison(t *testing.T, store rag.Store, strategies, queries []string, contextual float64, createdAt time.Time) {
	t.Helper()
	payload, _ := json.Marshal(compareBody(strategies, queries, contextual))
	duration := 3200
	row := rag.Comparison{Strategies: strategies, Queries: queries, TopK: 3, CorpusCount: 18, ResponsePayload: payload, DurationMS: &duration, CreatedAt: createdAt}
	if err := store.Create(context.Background(), &row); err != nil {
		t.Fatal(err)
	}
}

func TestLabHistoryIsNewestFirstWithoutCallingTheService(t *testing.T) {
	store := &memStore{}
	now := time.Now().UTC()
	seedComparison(t, store, []string{"structural"}, nil, 0, now.Add(-time.Hour))
	seedComparison(t, store, []string{"structural", "contextual_retrieval"}, nil, 0.14, now)
	h := newHarness(t, withStore(store))

	r := h.get("/api/chunking-comparisons")

	h.wantStatus(r, 200)
	items := r.list(t)
	if len(items) != 2 || items[0].(map[string]any)["id"].(float64) != 2 {
		t.Fatalf("orden: %s", r.body)
	}
	first := items[0].(map[string]any)
	if first["total_ingestion_cost_usd"].(float64) != 0.14 || first["strategy_labels"].([]any)[1] != "Contextual retrieval" {
		t.Errorf("resumen: %v", first)
	}
	if first["response"] != nil {
		t.Error("el listado no debe incluir la respuesta completa")
	}
	if len(h.api.calls) != 0 {
		t.Errorf("el historial no debe llamar a la API: %v", h.api.calls)
	}
}

func TestLabHistoryKeepsOnlyTheLast20(t *testing.T) {
	store := &memStore{}
	base := time.Now().UTC().Add(-time.Hour)
	for index := 0; index < 25; index++ {
		seedComparison(t, store, []string{"structural"}, nil, 0, base.Add(time.Duration(index)*time.Second))
	}
	h := newHarness(t, withStore(store))
	if got := len(h.get("/api/chunking-comparisons").list(t)); got != 20 {
		t.Errorf("elementos: %d", got)
	}
}

func TestLabHistoryUnavailableIs503(t *testing.T) {
	for name, opt := range map[string]option{"bd caída": withStore(&memStore{failRead: true}), "sin bd": withoutStore()} {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t, opt)
			h.wantDetail(h.get("/api/chunking-comparisons"), 503, "El historial no está disponible en este momento.")
			h.wantDetail(h.get("/api/chunking-comparisons/1"), 503, "El historial no está disponible en este momento.")
		})
	}
}

// --- Ajustes ---

func TestSettingsShowListsTheSevenKnobsWithOverridesAndProviderOptions(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/config/models", 200, configBody(map[string]string{"critic_model": "gpt-4o"}))

	r := h.get("/api/ai-settings")

	h.wantStatus(r, 200)
	body := r.object(t)
	models := body["models"].([]any)
	if len(models) != 7 {
		t.Fatalf("knobs: %d", len(models))
	}
	byKey := map[string]map[string]any{}
	for _, model := range models {
		entry := model.(map[string]any)
		byKey[entry["key"].(string)] = entry
	}
	critic := byKey["critic_model"]
	if critic["overridden"] != true || critic["selected"] != "gpt-4o" || critic["label"] != "Crítico (ACB)" {
		t.Errorf("crítico: %v", critic)
	}
	for _, option := range byKey["propositional_chunker_model"]["options"].([]any) {
		if strings.HasPrefix(option.(string), "claude") {
			t.Errorf("el chunker proposicional no admite %v", option)
		}
	}
	if byKey["primary_model"]["selected"] != "" || body["embedding_model"] != "text-embedding-3-small" || body["any_overridden"] != true {
		t.Errorf("respuesta: %v", body)
	}
}

func TestSettingsShowFailuresAreSanitized(t *testing.T) {
	h := newHarness(t)
	h.api.stubReply("GET", "/api/v1/config/models", reply{drop: true})
	r := h.get("/api/ai-settings")
	h.wantDetail(r, 503, "No se pudo conectar")
	if strings.Contains(r.text(), h.api.server.URL) {
		t.Error("filtra la URL interna")
	}
}

func TestSettingsUpdateSendsKnownKnobsAndNullsForEmptyOnes(t *testing.T) {
	h := newHarness(t)
	h.api.stub("PUT", "/api/v1/config/models", func(apiCall) reply { return jsonReply(configBody(map[string]string{"critic_model": "gpt-4o"})) })

	r := h.sendJSON("PUT", "/api/ai-settings", map[string]any{"models": map[string]any{
		"critic_model": "gpt-4o", "summary_model": "", "fallback_model": nil, "desconocido": "x",
	}})

	h.wantStatus(r, 200)
	sent := jsonBody(t, h.api.requests("PUT", "/api/v1/config/models")[0])["models"].(map[string]any)
	if len(sent) != 3 || sent["critic_model"] != "gpt-4o" || sent["summary_model"] != nil || sent["fallback_model"] != nil {
		t.Errorf("enviado: %v", sent)
	}
	if _, present := sent["summary_model"]; !present {
		t.Error("un knob vacío debe viajar como null")
	}
	if r.object(t)["any_overridden"] != true {
		t.Errorf("respuesta: %s", r.body)
	}
}

func TestSettingsUpdateWithNothingToChangeDoesNotCallTheService(t *testing.T) {
	h := newHarness(t)
	h.wantDetail(h.sendJSON("PUT", "/api/ai-settings", map[string]any{"models": map[string]any{"desconocido": "x"}}), 422, "No hay ningún modelo que cambiar.")
	h.wantStatus(h.do("PUT", "/api/ai-settings", "application/json", strings.NewReader("no json")), 422)
	if got := h.api.count("PUT", "/api/v1/config/models"); got != 0 {
		t.Errorf("llamadas: %d", got)
	}
}

func TestSettingsUpdateRejectionAndOutageStatuses(t *testing.T) {
	cases := map[string]struct {
		reply  reply
		status int
		detail string
	}{
		"rechazo":        {jsonReply(map[string]any{"detail": "Modelo sin clave: falta OPENAI_API_KEY"}, 422), 422, "Cambio rechazado: Modelo sin clave: falta OPENAI_API_KEY"},
		"sin almacén":    {jsonReply(map[string]any{"detail": "Almacén no disponible"}, 503), 503, "Almacén no disponible"},
		"servicio caído": {reply{drop: true}, 503, "No se pudo conectar"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t)
			h.api.stubReply("PUT", "/api/v1/config/models", c.reply)
			r := h.sendJSON("PUT", "/api/ai-settings", map[string]any{"models": map[string]any{"critic_model": "gpt-4o"}})
			h.wantDetail(r, c.status, c.detail)
			if strings.Contains(r.text(), h.api.server.URL) {
				t.Error("filtra la URL interna")
			}
		})
	}
}

func TestPrimaryModelIsCachedAndSavingSettingsInvalidatesIt(t *testing.T) {
	h := newHarness(t)
	current := "gpt-4o-mini"
	h.api.stub("GET", "/api/v1/config/models", func(apiCall) reply {
		return jsonReply(configBody(map[string]string{"primary_model": current}))
	})
	h.api.stub("PUT", "/api/v1/config/models", func(apiCall) reply {
		current = "gpt-4o"
		return jsonReply(configBody(map[string]string{"primary_model": current}))
	})

	first := h.get("/api/primary-model")
	h.get("/api/primary-model")
	if first.object(t)["primary_model"] != "gpt-4o-mini" || h.api.count("GET", "/api/v1/config/models") != 1 {
		t.Fatalf("caché: %s (%d llamadas)", first.body, h.api.count("GET", "/api/v1/config/models"))
	}

	h.wantStatus(h.sendJSON("PUT", "/api/ai-settings", map[string]any{"models": map[string]any{"primary_model": "gpt-4o"}}), 200)

	if got := h.get("/api/primary-model").object(t)["primary_model"]; got != "gpt-4o" {
		t.Errorf("tras guardar: %v", got)
	}
}

func TestPrimaryModelOmitsTheValueWhenTheServiceFailsAndCachesTheFailure(t *testing.T) {
	h := newHarness(t)
	h.api.stubReply("GET", "/api/v1/config/models", reply{drop: true})

	for range 3 {
		r := h.get("/api/primary-model")
		h.wantStatus(r, 200)
		if got := r.object(t)["primary_model"]; got != "" {
			t.Errorf("primary_model: %v", got)
		}
	}
	if got := h.api.count("GET", "/api/v1/config/models"); got != 1 {
		t.Errorf("el fallo debe cachearse (%d llamadas)", got)
	}
}

// --- Robustez ---

func TestAPanicRespondsGenericJSON500AndTheServerKeepsServing(t *testing.T) {
	h := newHarness(t)
	handler := h.server.recoverer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/boom" {
			panic("secreto sk-123")
		}
		w.WriteHeader(200)
	}))
	app := httptest.NewServer(handler)
	defer app.Close()

	reply, err := http.Get(app.URL + "/boom")
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(reply.Body)
	reply.Body.Close()
	if reply.StatusCode != 500 || strings.Contains(string(body), "sk-123") || !strings.Contains(string(body), "detail") {
		t.Errorf("pánico: %d %s", reply.StatusCode, body)
	}
	ok, err := http.Get(app.URL + "/ok")
	if err != nil || ok.StatusCode != 200 {
		t.Errorf("el servidor debe seguir: %v", err)
	}
}
