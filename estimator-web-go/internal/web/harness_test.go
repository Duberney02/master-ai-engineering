package web

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"mime/multipart"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"net/textproto"
	"net/url"
	"regexp"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"

	"estimator-web/internal/config"
	"estimator-web/internal/rag"
)

// --- API de IA simulada (equivale a WebMock): las pruebas nunca llaman a la API real ---

const sessionID = "6f1c2c1e-6d0a-4a5e-9c1a-0d6f5b1f4a10"

// reply es la respuesta que da la API simulada a una petición.
type reply struct {
	status int
	body   string
	delay  time.Duration
	drop   bool // cierra la conexión sin responder (API caída)
}

func jsonReply(body any, status ...int) reply {
	encoded, err := json.Marshal(body)
	if err != nil {
		panic(err)
	}
	code := http.StatusOK
	if len(status) > 0 {
		code = status[0]
	}
	return reply{status: code, body: string(encoded)}
}

// apiCall es una petición recibida por la API simulada.
type apiCall struct {
	method, path, rawQuery, contentType string
	body                                []byte
}

type fakeAPI struct {
	t      *testing.T
	server *httptest.Server
	mu     sync.Mutex
	stubs  map[string]func(apiCall) reply
	calls  []apiCall
}

func newFakeAPI(t *testing.T) *fakeAPI {
	api := &fakeAPI{t: t, stubs: map[string]func(apiCall) reply{}}
	api.server = httptest.NewServer(http.HandlerFunc(api.serve))
	t.Cleanup(api.server.Close)
	return api
}

func (a *fakeAPI) serve(w http.ResponseWriter, r *http.Request) {
	body, _ := io.ReadAll(r.Body)
	call := apiCall{method: r.Method, path: r.URL.EscapedPath(), rawQuery: r.URL.RawQuery, contentType: r.Header.Get("Content-Type"), body: body}
	a.mu.Lock()
	a.calls = append(a.calls, call)
	stub, ok := a.stubs[r.Method+" "+call.path]
	a.mu.Unlock()
	if !ok {
		a.t.Errorf("petición a la API sin simular: %s %s", r.Method, call.path)
		w.WriteHeader(599)
		return
	}
	answer := stub(call)
	if answer.drop {
		panic(http.ErrAbortHandler)
	}
	time.Sleep(answer.delay)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(answer.status)
	_, _ = io.WriteString(w, answer.body)
}

// stub fija la respuesta de una ruta.
func (a *fakeAPI) stub(method, path string, answer func(apiCall) reply) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.stubs[method+" "+path] = answer
}

func (a *fakeAPI) stubReply(method, path string, answer reply) {
	a.stub(method, path, func(apiCall) reply { return answer })
}

func (a *fakeAPI) stubJSON(method, path string, status int, body any) {
	a.stubReply(method, path, jsonReply(body, status))
}

// requests devuelve las llamadas recibidas por una ruta.
func (a *fakeAPI) requests(method, path string) []apiCall {
	a.mu.Lock()
	defer a.mu.Unlock()
	var found []apiCall
	for _, call := range a.calls {
		if call.method == method && call.path == path {
			found = append(found, call)
		}
	}
	return found
}

func (a *fakeAPI) count(method, path string) int { return len(a.requests(method, path)) }

// --- Cuerpos de la API (los de test_helper.rb) ---

var result = map[string]any{
	"summary": "Portal mediano con facturación y soporte.", "confidence_pct": 70, "total_duration_weeks": 10,
	"total_cost_eur": 20000, "out_of_scope": false,
	"phases": []any{
		map[string]any{"name": "Diseño", "description": "UX y prototipos", "duration_weeks": 2, "cost_eur": 4000},
		map[string]any{"name": "Desarrollo", "description": "App y API", "duration_weeks": 8, "cost_eur": 16000},
	},
}

var outOfScope = map[string]any{
	"summary": "Out of scope: la reunión no define el alcance.", "confidence_pct": 12, "total_duration_weeks": 1,
	"total_cost_eur": 0, "out_of_scope": true,
	"phases": []any{map[string]any{"name": "No estimable", "description": "", "duration_weeks": 1, "cost_eur": 0}},
}

var emptyMetadata = map[string]any{"project_name": nil, "assumed_team_size": nil, "mentioned_technologies": []any{}, "agreed_scope": nil}

var projectMetadata = map[string]any{
	"project_name": "Orion", "assumed_team_size": 4, "mentioned_technologies": []any{"FastAPI", "Kafka"},
	"agreed_scope": "Portal y panel de administración",
}

func metricsBody(cacheHit bool, cost any) map[string]any {
	return map[string]any{
		"model": "gpt-4o-mini", "provider": "openai", "finish_reason": "stop",
		"usage":      map[string]any{"input_tokens": 12400, "output_tokens": 860, "total_tokens": 13260},
		"latency_ms": 8450, "cache_hit": cacheHit, "estimated_cost_usd": cost, "request_cost_usd": cost,
	}
}

type estimateOptions struct {
	result   map[string]any
	id       any
	source   string
	metadata map[string]any
}

// estimateBody es la respuesta de `POST /sessions/{id}/estimate`: la estimación más el estado de la conversación.
func estimateBody(opts estimateOptions) map[string]any {
	if opts.result == nil {
		opts.result = result
	}
	if opts.source == "" {
		opts.source = "none"
	}
	if opts.metadata == nil {
		opts.metadata = emptyMetadata
	}
	return map[string]any{
		"result": opts.result, "prompt_version": "v3", "cached": opts.source != "none", "cache_source": opts.source,
		"estimation_id": opts.id, "metrics": metricsBody(false, 0.000412), "session_id": sessionID,
		"project_metadata": opts.metadata, "turn_count": 1, "max_turns": 6,
	}
}

type detailOptions struct {
	id          int
	result      map[string]any
	source      string
	metrics     any
	description string
}

func detailBody(opts detailOptions) map[string]any {
	if opts.id == 0 {
		opts.id = 7
	}
	if opts.result == nil {
		opts.result = result
	}
	if opts.source == "" {
		opts.source = "none"
	}
	if opts.description == "" {
		opts.description = "Portal de clientes para facturas e incidencias."
	}
	metrics := opts.metrics
	if metrics == nil {
		metrics = metricsBody(false, 0.000412)
	} else if metrics == "none" {
		metrics = nil
	}
	return map[string]any{
		"id": opts.id, "requested_at": "2026-10-05T10:30:00Z", "completed_at": "2026-10-05T10:30:09Z", "description": opts.description,
		"options": map[string]any{"project_type": "web_saas", "detail_level": "medium", "output_format": "phases_table"},
		"result":  opts.result, "prompt_version": "v3", "cached": opts.source != "none", "cache_source": opts.source,
		"model": "gpt-4o-mini", "provider": "openai", "metrics": metrics,
	}
}

func summaryItem(id int, res map[string]any, source string) map[string]any {
	return map[string]any{
		"id": id, "requested_at": "2026-10-05T10:30:00Z", "project_type": "web_saas", "detail_level": "medium",
		"output_format": "phases_table", "prompt_version": "v3", "cache_source": source, "confidence_pct": res["confidence_pct"],
		"total_cost_eur": res["total_cost_eur"], "total_duration_weeks": res["total_duration_weeks"], "out_of_scope": res["out_of_scope"],
		"description_excerpt": "Portal de clientes para facturas",
	}
}

const systemPrompt = "Eres un arquitecto sénior de estimación de software.\n\n## Instrucciones generales\n1. Basa la estimación solo en la descripción."

func promptBody() map[string]any {
	return map[string]any{
		"prompt_version": "v3", "system_prompt": systemPrompt,
		"examples": []any{
			map[string]any{"title": "Portal de reservas para un gimnasio", "description": "Web donde los socios reservan clases."},
			map[string]any{"title": "Plataforma de IA para todo el hospital", "description": "Queremos una IA que mejore el hospital."},
		},
	}
}

var knobKeys = []string{"primary_model", "fallback_model", "critic_model", "metadata_model", "summary_model", "propositional_chunker_model", "contextual_chunker_model"}

// configBody es la respuesta de `GET /api/v1/config/models`; `overrides` fija `effective` y marca `overridden`.
func configBody(overrides map[string]string) map[string]any {
	defaults := map[string]any{"fallback_model": nil, "propositional_chunker_model": "gpt-4o-mini", "contextual_chunker_model": "claude-sonnet-4-5"}
	models := map[string]any{}
	for _, key := range knobKeys {
		def, ok := defaults[key]
		if !ok {
			def = "gpt-4o-mini"
		}
		effective, overridden := overrides[key]
		var effectiveValue any = def
		if overridden {
			effectiveValue = effective
		}
		models[key] = map[string]any{"effective": effectiveValue, "default": def, "overridden": overridden}
	}
	return map[string]any{
		"models": models, "available_models": []any{"gpt-4o-mini", "gpt-4o", "claude-haiku-4-5", "claude-sonnet-4-5"},
		"embedding_model": "text-embedding-3-small", "embedding_model_note": "Solo lectura: cambiarlo invalidaría todos los vectores guardados.",
	}
}

func statsBody(strategy string, cost float64) map[string]any {
	return map[string]any{
		"strategy": strategy, "n_chunks": 10, "token_distribution": map[string]any{"min": 40, "p50": 79.0, "p95": 120.5, "max": 300},
		"n_orphan_chunks": 0, "n_obese_chunks": 0, "ingestion_cost_usd": cost, "extra_api_calls": 0, "ingestion_seconds": 0.012,
	}
}

func topChunk(id string, cosine float64, level, parent string) map[string]any {
	chunk := map[string]any{"chunk_id": id, "cosine": cosine, "text_preview": "Vista previa de " + id, "level": nil, "parent_chunk_id": nil}
	if level != "" {
		chunk["level"] = level
	}
	if parent != "" {
		chunk["parent_chunk_id"] = parent
	}
	return chunk
}

// compareBody es la respuesta de `POST /embeddings/compare`.
func compareBody(strategies, queries []string, contextualCost float64) map[string]any {
	stats := map[string]any{}
	perStrategy := map[string]any{}
	for _, name := range strategies {
		cost := 0.0
		if name == "contextual_retrieval" {
			cost = contextualCost
		}
		stats[name] = statsBody(name, cost)
		var results []any
		for _, query := range queries {
			top := []any{topChunk("BUD-1::AUTH-1", 0.64, "", "")}
			if name == "hierarchical" {
				top = []any{topChunk("BUD-1::parent", 0.71, "parent", ""), topChunk("BUD-1::AUTH-1", 0.64, "child", "BUD-1::parent")}
			}
			results = append(results, map[string]any{"strategy": name, "query": query, "top_k": top})
		}
		perStrategy[name] = results
	}
	body := map[string]any{"stats_per_strategy": stats, "queries_per_strategy": map[string]any{}}
	if len(queries) > 0 {
		body["queries_per_strategy"] = perStrategy
	}
	return body
}

// --- Historial en memoria (el de PostgreSQL se prueba en rag y en pg_test.go) ---

type memStore struct {
	mu        sync.Mutex
	rows      []rag.Comparison
	failRead  bool
	failWrite bool
}

var errStoreDown = fmt.Errorf("db down")

func (m *memStore) Create(_ context.Context, comparison *rag.Comparison) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.failWrite {
		return errStoreDown
	}
	if err := comparison.Validate(); err != nil {
		return err
	}
	comparison.ID = int64(len(m.rows) + 1)
	if comparison.CreatedAt.IsZero() {
		comparison.CreatedAt = time.Now().UTC()
	}
	m.rows = append(m.rows, *comparison)
	return nil
}

func (m *memStore) Recent(_ context.Context, limit int) ([]rag.Comparison, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.failRead {
		return nil, errStoreDown
	}
	sorted := append([]rag.Comparison{}, m.rows...)
	sort.SliceStable(sorted, func(i, j int) bool { return sorted[i].CreatedAt.After(sorted[j].CreatedAt) })
	if len(sorted) > limit {
		sorted = sorted[:limit]
	}
	return sorted, nil
}

func (m *memStore) Find(_ context.Context, id int64) (*rag.Comparison, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.failRead {
		return nil, errStoreDown
	}
	for _, row := range m.rows {
		if row.ID == id {
			found := row
			return &found, nil
		}
	}
	return nil, rag.ErrNotFound
}

// --- Navegador simulado ---

type harness struct {
	t      *testing.T
	api    *fakeAPI
	app    *httptest.Server
	server *Server
	client *http.Client
	csrf   string
	cfg    config.Config
	store  rag.Store
}

type option func(*harness)

func withConfig(change func(*config.Config)) option { return func(h *harness) { change(&h.cfg) } }
func withStore(store rag.Store) option              { return func(h *harness) { h.store = store } }

func newHarness(t *testing.T, opts ...option) *harness {
	t.Helper()
	api := newFakeAPI(t)
	api.stubJSON("GET", "/api/v1/prompts/estimation", 200, promptBody())
	api.stubJSON("POST", "/api/v1/sessions", 201, map[string]any{"session_id": sessionID})
	api.stubJSON("GET", "/api/v1/config/models", 200, configBody(nil))

	h := &harness{t: t, api: api, store: &memStore{}}
	h.cfg = config.Config{
		Port: "0", APIURL: api.server.URL, OpenTimeout: time.Second, ReadTimeout: 5 * time.Second,
		CompareTimeout: 10 * time.Second, BadgeTimeout: time.Second, SecretKeyBase: "secreto-de-pruebas",
	}
	for _, opt := range opts {
		opt(h)
	}
	server, err := New(h.cfg, h.store, nil)
	if err != nil {
		t.Fatal(err)
	}
	h.server = server
	h.app = httptest.NewServer(server.Handler())
	t.Cleanup(h.app.Close)

	jar, _ := cookiejar.New(nil)
	h.client = &http.Client{Jar: jar, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	return h
}

// page es una respuesta del servicio.
type page struct {
	status   int
	body     string
	location string
	header   http.Header
}

var csrfMeta = regexp.MustCompile(`<meta name="csrf-token" content="([^"]+)"`)

func (h *harness) do(request *http.Request) *page {
	h.t.Helper()
	response, err := h.client.Do(request)
	if err != nil {
		h.t.Fatal(err)
	}
	defer response.Body.Close()
	body, _ := io.ReadAll(response.Body)
	result := &page{status: response.StatusCode, body: string(body), location: response.Header.Get("Location"), header: response.Header}
	if match := csrfMeta.FindStringSubmatch(result.body); match != nil {
		h.csrf = match[1]
	}
	return result
}

func (h *harness) get(path string) *page {
	h.t.Helper()
	request, _ := http.NewRequest(http.MethodGet, h.app.URL+path, nil)
	return h.do(request)
}

// token devuelve el token CSRF de la sesión actual (abre una página si todavía no hay).
func (h *harness) token() string {
	h.t.Helper()
	if h.csrf == "" {
		h.get("/")
	}
	return h.csrf
}

// post envía un formulario urlencoded con el token CSRF de la sesión.
func (h *harness) post(path string, values url.Values) *page {
	h.t.Helper()
	if values == nil {
		values = url.Values{}
	}
	if values.Get("authenticity_token") == "" {
		values.Set("authenticity_token", h.token())
	}
	request, _ := http.NewRequest(http.MethodPost, h.app.URL+path, strings.NewReader(values.Encode()))
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	return h.do(request)
}

// patch envía el formulario como lo hace el navegador: POST con `_method=patch`.
func (h *harness) patch(path string, values url.Values) *page {
	if values == nil {
		values = url.Values{}
	}
	values.Set("_method", "patch")
	return h.post(path, values)
}

type upload struct{ field, filename, contentType, content string }

// postMultipart envía un formulario multipart con campos y archivos.
func (h *harness) postMultipart(path string, fields url.Values, files []upload) *page {
	h.t.Helper()
	if fields == nil {
		fields = url.Values{}
	}
	if fields.Get("authenticity_token") == "" {
		fields.Set("authenticity_token", h.token())
	}
	var buffer bytes.Buffer
	writer := multipart.NewWriter(&buffer)
	for name, values := range fields {
		for _, value := range values {
			_ = writer.WriteField(name, value)
		}
	}
	for _, file := range files {
		header := textproto.MIMEHeader{}
		header.Set("Content-Disposition", fmt.Sprintf(`form-data; name="%s"; filename="%s"`, file.field, file.filename))
		contentType := file.contentType
		if contentType == "" {
			contentType = "application/octet-stream"
		}
		header.Set("Content-Type", contentType)
		part, _ := writer.CreatePart(header)
		_, _ = part.Write([]byte(file.content))
	}
	_ = writer.Close()
	request, _ := http.NewRequest(http.MethodPost, h.app.URL+path, &buffer)
	request.Header.Set("Content-Type", writer.FormDataContentType())
	return h.do(request)
}

// --- Aserciones sobre el HTML ---

func (p *page) has(snippet string) bool { return strings.Contains(p.body, snippet) }

func (h *harness) wantStatus(p *page, status int) {
	h.t.Helper()
	if p.status != status {
		h.t.Fatalf("estado %d, se esperaba %d. Cuerpo:\n%s", p.status, status, abbreviate(p.body))
	}
}

func (h *harness) wantContains(p *page, snippets ...string) {
	h.t.Helper()
	for _, snippet := range snippets {
		if !p.has(snippet) {
			h.t.Errorf("falta %q en la respuesta:\n%s", snippet, abbreviate(p.body))
		}
	}
}

func (h *harness) wantAbsent(p *page, snippets ...string) {
	h.t.Helper()
	for _, snippet := range snippets {
		if p.has(snippet) {
			h.t.Errorf("no debería aparecer %q en la respuesta", snippet)
		}
	}
}

func abbreviate(text string) string {
	if len(text) > 3000 {
		return text[:3000] + "…"
	}
	return text
}

var tags = regexp.MustCompile(`<[^>]+>`)

// textOf devuelve el texto (sin etiquetas, con espacios colapsados) del elemento con ese id.
func (p *page) textOf(id string) (string, bool) {
	start := strings.Index(p.body, `id="`+id+`"`)
	if start < 0 {
		return "", false
	}
	open := strings.Index(p.body[start:], ">")
	if open < 0 {
		return "", false
	}
	rest := p.body[start+open+1:]
	tagStart := strings.LastIndex(p.body[:start], "<")
	name := strings.Fields(p.body[tagStart+1 : start])[0]
	depth, index := 1, 0
	openTag, closeTag := "<"+name, "</"+name+">"
	for depth > 0 {
		nextClose := strings.Index(rest[index:], closeTag)
		if nextClose < 0 {
			return "", false
		}
		nextOpen := strings.Index(rest[index:], openTag)
		if nextOpen >= 0 && nextOpen < nextClose && isTagBoundary(rest, index+nextOpen+len(openTag)) {
			depth++
			index += nextOpen + len(openTag)
			continue
		}
		depth--
		index += nextClose
		if depth > 0 {
			index += len(closeTag)
		}
	}
	return squash(tags.ReplaceAllString(rest[:index], " ")), true
}

func isTagBoundary(text string, position int) bool {
	if position >= len(text) {
		return false
	}
	return strings.ContainsRune(" >/\n", rune(text[position]))
}

func squash(text string) string { return strings.Join(strings.Fields(htmlUnescape(text)), " ") }

func htmlUnescape(text string) string {
	return strings.NewReplacer("&amp;", "&", "&lt;", "<", "&gt;", ">", "&#34;", `"`, "&#39;", "'", "&quot;", `"`).Replace(text)
}

// count cuenta las coincidencias de una expresión regular.
func (p *page) count(pattern string) int {
	return len(regexp.MustCompile(pattern).FindAllString(p.body, -1))
}

// multipartFields lee los campos de texto y los archivos de un cuerpo multipart recibido por la API simulada.
func multipartFields(t *testing.T, call apiCall) (map[string]string, []*multipart.FileHeader) {
	t.Helper()
	mediaType, params, err := mime.ParseMediaType(call.contentType)
	if err != nil || mediaType != "multipart/form-data" {
		t.Fatalf("Content-Type multipart esperado, llegó %q", call.contentType)
	}
	form, err := multipart.NewReader(bytes.NewReader(call.body), params["boundary"]).ReadForm(64 << 20)
	if err != nil {
		t.Fatal(err)
	}
	fields := map[string]string{}
	for name, values := range form.Value {
		fields[name] = values[0]
	}
	return fields, form.File["attachments"]
}

// jsonBody decodifica el cuerpo JSON de una llamada.
func jsonBody(t *testing.T, call apiCall) map[string]any {
	t.Helper()
	var decoded map[string]any
	if err := json.Unmarshal(call.body, &decoded); err != nil {
		t.Fatalf("cuerpo JSON inválido: %v", err)
	}
	return decoded
}
