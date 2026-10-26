package web

import (
	"context"
	"net/url"
	"strings"
	"testing"
	"time"

	"estimator-web/internal/config"
	"estimator-web/internal/estimatorai"
	"estimator-web/internal/rag"
)

const comparePath = "/embeddings/compare"

func runValues(overrides map[string][]string) url.Values {
	values := url.Values{"strategies[]": {"structural", "hierarchical"}, "top_k": {"3"}}
	for key, value := range overrides {
		values[key] = value
	}
	return values
}

func stubCompare(h *harness, body any) {
	h.api.stubJSON("POST", comparePath, 200, body)
}

func saved(t *testing.T, store *memStore, strategies []string, queries []string, createdAt time.Time, contextual float64) rag.Comparison {
	t.Helper()
	payload, _ := jsonMarshal(compareBody(strategies, queries, contextual))
	row := rag.Comparison{Strategies: strategies, Queries: queries, TopK: 3, CorpusCount: 18, ResponsePayload: payload, CreatedAt: createdAt}
	duration := 3200
	row.DurationMS = &duration
	if err := store.Create(context.Background(), &row); err != nil {
		t.Fatal(err)
	}
	return row
}

// --- Formulario ---

func TestNewPreselectsTheFreeStrategiesAndFlagsThePaidOnes(t *testing.T) {
	h := newHarness(t)
	p := h.get("/rag/chunking_comparisons/new")

	h.wantStatus(p, 200)
	for _, name := range []string{"structural", "fixed_size", "recursive"} {
		h.wantContains(p, `id="strategy_`+name+`" value="`+name+`" checked="checked"`)
	}
	for _, name := range []string{"sentence_window", "hierarchical", "semantic", "propositional", "contextual_retrieval"} {
		h.wantContains(p, `id="strategy_`+name+`" value="`+name+`" data-paid=`)
	}
	h.wantContains(p, `id="strategy_propositional" value="propositional" data-paid="true"`, `id="strategy_structural" value="structural" checked="checked" data-paid="false"`)
	if got := p.count(`<span class="badge expensive">\s*de pago \(LLM\)`); got != 2 {
		t.Errorf("etiquetas de pago (LLM): %d", got)
	}
	h.wantContains(p, "requiere ANTHROPIC_API_KEY", "requiere OPENAI_API_KEY", `id="paid-warning" hidden`, "hasta 10 s")
}

func TestNewOffersThePredefinedQueriesAndTopK(t *testing.T) {
	h := newHarness(t)
	p := h.get("/rag/chunking_comparisons/new")

	if got := p.count(`name="queries\[\]"`); got != len(estimatorai.SampleQueries()) {
		t.Errorf("consultas: %d", got)
	}
	h.wantContains(p, `id="top_k" value="3" min="1" max="10"`, `<textarea name="custom_queries" id="custom_queries" rows="3">`)
	h.wantContains(p, "sobre 18 presupuestos históricos")
}

// --- Ejecución ---

func TestCreateSendsTheCorpusStrategiesQueriesAndTopKThenSavesAndRedirects(t *testing.T) {
	store := &memStore{}
	h := newHarness(t, withStore(store))
	stubCompare(h, compareBody([]string{"structural", "hierarchical"}, []string{"oauth", "otra"}, 0))

	p := h.post("/rag/chunking_comparisons", runValues(map[string][]string{
		"queries[]": {"oauth"}, "custom_queries": {"otra\n\n  "}, "top_k": {"2"},
	}))

	call := h.api.requests("POST", comparePath)
	if len(call) != 1 {
		t.Fatalf("llamadas a la comparación: %d", len(call))
	}
	body := jsonBody(t, call[0])
	if strings.Join(toStrings(body["strategies"]), ",") != "structural,hierarchical" || strings.Join(toStrings(body["queries"]), ",") != "oauth,otra" ||
		body["top_k"] != float64(2) || len(body["budgets"].([]any)) != len(estimatorai.Budgets()) {
		t.Errorf("cuerpo enviado: strategies=%v queries=%v top_k=%v", body["strategies"], body["queries"], body["top_k"])
	}
	if !strings.HasPrefix(call[0].contentType, "application/json") {
		t.Errorf("Content-Type: %s", call[0].contentType)
	}

	h.wantStatus(p, 302)
	if len(store.rows) != 1 || p.location != "/rag/chunking_comparisons/1" {
		t.Fatalf("filas %d, redirección %q", len(store.rows), p.location)
	}
	row := store.rows[0]
	if strings.Join(row.Queries, ",") != "oauth,otra" || row.TopK != 2 || row.CorpusCount != len(estimatorai.Budgets()) || row.DurationMS == nil || row.CorpusLabel != estimatorai.CorpusLabel {
		t.Errorf("fila guardada: %+v", row)
	}
}

func TestCreateIgnoresUnknownStrategiesDeduplicatesAndClampsTopK(t *testing.T) {
	h := newHarness(t)
	stubCompare(h, compareBody([]string{"structural"}, nil, 0))

	h.post("/rag/chunking_comparisons", runValues(map[string][]string{"strategies[]": {"structural", "magic", "structural"}, "top_k": {"99"}}))

	body := jsonBody(t, h.api.requests("POST", comparePath)[0])
	if strings.Join(toStrings(body["strategies"]), ",") != "structural" || body["top_k"] != float64(10) {
		t.Errorf("cuerpo: %v %v", body["strategies"], body["top_k"])
	}

	h.post("/rag/chunking_comparisons", runValues(map[string][]string{"top_k": {"abc"}}))
	if jsonBody(t, h.api.requests("POST", comparePath)[1])["top_k"] != float64(1) {
		t.Error("un top_k no numérico se limita a 1")
	}
}

func TestCreateWithoutStrategiesIsRefusedBeforeCallingTheService(t *testing.T) {
	store := &memStore{}
	h := newHarness(t, withStore(store))

	p := h.post("/rag/chunking_comparisons", runValues(map[string][]string{"strategies[]": nil}))

	h.wantStatus(p, 422)
	if text, _ := p.textOf("flash-alert"); !strings.Contains(text, "al menos una estrategia") {
		t.Errorf("aviso: %q", text)
	}
	if h.api.count("POST", comparePath) != 0 || len(store.rows) != 0 {
		t.Error("no debe llamarse al servicio ni guardarse nada")
	}
	h.wantContains(p, `id="lab-form"`)
}

func TestCreateUsesTheExtendedTimeoutOnlyForThisCall(t *testing.T) {
	h := newHarness(t, withConfig(func(c *config.Config) {
		c.ReadTimeout = 50 * time.Millisecond
		c.CompareTimeout = 5 * time.Second
	}))
	h.api.stub("POST", comparePath, func(apiCall) reply {
		answer := jsonReply(compareBody([]string{"structural"}, nil, 0))
		answer.delay = 300 * time.Millisecond
		return answer
	})
	h.api.stubReply("GET", "/api/v1/estimations/7", reply{status: 200, body: "{}", delay: 300 * time.Millisecond})

	if p := h.post("/rag/chunking_comparisons", runValues(nil)); p.status != 302 {
		t.Errorf("la comparación debe usar el tiempo ampliado (estado %d)", p.status)
	}
	if p := h.get("/estimations/7"); p.status != 502 {
		t.Errorf("el resto de flujos conserva el tiempo global (estado %d)", p.status)
	}
}

// --- Mapeo de errores ---

func TestServiceErrorsMapToTheRightStatusAndSanitizedMessage(t *testing.T) {
	cases := []struct {
		name    string
		answer  reply
		status  int
		message string
		absent  []string
	}{
		{"400 con detalle", jsonReply(map[string]any{"detail": "Estrategia desconocida: magic"}, 400), 422, "Petición inválida: Estrategia desconocida", nil},
		{"503 por clave ausente", jsonReply(map[string]any{"detail": "La estrategia 'contextual_retrieval' requiere ANTHROPIC_API_KEY."}, 503), 503, "ANTHROPIC_API_KEY", nil},
		{"servicio caído", reply{drop: true}, 503, "No se pudo conectar", []string{"EOF"}},
		{"error del servidor", reply{status: 500, body: "Traceback secret"}, 502, "Error del servicio IA", []string{"Traceback"}},
		{"respuesta inválida", jsonReply(map[string]any{"x": 1}), 502, "Error del servicio IA: La API del estimador devolvió una respuesta inválida.", nil},
	}
	for _, tc := range cases {
		h := newHarness(t)
		h.api.stubReply("POST", comparePath, tc.answer)

		p := h.post("/rag/chunking_comparisons", runValues(nil))

		h.wantStatus(p, tc.status)
		if text, _ := p.textOf("flash-alert"); !strings.Contains(text, tc.message) {
			t.Errorf("%s: aviso %q", tc.name, text)
		}
		h.wantContains(p, `id="lab-form"`)
		h.wantAbsent(p, append(tc.absent, h.api.server.URL)...)
	}
}

func TestAServiceTimeoutIsA504ThatSuggestsFewerStrategies(t *testing.T) {
	h := newHarness(t, withConfig(func(c *config.Config) { c.CompareTimeout = 50 * time.Millisecond }))
	h.api.stubReply("POST", comparePath, reply{status: 200, body: "{}", delay: 300 * time.Millisecond})

	p := h.post("/rag/chunking_comparisons", runValues(nil))

	h.wantStatus(p, 504)
	if text, _ := p.textOf("flash-alert"); !strings.Contains(text, "no respondió") || !strings.Contains(text, "menos estrategias") {
		t.Errorf("aviso: %q", text)
	}
}

func TestIfTheHistoryCannotSaveAComputedRunItIsShownAnyway(t *testing.T) {
	store := &memStore{failWrite: true}
	h := newHarness(t, withStore(store))
	stubCompare(h, compareBody([]string{"structural", "hierarchical"}, nil, 0))

	p := h.post("/rag/chunking_comparisons", runValues(nil))

	h.wantStatus(p, 200)
	if text, _ := p.textOf("flash-alert"); !strings.Contains(text, "no se pudo guardar en el historial") {
		t.Errorf("aviso: %q", text)
	}
	h.wantContains(p, `id="stats-table"`)
	h.wantAbsent(p, "Ejecutada el")
}

func TestWithoutADatabaseTheLabStillComputesAndShowsTheRun(t *testing.T) {
	h := newHarness(t, withStore(nil))
	stubCompare(h, compareBody([]string{"structural"}, nil, 0))

	p := h.post("/rag/chunking_comparisons", runValues(nil))

	h.wantStatus(p, 200)
	h.wantContains(p, `id="stats-table"`, "no se pudo guardar en el historial")
}

// --- Resultados ---

func TestShowRendersTheStatsTableCostBarsAndTheRetrievalPlayground(t *testing.T) {
	store := &memStore{}
	h := newHarness(t, withStore(store))
	strategies := []string{"structural", "hierarchical", "contextual_retrieval"}
	row := saved(t, store, strategies, []string{"oauth"}, time.Now().UTC(), 0.14)

	p := h.get("/rag/chunking_comparisons/" + itoa(row.ID))

	h.wantStatus(p, 200)
	if got := p.count(`<tr id="stats-`); got != 3 {
		t.Errorf("filas de estadísticas: %d", got)
	}
	if text, _ := p.textOf("stats-structural"); !strings.Contains(text, "Estructural 10 40 79,0 120,5 300 0 0 0 0,01") {
		t.Errorf("fila estructural: %q", text)
	}
	if got := p.count(`<div class="bar-row"`); got != 3 {
		t.Errorf("barras de coste: %d", got)
	}
	if text, _ := p.textOf("cost-contextual_retrieval"); !strings.Contains(text, "0,140000 USD") {
		t.Errorf("coste contextual: %q", text)
	}
	if text, _ := p.textOf("cost-structural"); !strings.Contains(text, "gratis") {
		t.Errorf("coste estructural: %q", text)
	}
	h.wantContains(p, `style="width: 100.0%"`, `style="width: 0.0%"`)
	if text, _ := p.textOf("query-0-hierarchical"); !strings.Contains(text, "padre") || !strings.Contains(text, "hijo de BUD-1::parent") {
		t.Errorf("jerarquía: %q", text)
	}
	if text, _ := p.textOf("query-0-structural"); strings.Contains(text, "padre") || strings.Contains(text, "hijo de") {
		t.Errorf("la estrategia estructural no tiene nivel: %q", text)
	}
	h.wantContains(p, "3.2 s", "18 presupuestos", "coste de ingesta 0,140000 USD", `aria-label="Similitud 71%"`, "<strong>0,710</strong>")
	if got := p.count(`<div id="query-0-`); got != 3 {
		t.Errorf("tarjetas por estrategia: %d", got)
	}
}

func TestShowOfAStatsOnlyRunSaysThereWereNoQueriesAndFreeRunsHaveNoCostBars(t *testing.T) {
	store := &memStore{}
	h := newHarness(t, withStore(store))
	row := saved(t, store, []string{"structural"}, nil, time.Now().UTC(), 0)

	p := h.get("/rag/chunking_comparisons/" + itoa(row.ID))

	h.wantContains(p, `id="lab-no-queries"`, `id="cost-free"`)
	h.wantAbsent(p, `id="lab-playground"`, `id="cost-bars"`)
}

func TestShowOfAnUnknownRunIsA404(t *testing.T) {
	h := newHarness(t)
	for _, path := range []string{"/rag/chunking_comparisons/0", "/rag/chunking_comparisons/999", "/rag/chunking_comparisons/abc"} {
		h.wantStatus(h.get(path), 404)
	}
}

func TestShowSurvivesNothingWhenTheDatabaseIsDownItIsAServerError(t *testing.T) {
	h := newHarness(t, withStore(&memStore{failRead: true}))
	h.wantStatus(h.get("/rag/chunking_comparisons/1"), 500)
}

// --- Historial ---

func TestIndexListsPersistedRunsNewestFirstWithoutCallingTheService(t *testing.T) {
	store := &memStore{}
	h := newHarness(t, withStore(store))
	older := saved(t, store, []string{"structural"}, nil, time.Now().UTC().Add(-48*time.Hour), 0)
	newer := saved(t, store, []string{"semantic"}, []string{"a", "b"}, time.Now().UTC().Add(-24*time.Hour), 0)

	p := h.get("/rag/chunking_comparisons")

	h.wantStatus(p, 200)
	first := strings.Index(p.body, `href="/rag/chunking_comparisons/`+itoa(newer.ID)+`"`)
	second := strings.Index(p.body, `href="/rag/chunking_comparisons/`+itoa(older.ID)+`"`)
	if first < 0 || second < 0 || first > second {
		t.Errorf("orden de enlaces: %d %d", first, second)
	}
	if h.api.count("POST", comparePath) != 0 {
		t.Error("el historial no llama al servicio")
	}
	h.wantContains(p, "Estructural", "Semántico", `<td class="num">2</td>`, "3.2 s", "0,000000 USD")
}

func TestIndexOfAnEmptyHistoryInvitesToCreateTheFirstRun(t *testing.T) {
	h := newHarness(t)
	h.wantContains(h.get("/rag/chunking_comparisons"), `id="lab-history-empty"`)
}

func TestIndexSurvivesAnUnavailableDatabase(t *testing.T) {
	h := newHarness(t, withStore(&memStore{failRead: true}))

	p := h.get("/rag/chunking_comparisons")

	h.wantStatus(p, 200)
	if text, _ := p.textOf("flash-alert"); !strings.Contains(text, "historial no está disponible") {
		t.Errorf("aviso: %q", text)
	}
	h.wantContains(p, `id="lab-history-empty"`)
}
