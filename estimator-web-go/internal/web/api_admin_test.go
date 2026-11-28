package web

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"estimator-web/internal/config"
	"estimator-web/internal/estimatorai"
	"estimator-web/internal/rag"
)

// Pruebas del Bloque 3: API JSON administrativa (Ajustes, indicador del primario y Chunking Lab). La IA es siempre un
// doble HTTP local, el historial es un doble en memoria o la base efímera de Compose, y la decisión administrativa
// del arnés solo existe en pruebas.

const (
	modelsPath  = "/api/v1/config/models"
	settingsAPI = "/api/v1/ai/settings"
	labAPI      = "/api/v1/rag/chunking-comparisons"
)

type restReply struct {
	status int
	header http.Header
	body   []byte
}

func (r restReply) json(t *testing.T) map[string]any {
	t.Helper()
	var decoded map[string]any
	if err := json.Unmarshal(r.body, &decoded); err != nil {
		t.Fatalf("JSON inválido (%d): %s", r.status, r.body)
	}
	return decoded
}

func (r restReply) detail(t *testing.T) string {
	t.Helper()
	text, _ := r.json(t)["detail"].(string)
	return text
}

// rest envía una petición JSON a Go y devuelve la respuesta sin seguir redirecciones.
func (h *harness) rest(method, path, body string, headers ...string) restReply {
	h.t.Helper()
	request, err := http.NewRequest(method, h.app.URL+path, strings.NewReader(body))
	if err != nil {
		h.t.Fatal(err)
	}
	if body != "" {
		request.Header.Set("Content-Type", "application/json")
	}
	for index := 0; index+1 < len(headers); index += 2 {
		request.Header.Set(headers[index], headers[index+1])
	}
	response, err := h.client.Do(request)
	if err != nil {
		h.t.Fatal(err)
	}
	defer response.Body.Close()
	data, _ := io.ReadAll(response.Body)
	return restReply{status: response.StatusCode, header: response.Header, body: data}
}

func (h *harness) wantREST(r restReply, status int) {
	h.t.Helper()
	if r.status != status {
		h.t.Fatalf("estado %d, se esperaba %d: %s", r.status, status, abbreviate(string(r.body)))
	}
}

// --- Ajustes ---

func TestSettingsReadProjectsTheCatalogWithNullsAndProviderFilters(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", modelsPath, 200, configBody(map[string]string{"critic_model": "gpt-4o"}))
	reply := h.rest("GET", settingsAPI, "")
	h.wantREST(reply, 200)
	if reply.header.Get("Content-Type") != "application/json" {
		t.Errorf("tipo: %q", reply.header.Get("Content-Type"))
	}
	body := reply.json(t)
	models := body["models"].(map[string]any)
	if len(models) != 7 {
		t.Fatalf("knobs: %d", len(models))
	}
	critic := models["critic_model"].(map[string]any)
	if critic["effective"] != "gpt-4o" || critic["default"] != "gpt-4o-mini" || critic["overridden"] != true {
		t.Errorf("override: %v", critic)
	}
	fallback := models["fallback_model"].(map[string]any)
	if fallback["effective"] != nil || fallback["default"] != nil || fallback["overridden"] != false {
		t.Errorf("el valor ausente debe viajar como null: %v", fallback)
	}
	fields := body["fields"].([]any)
	if len(fields) != 7 || fields[0].(map[string]any)["key"] != "primary_model" || fields[6].(map[string]any)["key"] != "contextual_chunker_model" {
		t.Fatalf("campos: %v", fields)
	}
	optionsOf := func(key string) []any {
		for _, field := range fields {
			if field.(map[string]any)["key"] == key {
				return field.(map[string]any)["options"].([]any)
			}
		}
		return nil
	}
	for _, option := range optionsOf("propositional_chunker_model") {
		if strings.HasPrefix(option.(string), "claude") {
			t.Errorf("el chunker proposicional ofrece %v", option)
		}
	}
	if got := optionsOf("contextual_chunker_model"); len(got) != 2 || got[0] != "claude-haiku-4-5" {
		t.Errorf("chunker contextual: %v", got)
	}
	if len(optionsOf("primary_model")) != 4 {
		t.Errorf("el primario ofrece todo el catálogo: %v", optionsOf("primary_model"))
	}
	if body["embedding_model"] != "text-embedding-3-small" || !strings.Contains(body["embedding_model_note"].(string), "Solo lectura") {
		t.Errorf("embeddings: %v", body)
	}
}

func TestSettingsWriteSendsEveryKnobAndConvertsEmptyToNull(t *testing.T) {
	h := newHarness(t)
	var sent atomic.Value
	h.api.stub("PUT", modelsPath, func(call apiCall) reply {
		sent.Store(call)
		return jsonReply(configBody(map[string]string{"primary_model": "gpt-4o"}))
	})
	reply := h.rest("PUT", settingsAPI, `{"models":{"primary_model":"gpt-4o","fallback_model":"","critic_model":null,"summary_model":"  ","desconocido":"x"}}`)
	h.wantREST(reply, 200)
	models := jsonBody(t, sent.Load().(apiCall))["models"].(map[string]any)
	want := map[string]any{"primary_model": "gpt-4o", "fallback_model": nil, "critic_model": nil, "summary_model": nil}
	if len(models) != len(want) {
		t.Fatalf("enviado: %v", models)
	}
	for key, value := range want {
		if got, present := models[key]; !present || got != value {
			t.Errorf("%s: %v", key, models[key])
		}
	}
	if reply.json(t)["models"].(map[string]any)["primary_model"].(map[string]any)["effective"] != "gpt-4o" {
		t.Errorf("respuesta: %s", reply.body)
	}
	if h.api.count("PUT", modelsPath) != 1 {
		t.Error("el PUT debe enviarse una sola vez")
	}
}

func TestSettingsWriteWithoutRecognizedFieldsNeverCallsTheService(t *testing.T) {
	h := newHarness(t)
	for _, body := range []string{`{}`, `{"models":{}}`, `{"models":{"desconocido":"x"}}`, `{"models":null}`, `{"models":[]}`, `{"models":{"primary_model":7}}`, `{"models":{"primary_model":["a"]}}`, `[]`} {
		reply := h.rest("PUT", settingsAPI, body)
		h.wantREST(reply, 422)
		if reply.detail(t) == "" {
			t.Errorf("%s sin aviso", body)
		}
	}
	h.wantREST(h.rest("PUT", settingsAPI, `{"models":`), 400)
	if reply := h.rest("PUT", settingsAPI, `{"models":{"primary_model":"x"}}`, "Content-Type", "text/plain"); reply.status != 415 {
		t.Errorf("tipo no admitido: %d", reply.status)
	}
	if got := h.api.count("PUT", modelsPath) + h.api.count("GET", modelsPath); got != 0 {
		t.Errorf("llamadas a IA: %d", got)
	}
}

func TestSettingsErrorsAreSanitizedAndNeverRetried(t *testing.T) {
	cases := []struct {
		name   string
		answer reply
		status int
		want   string // fragmento que debe aparecer
		absent []string
	}{
		{"rechazo con variable conocida", jsonReply(map[string]any{"detail": "El modelo claude-haiku-4-5 requiere ANTHROPIC_API_KEY."}, 422), 422, "ANTHROPIC_API_KEY", nil},
		{"rechazo 400", jsonReply(map[string]any{"detail": "Modelo fuera del catálogo."}, 400), 422, "Modelo fuera del catálogo.", nil},
		{"rechazo con URL interna", jsonReply(map[string]any{"detail": "fallo en http://postgres:5432/ai"}, 422), 422, "La solicitud no es válida", []string{"postgres", "://"}},
		{"rechazo con variable no permitida", jsonReply(map[string]any{"detail": "Falta DATABASE_URL"}, 422), 422, "La solicitud no es válida", []string{"DATABASE_URL"}},
		{"rechazo con detalle de validación", jsonReply(map[string]any{"detail": []any{map[string]any{"loc": []any{"body"}, "msg": "campo"}}}, 422), 422, "La solicitud no es válida", []string{"loc"}},
		{"almacén no disponible", jsonReply(map[string]any{"detail": "Almacén de configuración no disponible."}, 503), 503, "Almacén de configuración no disponible.", nil},
		{"traza en 500", reply{status: 500, body: "Traceback (most recent call last): sk-secreto /app/x.py"}, 502, "no pudo completar", []string{"Traceback", "sk-secreto", "/app"}},
		{"contrato inválido", jsonReply(map[string]any{"models": "texto"}, 200), 502, "respuesta inválida", nil},
		{"no JSON", reply{status: 200, body: "<html>"}, 502, "respuesta inválida", nil},
		{"404 interno", jsonReply(map[string]any{"detail": "no existe"}, 404), 502, "no pudo completar", []string{"no existe"}},
		{"servicio caído", reply{drop: true}, 503, "No se pudo conectar", []string{"127.0.0.1", "http"}},
		{"plazo", reply{status: 200, body: "{}", delay: 400 * time.Millisecond}, 504, "no respondió a tiempo", nil},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			h := newHarness(t, withConfig(func(c *config.Config) {
				c.PublicRegularTotal = 150 * time.Millisecond
				c.PublicRegularHeaders = 150 * time.Millisecond
			}))
			h.api.stubReply("PUT", modelsPath, test.answer)
			h.api.stubReply("GET", modelsPath, test.answer)
			for _, call := range []func() restReply{
				func() restReply { return h.rest("PUT", settingsAPI, `{"models":{"primary_model":"gpt-4o"}}`) },
				func() restReply { return h.rest("GET", settingsAPI, "") },
			} {
				reply := call()
				h.wantREST(reply, test.status)
				text := reply.detail(t)
				if !strings.Contains(text, test.want) {
					t.Errorf("aviso %q sin %q", text, test.want)
				}
				for _, banned := range test.absent {
					if strings.Contains(string(reply.body), banned) {
						t.Errorf("la respuesta expone %q: %s", banned, reply.body)
					}
				}
			}
			if h.api.count("PUT", modelsPath) != 1 || h.api.count("GET", modelsPath) != 1 {
				t.Errorf("reintentos: PUT=%d GET=%d", h.api.count("PUT", modelsPath), h.api.count("GET", modelsPath))
			}
		})
	}
}

func TestSettingsRejectionLeavesTheBadgeCacheUntouched(t *testing.T) {
	h := newHarness(t)
	calls := 0
	h.server.badge = newBadgeCache(15*time.Second, time.Now, func(context.Context) string { calls++; return "gpt-4o-mini" })
	h.server.badge.Get(context.Background())
	h.api.stubJSON("PUT", modelsPath, 422, map[string]any{"detail": "fuera de catálogo"})
	h.wantREST(h.rest("PUT", settingsAPI, `{"models":{"primary_model":"x"}}`), 422)
	h.server.badge.Get(context.Background())
	if calls != 1 {
		t.Errorf("un rechazo no debe invalidar el indicador: %d consultas", calls)
	}
}

func TestSettingsWriteInvalidatesThePrimaryProjection(t *testing.T) {
	h := newHarness(t)
	var current atomic.Value
	current.Store("gpt-4o-mini")
	h.api.stub("GET", modelsPath, func(apiCall) reply {
		return jsonReply(configBody(map[string]string{"primary_model": current.Load().(string)}))
	})
	h.api.stub("PUT", modelsPath, func(apiCall) reply {
		current.Store("gpt-4o")
		return jsonReply(configBody(map[string]string{"primary_model": "gpt-4o"}))
	})
	read := func() any { return h.rest("GET", "/api/v1/ai/primary-model", "").json(t)["model"] }
	if read() != "gpt-4o-mini" || read() != "gpt-4o-mini" {
		t.Fatal("lectura inicial")
	}
	if h.api.count("GET", modelsPath) != 1 {
		t.Errorf("la segunda lectura debe salir de la caché: %d consultas", h.api.count("GET", modelsPath))
	}
	h.wantREST(h.rest("PUT", settingsAPI, `{"models":{"primary_model":"gpt-4o"}}`), 200)
	if got := read(); got != "gpt-4o" {
		t.Errorf("tras guardar se esperaba el modelo nuevo: %v", got)
	}
}

// --- Indicador del modelo primario ---

func TestPrimaryModelProjectionIsPublicAndOmitsTheCatalog(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", modelsPath, 200, configBody(nil))
	h.server.adminDecision = nil // composición normal: la administración está denegada
	reply := h.rest("GET", "/api/v1/ai/primary-model", "")
	h.wantREST(reply, 200)
	if string(reply.body) != "{\"model\":\"gpt-4o-mini\"}\n" {
		t.Errorf("cuerpo: %q", reply.body)
	}
	for _, leaked := range []string{"available_models", "fallback", "embedding", "critic"} {
		if strings.Contains(string(reply.body), leaked) {
			t.Errorf("la proyección expone %q", leaked)
		}
	}
	h.wantREST(h.rest("GET", settingsAPI, ""), 403)
}

func TestPrimaryModelCachesAbsenceAndFailureForFifteenSeconds(t *testing.T) {
	for name, answer := range map[string]reply{
		"servicio caído": {drop: true},
		"error 500":      {status: 500, body: "{}"},
		"sin primario":   jsonReply(map[string]any{"models": map[string]any{"fallback_model": map[string]any{"effective": nil}}}),
	} {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t)
			now := time.Now()
			h.server.badge = newBadgeCache(15*time.Second, func() time.Time { return now }, h.server.badge.fetch)
			h.api.stubReply("GET", modelsPath, answer)
			for range 3 {
				reply := h.rest("GET", "/api/v1/ai/primary-model", "")
				h.wantREST(reply, 200)
				if got := reply.json(t); got["model"] != nil || len(got) != 1 {
					t.Fatalf("se esperaba model=null: %s", reply.body)
				}
			}
			if h.api.count("GET", modelsPath) != 1 {
				t.Errorf("la ausencia debe cachearse: %d consultas", h.api.count("GET", modelsPath))
			}
			now = now.Add(15 * time.Second)
			h.rest("GET", "/api/v1/ai/primary-model", "")
			if h.api.count("GET", modelsPath) != 2 {
				t.Errorf("tras 15 s debe consultar de nuevo: %d", h.api.count("GET", modelsPath))
			}
		})
	}
}

func TestPrimaryModelUsesTheShortConfigurableDeadline(t *testing.T) {
	h := newHarness(t, withConfig(func(c *config.Config) { c.BadgeTimeout = 100 * time.Millisecond }))
	h.api.stubReply("GET", modelsPath, reply{status: 200, body: "{}", delay: 600 * time.Millisecond})
	started := time.Now()
	reply := h.rest("GET", "/api/v1/ai/primary-model", "")
	h.wantREST(reply, 200)
	if reply.json(t)["model"] != nil || time.Since(started) > 450*time.Millisecond {
		t.Errorf("el indicador debe omitirse dentro del plazo corto (%v): %s", time.Since(started), reply.body)
	}
}

// El reloj y la consulta se controlan con barreras: ninguna prueba de la caché depende de pausas reales.
type gatedFetch struct {
	mu      sync.Mutex
	calls   int
	entered chan int
	release []chan string
}

func newGatedFetch(gates int) *gatedFetch {
	g := &gatedFetch{entered: make(chan int, 16)}
	for range gates {
		g.release = append(g.release, make(chan string, 1))
	}
	return g
}

func (g *gatedFetch) fetch(ctx context.Context) string {
	g.mu.Lock()
	g.calls++
	n := g.calls
	g.mu.Unlock()
	if ctx.Err() != nil {
		return "contexto-cancelado"
	}
	g.entered <- n
	return <-g.release[n-1]
}

func (g *gatedFetch) count() int {
	g.mu.Lock()
	defer g.mu.Unlock()
	return g.calls
}

func TestBadgeCacheSharesOneFetchBetweenConcurrentReaders(t *testing.T) {
	gate := newGatedFetch(2)
	cache := newBadgeCache(15*time.Second, func() time.Time { return time.Unix(1000, 0) }, gate.fetch)
	results := make(chan string, 8)
	for range 8 {
		go func() { results <- cache.Get(context.Background()) }()
	}
	<-gate.entered // una consulta en vuelo; las demás lecturas esperan o leerán la caché
	gate.release[0] <- "gpt-4o"
	for range 8 {
		if got := <-results; got != "gpt-4o" {
			t.Fatalf("lector con %q", got)
		}
	}
	if gate.count() != 1 {
		t.Fatalf("consultas: %d", gate.count())
	}
}

func TestBadgeCacheInvalidationDiscardsTheInflightValue(t *testing.T) {
	gate := newGatedFetch(2)
	cache := newBadgeCache(15*time.Second, func() time.Time { return time.Unix(1000, 0) }, gate.fetch)
	first := make(chan string, 1)
	go func() { first <- cache.Get(context.Background()) }()
	<-gate.entered // consulta 1 en vuelo

	cache.Invalidate() // se guarda un cambio mientras tanto
	second := make(chan string, 1)
	go func() { second <- cache.Get(context.Background()) }()
	if n := <-gate.entered; n != 2 {
		t.Fatalf("la lectura posterior a Invalidate debe lanzar su propia consulta, lanzó %d", n)
	}
	gate.release[1] <- "nuevo"
	if got := <-second; got != "nuevo" {
		t.Fatalf("lectura posterior: %q", got)
	}
	gate.release[0] <- "viejo" // la consulta anterior termina tarde
	if got := <-first; got != "viejo" {
		t.Fatalf("el lector original recibe su valor: %q", got)
	}
	if got := cache.Get(context.Background()); got != "nuevo" {
		t.Fatalf("la consulta anterior no debe sobrescribir la caché: %q", got)
	}
	if gate.count() != 2 {
		t.Fatalf("consultas: %d", gate.count())
	}
}

func TestBadgeCacheDoesNotStoreAnInflightValueAfterInvalidation(t *testing.T) {
	gate := newGatedFetch(2)
	cache := newBadgeCache(15*time.Second, func() time.Time { return time.Unix(1000, 0) }, gate.fetch)
	done := make(chan string, 1)
	go func() { done <- cache.Get(context.Background()) }()
	<-gate.entered
	cache.Invalidate()
	gate.release[0] <- "viejo"
	if got := <-done; got != "viejo" {
		t.Fatalf("lector: %q", got)
	}
	next := make(chan string, 1)
	go func() { next <- cache.Get(context.Background()) }()
	<-gate.entered
	gate.release[1] <- "nuevo"
	if got := <-next; got != "nuevo" {
		t.Fatalf("se esperaba una consulta nueva y no el valor invalidado: %q", got)
	}
}

func TestBadgeCacheExpiresAfterTheTTLAndKeepsAbsenceUntilThen(t *testing.T) {
	now := time.Unix(1000, 0)
	var calls int
	values := []string{"", "gpt-4o"}
	cache := newBadgeCache(15*time.Second, func() time.Time { return now }, func(context.Context) string {
		defer func() { calls++ }()
		return values[min(calls, 1)]
	})
	for _, offset := range []time.Duration{0, 5 * time.Second, 14999 * time.Millisecond} {
		now = time.Unix(1000, 0).Add(offset)
		if cache.Get(context.Background()) != "" {
			t.Fatal("la ausencia se conserva dentro del TTL")
		}
	}
	if calls != 1 {
		t.Fatalf("consultas: %d", calls)
	}
	now = time.Unix(1000, 0).Add(15 * time.Second)
	if got := cache.Get(context.Background()); got != "gpt-4o" || calls != 2 {
		t.Fatalf("tras el TTL: %q (%d consultas)", got, calls)
	}
}

func TestBadgeCacheFetchIgnoresTheCallerCancellationAndWaitersCanLeave(t *testing.T) {
	gate := newGatedFetch(1)
	cache := newBadgeCache(15*time.Second, func() time.Time { return time.Unix(1000, 0) }, gate.fetch)
	canceled, cancel := context.WithCancel(context.Background())
	cancel()
	first := make(chan string, 1)
	go func() { first <- cache.Get(canceled) }()
	<-gate.entered // la consulta recibe un contexto desligado: no queda cacheada una ausencia falsa

	waiter, stop := context.WithCancel(context.Background())
	stop()
	if got := cache.Get(waiter); got != "" {
		t.Fatalf("un lector cancelado no espera: %q", got)
	}
	gate.release[0] <- "gpt-4o"
	if got := <-first; got != "gpt-4o" {
		t.Fatalf("lector original: %q", got)
	}
	if got := cache.Get(context.Background()); got != "gpt-4o" || gate.count() != 1 {
		t.Fatalf("caché: %q (%d consultas)", got, gate.count())
	}
}

// --- Chunking Lab: opciones ---

func TestLabOptionsExposeTheCatalogDefaultsAndLimits(t *testing.T) {
	h := newHarness(t)
	reply := h.rest("GET", labAPI+"/options", "")
	h.wantREST(reply, 200)
	body := reply.json(t)
	strategies := body["strategies"].([]any)
	if len(strategies) != 8 {
		t.Fatalf("estrategias: %d", len(strategies))
	}
	checked := []string{}
	byName := map[string]map[string]any{}
	for _, item := range strategies {
		entry := item.(map[string]any)
		byName[entry["name"].(string)] = entry
		if entry["default_checked"] == true {
			checked = append(checked, entry["name"].(string))
		}
		for _, key := range []string{"name", "label", "description", "cost_tier", "cost_label", "key_name", "default_checked"} {
			if _, ok := entry[key]; !ok {
				t.Errorf("%v sin %s", entry["name"], key)
			}
		}
	}
	if strings.Join(checked, ",") != "structural,fixed_size,recursive" {
		t.Errorf("marcadas: %v", checked)
	}
	if byName["structural"]["key_name"] != nil || byName["structural"]["cost_tier"] != "free" {
		t.Errorf("gratuita: %v", byName["structural"])
	}
	if byName["contextual_retrieval"]["key_name"] != "ANTHROPIC_API_KEY" || byName["propositional"]["key_name"] != "OPENAI_API_KEY" ||
		byName["semantic"]["cost_label"] != "de pago (embeddings)" {
		t.Errorf("de pago: %v", byName)
	}
	limits := body["top_k"].(map[string]any)
	if limits["default"] != float64(3) || limits["min"] != float64(1) || limits["max"] != float64(10) {
		t.Errorf("top_k: %v", limits)
	}
	if body["compare_timeout_seconds"] != float64(10) || len(body["sample_queries"].([]any)) == 0 {
		t.Errorf("plazo o consultas: %v", body)
	}
	if h.api.count("POST", comparePath) != 0 {
		t.Error("las opciones no llaman a IA")
	}
}

// --- Chunking Lab: comparación ---

func (h *harness) stubCompareRaw(strategies, queries []string) {
	h.api.stubJSON("POST", comparePath, 200, compareBody(strategies, queries, 0.14))
}

func compareRequest(h *harness) map[string]any {
	h.t.Helper()
	calls := h.api.requests("POST", comparePath)
	if len(calls) == 0 {
		h.t.Fatal("IA no recibió la comparación")
	}
	return jsonBody(h.t, calls[len(calls)-1])
}

func TestLabCreateNormalizesTopKPerDA28(t *testing.T) {
	valid := []struct {
		raw  string // fragmento JSON de top_k (vacío = omitido)
		want float64
	}{
		{"", 3}, {`"top_k":1`, 1}, {`"top_k":3`, 3}, {`"top_k":10`, 10}, {`"top_k":7`, 7}, {`"top_k":0`, 1}, {`"top_k":-0`, 1}, {`"top_k":-4`, 1},
		{`"top_k":11`, 10}, {`"top_k":250`, 10}, {`"top_k":99999999999999999999999`, 10}, {`"top_k":-99999999999999999999999`, 1},
	}
	for _, test := range valid {
		t.Run("válido "+test.raw, func(t *testing.T) {
			h := newHarness(t)
			h.stubCompareRaw([]string{"structural"}, nil)
			body := `{"strategies":["structural"]`
			if test.raw != "" {
				body += "," + test.raw
			}
			reply := h.rest("POST", labAPI, body+"}")
			h.wantREST(reply, 201)
			if got := compareRequest(h)["top_k"]; got != test.want {
				t.Errorf("a IA llegó %v, se esperaba %v", got, test.want)
			}
			if got := reply.json(t)["top_k"]; got != test.want {
				t.Errorf("guardado %v", got)
			}
		})
	}
	for _, raw := range []string{`1.0`, `3.5`, `1e1`, `1E1`, `5e-1`, `"5"`, `""`, `true`, `false`, `null`, `[]`, `{}`, `[3]`} {
		t.Run("inválido "+raw, func(t *testing.T) {
			h := newHarness(t)
			h.stubCompareRaw([]string{"structural"}, nil)
			reply := h.rest("POST", labAPI, `{"strategies":["structural"],"top_k":`+raw+`}`)
			h.wantREST(reply, 422)
			if h.api.count("POST", comparePath) != 0 || len(h.store.(*memStore).rows) != 0 {
				t.Error("un top_k inválido no debe llamar a IA ni guardar")
			}
		})
	}
}

func TestLabCreateFiltersStrategiesAndNormalizesQueriesWithoutArbitraryLimits(t *testing.T) {
	h := newHarness(t)
	h.stubCompareRaw([]string{"structural", "recursive"}, []string{"a"})
	huge := strings.Repeat("ñ", 20000)
	many := []string{}
	for index := range 1500 {
		many = append(many, fmt.Sprintf("consulta %d", index))
	}
	manyJSON, _ := json.Marshal(many)
	body := fmt.Sprintf(`{"strategies":["recursive","inexistente","structural","recursive",""],"queries":%s,"custom_queries":%q}`,
		manyJSON, "  propia 1 \n\nconsulta 3\r\n"+huge+"\n  propia 1")
	h.wantREST(h.rest("POST", labAPI, body), 201)
	sent := compareRequest(h)
	if got := fmt.Sprint(sent["strategies"]); got != "[recursive structural]" {
		t.Errorf("estrategias: %s", got)
	}
	queries := sent["queries"].([]any)
	if len(queries) != 1500+1+1 { // 1500 marcadas + «propia 1» + consulta larga; «consulta 3» ya estaba
		t.Fatalf("consultas: %d", len(queries))
	}
	if queries[0] != "consulta 0" || queries[1500] != "propia 1" || queries[1501] != huge {
		t.Errorf("orden o contenido alterados: %v … %.20v", queries[1500], queries[1501])
	}
	if sent["top_k"] != float64(3) {
		t.Errorf("top_k: %v", sent["top_k"])
	}
	corpus := sent["budgets"].([]any)
	if len(corpus) == 0 {
		t.Error("el corpus lo determina Go")
	}
}

func TestLabCreateRejectsEmptySelectionAndBadShapesBeforeCallingAI(t *testing.T) {
	h := newHarness(t)
	for _, body := range []string{
		`{}`, `{"strategies":[]}`, `{"strategies":["inexistente"]}`, `{"strategies":null}`, `{"strategies":"structural"}`,
		`{"strategies":[1]}`, `{"strategies":["structural"],"queries":"a"}`, `{"strategies":["structural"],"queries":null}`,
		`{"strategies":["structural"],"custom_queries":7}`, `[]`, `"x"`,
	} {
		reply := h.rest("POST", labAPI, body)
		h.wantREST(reply, 422)
	}
	if reply := h.rest("POST", labAPI, `{"strategies":[]}`); reply.detail(t) != "Selecciona al menos una estrategia." {
		t.Errorf("aviso: %q", reply.detail(t))
	}
	h.wantREST(h.rest("POST", labAPI, `{"strategies":`), 400)
	if h.api.count("POST", comparePath) != 0 {
		t.Error("IA no debe recibir llamadas")
	}
}

func TestLabCreateSavesAndReturnsDecimalIDLocationAndOrderedResult(t *testing.T) {
	h := newHarness(t)
	h.stubCompareRaw([]string{"hierarchical", "structural"}, []string{"oauth"})
	reply := h.rest("POST", labAPI, `{"strategies":["hierarchical","structural"],"queries":["oauth"],"top_k":2}`)
	h.wantREST(reply, 201)
	body := reply.json(t)
	if body["id"] != "1" || reply.header.Get("Location") != labAPI+"/1" {
		t.Errorf("id/Location: %v %q", body["id"], reply.header.Get("Location"))
	}
	if !strings.Contains(string(reply.body), `"id":"1"`) {
		t.Errorf("el ID debe serializarse como cadena: %s", reply.body)
	}
	if body["warning"] != nil || body["created_at"] == nil || body["corpus_label"] != estimatorai.CorpusLabel || body["top_k"] != float64(2) {
		t.Errorf("metadatos: %v", body)
	}
	if _, err := time.Parse(time.RFC3339Nano, body["created_at"].(string)); err != nil {
		t.Errorf("created_at: %v", err)
	}
	result := body["result"].(map[string]any)
	stats := result["stats_per_strategy"].([]any)
	if len(stats) != 2 || stats[0].(map[string]any)["strategy"] != "structural" || stats[1].(map[string]any)["strategy"] != "hierarchical" {
		t.Fatalf("orden canónico del catálogo: %v", stats)
	}
	first := stats[0].(map[string]any)
	distribution := first["token_distribution"].(map[string]any)
	for _, key := range []string{"n_chunks", "n_orphan_chunks", "n_obese_chunks", "ingestion_cost_usd", "extra_api_calls", "ingestion_seconds"} {
		if _, ok := first[key]; !ok {
			t.Errorf("estadística sin %s", key)
		}
	}
	if distribution["p95"] != 120.5 || distribution["max"] != float64(300) {
		t.Errorf("distribución: %v", distribution)
	}
	queries := result["queries_per_strategy"].([]any)
	if len(queries) != 2 {
		t.Fatalf("consultas por estrategia: %v", queries)
	}
	plain := queries[0].(map[string]any)["top_k"].([]any)[0].(map[string]any)
	if plain["level"] != nil || plain["parent_chunk_id"] != nil || plain["chunk_id"] != "BUD-1::AUTH-1" {
		t.Errorf("chunk sin jerarquía: %v", plain)
	}
	tree := queries[1].(map[string]any)["top_k"].([]any)
	child := tree[1].(map[string]any)
	if tree[0].(map[string]any)["level"] != "parent" || child["level"] != "child" || child["parent_chunk_id"] != "BUD-1::parent" {
		t.Errorf("jerarquía: %v", tree)
	}
	if body["total_ingestion_cost_usd"] != float64(0) || h.api.count("POST", comparePath) != 1 || len(h.store.(*memStore).rows) != 1 {
		t.Errorf("coste/llamadas/filas: %v %d %d", body["total_ingestion_cost_usd"], h.api.count("POST", comparePath), len(h.store.(*memStore).rows))
	}
}

func TestLabCreateWithSaveFailureReturnsTheResultWithNullIDAndWarning(t *testing.T) {
	for name, store := range map[string]rag.Store{"escritura caída": &memStore{failWrite: true}, "sin base de datos": nil} {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t, withStore(store))
			if store == nil {
				h.server.store = nil
			}
			h.stubCompareRaw([]string{"structural"}, nil)
			reply := h.rest("POST", labAPI, `{"strategies":["structural"]}`)
			h.wantREST(reply, 200)
			body := reply.json(t)
			if body["id"] != nil || body["created_at"] != nil || reply.header.Get("Location") != "" {
				t.Errorf("sin guardar: id=%v created_at=%v Location=%q", body["id"], body["created_at"], reply.header.Get("Location"))
			}
			if body["warning"] != "La comparación se calculó, pero no se pudo guardar en el historial." {
				t.Errorf("aviso: %v", body["warning"])
			}
			if len(body["result"].(map[string]any)["stats_per_strategy"].([]any)) != 1 {
				t.Error("el resultado calculado debe conservarse")
			}
			if h.api.count("POST", comparePath) != 1 {
				t.Error("no se reintenta la comparación")
			}
		})
	}
}

func TestLabCreateMapsEveryAIErrorWithoutRetries(t *testing.T) {
	cases := []struct {
		name   string
		answer reply
		status int
		want   string
		absent []string
	}{
		{"400 de IA", jsonReply(map[string]any{"detail": "Estrategia no soportada"}, 400), 422, "Petición inválida: Estrategia no soportada", nil},
		{"422 de IA", jsonReply(map[string]any{"detail": []any{map[string]any{"msg": "x"}}}, 422), 422, "La solicitud no es válida", []string{`"msg"`}},
		{"clave de Anthropic", jsonReply(map[string]any{"detail": "Falta ANTHROPIC_API_KEY para contextual_retrieval."}, 503), 503, "ANTHROPIC_API_KEY", nil},
		{"clave de OpenAI", jsonReply(map[string]any{"detail": "Falta OPENAI_API_KEY."}, 503), 503, "OPENAI_API_KEY", nil},
		{"503 con variable interna", jsonReply(map[string]any{"detail": "Falta REDIS_URL en redis://cache:6379"}, 503), 503, "no puede ejecutar esa comparación", []string{"REDIS_URL", "redis://"}},
		{"500 con traza", reply{status: 500, body: "Traceback sk-clave-secreta"}, 502, "no pudo completar", []string{"Traceback", "sk-clave"}},
		{"contrato inválido", jsonReply(map[string]any{"otro": 1}, 200), 502, "respuesta inválida", nil},
		{"servicio caído", reply{drop: true}, 503, "No se pudo conectar", []string{"127.0.0.1"}},
		{"plazo", reply{status: 200, body: "{}", delay: 500 * time.Millisecond}, 504, "prueba con menos estrategias", nil},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			h := newHarness(t, withConfig(func(c *config.Config) { c.CompareTimeout = 200 * time.Millisecond }))
			h.api.stubReply("POST", comparePath, test.answer)
			reply := h.rest("POST", labAPI, `{"strategies":["structural","semantic"]}`)
			h.wantREST(reply, test.status)
			if !strings.Contains(reply.detail(t), test.want) {
				t.Errorf("aviso %q sin %q", reply.detail(t), test.want)
			}
			for _, banned := range test.absent {
				if strings.Contains(string(reply.body), banned) {
					t.Errorf("expone %q: %s", banned, reply.body)
				}
			}
			if h.api.count("POST", comparePath) != 1 || len(h.store.(*memStore).rows) != 0 {
				t.Errorf("POST=%d filas=%d", h.api.count("POST", comparePath), len(h.store.(*memStore).rows))
			}
		})
	}
}

func TestLabTimeoutDoesNotWidenTheOtherOperations(t *testing.T) {
	h := newHarness(t, withConfig(func(c *config.Config) {
		c.CompareTimeout = 600 * time.Millisecond
		c.PublicRegularTotal = 100 * time.Millisecond
		c.PublicRegularHeaders = 100 * time.Millisecond
	}))
	h.api.stub("POST", comparePath, func(apiCall) reply {
		answer := jsonReply(compareBody([]string{"structural"}, nil, 0))
		answer.delay = 300 * time.Millisecond // supera el plazo habitual y cabe en el del Lab
		return answer
	})
	h.api.stubReply("GET", modelsPath, reply{status: 200, body: "{}", delay: 300 * time.Millisecond})
	h.wantREST(h.rest("POST", labAPI, `{"strategies":["structural"]}`), 201)
	h.wantREST(h.rest("GET", settingsAPI, ""), 504)
}

// La cancelación del navegador llega hasta IA, no persiste nada y no reintenta. Las barreras no usan pausas.
func cancelDuringCompare(t *testing.T, store rag.Store) int32 {
	t.Helper()
	arrived := make(chan struct{})
	observed := make(chan struct{})
	var posts atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		posts.Add(1)
		_, _ = io.Copy(io.Discard, r.Body)
		close(arrived)
		<-r.Context().Done()
		close(observed)
	}))
	defer upstream.Close()
	server, err := New(config.Config{APIURL: upstream.URL, CompareTimeout: 30 * time.Second}, store, nil)
	if err != nil {
		t.Fatal(err)
	}
	server.adminDecision = func(context.Context, administrativeOperation) (bool, error) { return true, nil }
	app := httptest.NewServer(server.Handler())
	defer app.Close()

	ctx, cancel := context.WithCancel(context.Background())
	request, _ := http.NewRequestWithContext(ctx, "POST", app.URL+labAPI, strings.NewReader(`{"strategies":["structural"]}`))
	request.Header.Set("Content-Type", "application/json")
	failed := make(chan error, 1)
	go func() {
		response, err := http.DefaultClient.Do(request)
		if err == nil {
			response.Body.Close()
		}
		failed <- err
	}()
	<-arrived
	cancel()
	if err := <-failed; err == nil {
		t.Fatal("el cliente cancelado no debe recibir respuesta")
	}
	select {
	case <-observed:
	case <-time.After(5 * time.Second):
		t.Fatal("IA no observó el cierre de la solicitud")
	}
	return posts.Load()
}

func TestLabCreateCancellationReachesTheAIAndPersistsNothing(t *testing.T) {
	store := &memStore{}
	if posts := cancelDuringCompare(t, store); posts != 1 || len(store.rows) != 0 {
		t.Errorf("POST=%d filas=%d", posts, len(store.rows))
	}
}

// --- Chunking Lab: historial y detalle ---

func TestLabListReturnsTheTwentyNewestWithoutCallingAI(t *testing.T) {
	store := &memStore{}
	h := newHarness(t, withStore(store))
	base := time.Date(2026, 10, 5, 10, 0, 0, 0, time.UTC)
	for index := range 25 {
		saved(t, store, []string{"structural"}, []string{"q"}, base.Add(time.Duration(index)*time.Minute), 0)
	}
	reply := h.rest("GET", labAPI, "")
	h.wantREST(reply, 200)
	body := reply.json(t)
	items := body["items"].([]any)
	if len(items) != 20 || body["warning"] != nil {
		t.Fatalf("elementos=%d aviso=%v", len(items), body["warning"])
	}
	if items[0].(map[string]any)["id"] != "25" || items[19].(map[string]any)["id"] != "6" {
		t.Errorf("orden: %v … %v", items[0].(map[string]any)["id"], items[19].(map[string]any)["id"])
	}
	first := items[0].(map[string]any)
	for _, key := range []string{"strategies", "queries", "top_k", "corpus_label", "corpus_count", "duration_ms", "created_at", "total_ingestion_cost_usd"} {
		if _, ok := first[key]; !ok {
			t.Errorf("resumen sin %s", key)
		}
	}
	if _, heavy := first["result"]; heavy {
		t.Error("el listado no incluye el resultado")
	}
	if len(h.api.calls) != 0 {
		t.Errorf("llamadas a IA: %d", len(h.api.calls))
	}
}

func TestLabListWithUnavailableHistoryIsEmptyWithAWarning(t *testing.T) {
	for name, store := range map[string]rag.Store{"lectura caída": &memStore{failRead: true}, "sin base de datos": nil} {
		t.Run(name, func(t *testing.T) {
			h := newHarness(t, withStore(store))
			if store == nil {
				h.server.store = nil
			}
			reply := h.rest("GET", labAPI, "")
			h.wantREST(reply, 200)
			body := reply.json(t)
			if len(body["items"].([]any)) != 0 || body["warning"] != "El historial no está disponible en este momento." {
				t.Errorf("cuerpo: %s", reply.body)
			}
			if !strings.Contains(string(reply.body), `"items":[]`) {
				t.Errorf("la lista vacía debe ser []: %s", reply.body)
			}
			if len(h.api.calls) != 0 {
				t.Error("sin llamadas a IA")
			}
		})
	}
}

func TestLabDetailReturnsTheStoredRunAndMapsTheFailures(t *testing.T) {
	store := &memStore{}
	h := newHarness(t, withStore(store))
	row := saved(t, store, []string{"structural", "hierarchical"}, []string{"oauth"}, time.Date(2026, 10, 5, 10, 0, 0, 0, time.UTC), 0.5)
	reply := h.rest("GET", labAPI+"/1", "")
	h.wantREST(reply, 200)
	body := reply.json(t)
	if body["id"] != "1" || body["corpus_count"] != float64(18) || body["duration_ms"] != float64(3200) || body["created_at"] != "2026-10-05T10:00:00Z" || body["warning"] != nil {
		t.Errorf("detalle: %v", body)
	}
	if len(body["result"].(map[string]any)["queries_per_strategy"].([]any)) != 2 || row.ID != 1 {
		t.Errorf("resultado: %v", body["result"])
	}
	for _, id := range []string{"999", "abc", "-1", "+1", "007", "1.5", "9223372036854775808", "99999999999999999999", "0x1"} {
		reply := h.rest("GET", labAPI+"/"+id, "")
		h.wantREST(reply, 404)
		if reply.detail(t) != "No se encontró la comparación solicitada." {
			t.Errorf("%s: %s", id, reply.body)
		}
	}
	store.failRead = true
	reply = h.rest("GET", labAPI+"/1", "")
	h.wantREST(reply, 500)
	if strings.Contains(string(reply.body), "db down") || reply.detail(t) != "El historial no está disponible en este momento." {
		t.Errorf("fallo del repositorio: %s", reply.body)
	}
	if len(h.api.calls) != 0 {
		t.Error("el detalle no llama a IA")
	}
}

// --- Frontera ---

func TestAdminMutationsRejectCrossOriginBeforeAnyEffect(t *testing.T) {
	h := newHarness(t)
	for _, call := range []struct{ method, path, body string }{
		{"PUT", settingsAPI, `{"models":{"primary_model":"gpt-4o"}}`}, {"POST", labAPI, `{"strategies":["structural"]}`},
	} {
		for _, origin := range []string{"https://otro.example", "null"} {
			h.wantREST(h.rest(call.method, call.path, call.body, "Origin", origin), 403)
		}
	}
	if len(h.api.calls) != 0 || len(h.store.(*memStore).rows) != 0 {
		t.Error("el origen rechazado no debe llegar a IA ni al historial")
	}
}

func TestAdminRoutesRejectUnsupportedMethodsAndUnknownSubpaths(t *testing.T) {
	h := newHarness(t)
	for _, call := range []struct {
		method, path string
		status       int
	}{
		{"DELETE", settingsAPI, 405}, {"POST", settingsAPI, 405}, {"PATCH", settingsAPI, 405},
		{"POST", "/api/v1/ai/primary-model", 405}, {"PUT", labAPI, 405}, {"POST", labAPI + "/options", 405},
		{"DELETE", labAPI + "/1", 405}, {"GET", labAPI + "/1/extra", 404}, {"GET", "/api/v1/ai/otra", 404},
	} {
		if reply := h.rest(call.method, call.path, ""); reply.status != call.status {
			t.Errorf("%s %s: %d", call.method, call.path, reply.status)
		}
	}
}

func TestSettingsRejectionIsPrefixedOnlyOnWriteAndKeepsTheAtomicRequestWhole(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("PUT", modelsPath, 422, map[string]any{"detail": "El modelo modelo-x no está en el catálogo."})
	reply := h.rest("PUT", settingsAPI, `{"models":{"primary_model":"gpt-4o","critic_model":"modelo-x"}}`)
	h.wantREST(reply, 422)
	if reply.detail(t) != "Cambio rechazado: El modelo modelo-x no está en el catálogo." {
		t.Errorf("aviso: %q", reply.detail(t))
	}
	calls := h.api.requests("PUT", modelsPath)
	if len(calls) != 1 || len(jsonBody(t, calls[0])["models"].(map[string]any)) != 2 {
		t.Errorf("Go envía una única solicitud con ambos campos y deja la atomicidad a IA: %d", len(calls))
	}
}
