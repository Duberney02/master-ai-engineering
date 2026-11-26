package web

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"estimator-web/internal/config"
)

func jsonMarshal(value any) ([]byte, error) { return json.Marshal(value) }

func itoa(value int64) string { return strconv.FormatInt(value, 10) }

func mustURL(raw string) *url.URL {
	parsed, err := url.Parse(raw)
	if err != nil {
		panic(err)
	}
	return parsed
}

func toStrings(value any) []string {
	items, _ := value.([]any)
	out := make([]string, len(items))
	for index, item := range items {
		out[index], _ = item.(string)
	}
	return out
}

// Pruebas de la frontera tras la retirada del cliente HTML (tareas 10.1 y 10.2): sonda, rutas retiradas, cookie legada,
// recuperación, registro saneado y wrappers HTTP que no ocultan las capacidades del escritor real.

// retiredRoutes son las rutas del inventario HTML de Go (design.md, «Inventario de retirada del HTML Go»).
var retiredRoutes = []struct{ method, path string }{
	{"GET", "/"}, {"GET", "/estimations/new"}, {"GET", "/estimations"}, {"POST", "/estimations"}, {"GET", "/estimations/1"},
	{"POST", "/conversation"}, {"GET", "/ai_settings"}, {"PATCH", "/ai_settings"}, {"PUT", "/ai_settings"}, {"POST", "/ai_settings"},
	{"GET", "/rag/chunking_comparisons"}, {"POST", "/rag/chunking_comparisons"}, {"GET", "/rag/chunking_comparisons/new"},
	{"GET", "/rag/chunking_comparisons/1"}, {"GET", "/robots.txt"}, {"GET", "/404.html"}, {"GET", "/422.html"}, {"GET", "/500.html"},
	{"GET", "/nada"}, {"DELETE", "/estimations"}, {"POST", "/up"},
}

func TestTheHealthProbeAnswers200WithoutCallingAnyone(t *testing.T) {
	h := newHarness(t)

	for _, method := range []string{"GET", "HEAD"} {
		r := h.rest(method, "/up", "")
		h.wantREST(r, 200)
		if got := r.header.Get("Content-Type"); !strings.HasPrefix(got, "text/plain") {
			t.Errorf("%s /up: tipo %q", method, got)
		}
		if strings.Contains(strings.ToLower(string(r.body)), "<html") {
			t.Errorf("%s /up responde HTML: %s", method, r.body)
		}
	}
	if len(h.api.calls) != 0 {
		t.Errorf("la sonda de salud no debe llamar a la API (%d llamadas)", len(h.api.calls))
	}
}

// 10.1: ninguna ruta, formulario o estático del cliente HTML responde ya, con o sin cookie legada, y nada llega a IA
// ni al repositorio.
func TestRetiredHTMLRoutesAnswerJSON404WithoutEffects(t *testing.T) {
	h := newHarness(t, withStore(forbiddenStore{}))
	for _, route := range retiredRoutes {
		body := ""
		headers := []string{"Origin", h.app.URL, "Cookie", legacyCookieName + "=valor"}
		if route.method != "GET" {
			headers = append(headers, "Content-Type", "application/x-www-form-urlencoded")
			body = "_method=patch&authenticity_token=x"
		}
		r := h.rest(route.method, route.path, body, headers...)
		if r.status != 404 {
			t.Errorf("%s %s: %d %s", route.method, route.path, r.status, abbreviate(string(r.body)))
			continue
		}
		if got := r.header.Get("Content-Type"); got != "application/json" {
			t.Errorf("%s %s: tipo %q", route.method, route.path, got)
		}
		if strings.Contains(string(r.body), "<") {
			t.Errorf("%s %s: cuerpo con marcado: %s", route.method, route.path, r.body)
		}
	}
	if len(h.api.calls) != 0 {
		t.Errorf("las rutas retiradas llamaron a IA: %d", len(h.api.calls))
	}
}

// Una mutación cruzada hacia una ruta retirada se rechaza por origen antes de enrutar: la validación de origen
// ESTIMATOR_PUBLIC_ORIGIN se conserva para toda mutación.
func TestMutationsStillRejectForeignOriginOnRetiredAndLiveRoutes(t *testing.T) {
	h := newHarness(t, withConfig(func(c *config.Config) { c.PublicOrigin = "https://estimador.example" }))
	paths := []string{"/estimations", "/ai_settings", "/api/v1/sessions", "/rag/chunking_comparisons"}
	for _, path := range paths {
		for _, origin := range []string{"null", "https://otro.example"} {
			if r := h.rest("POST", path, "", "Origin", origin); r.status != 403 {
				t.Errorf("POST %s con Origin %s: %d", path, origin, r.status)
			}
		}
	}
	if len(h.api.calls) != 0 {
		t.Errorf("llamadas a IA tras orígenes rechazados: %d", len(h.api.calls))
	}
	for _, path := range paths {
		if r := h.rest("POST", path, "", "Origin", "https://estimador.example"); r.status == 403 {
			t.Errorf("POST %s con el origen configurado no debe rechazarse por origen", path)
		}
	}
}

// Cookie legada: nunca se emite; si el navegador la envía se expira en el ámbito original, en cualquier respuesta.
func TestLegacySessionCookieIsNeverIssuedAndIsExpiredWhenSent(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations", 200, []any{})
	for _, path := range []string{"/", "/up", "/api/v1/estimations?limit=1", "/api/v1/ai/primary-model"} {
		if r := h.rest("GET", path, ""); len(r.header.Values("Set-Cookie")) != 0 {
			t.Errorf("%s emite cookies sin que el navegador envíe la legada: %v", path, r.header.Values("Set-Cookie"))
		}
		r := h.rest("GET", path, "", "Cookie", legacyCookieName+"=firmada")
		cookies := r.header.Values("Set-Cookie")
		if len(cookies) != 1 || !strings.HasPrefix(cookies[0], legacyCookieName+"=;") || !strings.Contains(cookies[0], "Max-Age=0") ||
			!strings.Contains(cookies[0], "Path=/") || !strings.Contains(cookies[0], "HttpOnly") {
			t.Errorf("%s no expira la cookie legada: %v", path, cookies)
		}
	}
}

func TestAPanicInAHandlerIsASanitized500(t *testing.T) {
	var logs bytes.Buffer
	server, err := New(config.Config{APIURL: "http://127.0.0.1:1"}, nil, slog.New(slog.NewTextHandler(&logs, nil)))
	if err != nil {
		t.Fatal(err)
	}
	handler := server.logging(server.recoverer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		panic("secreto interno 10.0.0.5")
	})))
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/estimations?token=abc", nil))

	if w.Code != 500 || w.Header().Get("Content-Type") != "application/json" {
		t.Fatalf("respuesta: %d %s", w.Code, w.Body.String())
	}
	for _, leaked := range []string{"secreto", "10.0.0.5", "goroutine", "<html"} {
		if strings.Contains(w.Body.String(), leaked) {
			t.Errorf("la respuesta expone %q: %s", leaked, w.Body.String())
		}
	}
	if !strings.Contains(logs.String(), "status=500") || strings.Contains(logs.String(), "token=abc") {
		t.Errorf("registro: %s", logs.String())
	}
}

// Un pánico tras empezar la respuesta (flujo SSE) corta la conexión en lugar de escribir un 500 sobre el cuerpo.
func TestAPanicAfterTheResponseStartedAbortsInsteadOfAppendingAnError(t *testing.T) {
	server, _ := New(config.Config{APIURL: "http://127.0.0.1:1"}, nil, nil)
	handler := server.logging(server.recoverer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, "event: x\n\n")
		panic("fallo tardío")
	})))
	w := httptest.NewRecorder()
	defer func() {
		if recovered := recover(); recovered != http.ErrAbortHandler {
			t.Errorf("se esperaba http.ErrAbortHandler y se obtuvo %v", recovered)
		}
		if strings.Contains(w.Body.String(), "detail") {
			t.Errorf("se añadió un error JSON al flujo: %s", w.Body.String())
		}
	}()
	handler.ServeHTTP(w, httptest.NewRequest("POST", "/api/v1/estimate/stream", nil))
}

// El registro usa la ruta del enrutador, sin identificadores de sesión ni cadena de consulta.
func TestRequestLogsCarryTheRoutePatternWithoutSessionIDsOrQueries(t *testing.T) {
	var logs bytes.Buffer
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(404) }))
	defer upstream.Close()
	server, err := New(config.Config{APIURL: upstream.URL}, nil, slog.New(slog.NewTextHandler(&logs, nil)))
	if err != nil {
		t.Fatal(err)
	}
	handler := server.Handler()
	for _, target := range []string{"/api/v1/sessions/" + testSessionID + "/estimate?clave=secreta", "/estimations/77?x=1", "/up"} {
		method := "POST"
		if target == "/up" {
			method = "GET"
		}
		handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(method, target, strings.NewReader("project_type=mobile_app")))
	}
	out := logs.String()
	for _, leaked := range []string{testSessionID, "clave=secreta", "secreta", "/estimations/77"} {
		if strings.Contains(out, leaked) {
			t.Errorf("el registro expone %q:\n%s", leaked, out)
		}
	}
	if !strings.Contains(out, "/api/v1/sessions/{session_id}/estimate") || strings.Contains(out, "path=/up") || strings.Contains(out, "route=/up") {
		t.Errorf("registro inesperado:\n%s", out)
	}
}

// capabilityWriter es un escritor con las capacidades que usan el streaming y las subidas.
type capabilityWriter struct {
	http.ResponseWriter
	flushErr   error
	flushes    int
	writeDeadl time.Time
	readDeadl  time.Time
}

func (w *capabilityWriter) FlushError() error { w.flushes++; return w.flushErr }
func (w *capabilityWriter) SetWriteDeadline(t time.Time) error {
	w.writeDeadl = t
	return nil
}
func (w *capabilityWriter) SetReadDeadline(t time.Time) error {
	w.readDeadl = t
	return nil
}

// 10.1: los wrappers de transporte propagan FlushError, los plazos y Unwrap hasta el escritor real.
func TestTransportWrappersKeepFlushErrorDeadlinesAndUnwrap(t *testing.T) {
	server, _ := New(config.Config{APIURL: "http://127.0.0.1:1"}, nil, nil)
	boom := errors.New("cliente cerrado")
	real := &capabilityWriter{ResponseWriter: httptest.NewRecorder(), flushErr: boom}
	deadline := time.Now().Add(time.Minute)
	var seen error
	handler := server.logging(server.recoverer(server.expireLegacyCookie(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		controller := http.NewResponseController(w)
		if err := controller.SetWriteDeadline(deadline); err != nil {
			t.Errorf("SetWriteDeadline no llegó al escritor real: %v", err)
		}
		if err := controller.SetReadDeadline(deadline); err != nil {
			t.Errorf("SetReadDeadline no llegó al escritor real: %v", err)
		}
		seen = controller.Flush()
	}))))
	handler.ServeHTTP(real, httptest.NewRequest("GET", "/x", nil))

	if !errors.Is(seen, boom) || real.flushes != 1 {
		t.Errorf("FlushError no se propaga: err=%v llamadas=%d", seen, real.flushes)
	}
	if !real.writeDeadl.Equal(deadline) || !real.readDeadl.Equal(deadline) {
		t.Errorf("plazos no propagados: %v %v", real.writeDeadl, real.readDeadl)
	}
	recorder := &statusRecorder{ResponseWriter: real}
	if recorder.Unwrap() != http.ResponseWriter(real) {
		t.Error("Unwrap no devuelve el escritor subyacente")
	}
	// Un escritor sin capacidades devuelve ErrNotSupported a través del wrapper, no un error propio.
	bare := httptest.NewRecorder()
	plain := &statusRecorder{ResponseWriter: struct{ http.ResponseWriter }{bare}}
	if err := http.NewResponseController(plain).SetWriteDeadline(deadline); !errors.Is(err, http.ErrNotSupported) {
		t.Errorf("se esperaba ErrNotSupported: %v", err)
	}
}

// Guardia de dependencias: el servicio no vuelve a incluir plantillas, estáticos HTML, cookies ni sesiones de navegador.
func TestNoHTMLPresentationDependenciesRemain(t *testing.T) {
	banned := []string{"html/template", "net/http/cookiejar", "estimator-web/internal/session", "SecretKeyBase", "authenticity_token", "X-CSRF-Token"}
	for _, pattern := range []string{"*.go", "../*/*.go", "../../cmd/server/*.go"} {
		files, _ := filepath.Glob(pattern)
		for _, name := range files {
			if strings.HasSuffix(name, "_test.go") {
				continue
			}
			data, err := os.ReadFile(name)
			if err != nil {
				t.Fatal(err)
			}
			for _, word := range banned {
				if strings.Contains(string(data), word) {
					t.Errorf("%s contiene %q", name, word)
				}
			}
		}
	}
	// Los únicos datos embebidos son los JSON del corpus de internal/estimatorai; la capa web no embebe nada.
	files, _ := filepath.Glob("*.go")
	for _, name := range files {
		data, _ := os.ReadFile(name)
		if !strings.HasSuffix(name, "_test.go") && strings.Contains(string(data), "go:embed") {
			t.Errorf("%s embebe archivos", name)
		}
	}
	for _, directory := range []string{"templates", "public", "../session"} {
		if _, err := os.Stat(directory); !os.IsNotExist(err) {
			t.Errorf("%s no debería existir", directory)
		}
	}
}

// Equivalente REST de «API inalcanzable → mensaje saneado»: 503 JSON sin la URL interna ni el error de red.
func TestAnUnreachableAIServiceIsASanitized503OnEveryPublicRoute(t *testing.T) {
	dead := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	url := dead.URL
	dead.Close()
	server, err := New(config.Config{APIURL: url, OpenTimeout: 500 * time.Millisecond, ReadTimeout: time.Second}, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	handler := server.Handler()
	for _, c := range []struct{ method, path, body, mime string }{
		{"POST", "/api/v1/sessions", "", ""},
		{"GET", "/api/v1/estimations", "", ""},
		{"GET", "/api/v1/estimations/7", "", ""},
		{"GET", "/api/v1/prompts/estimation", "", ""},
		{"POST", "/api/v1/estimate", estimateRequest, "application/json"},
	} {
		w := callPublicAPI(handler, c.method, c.path, c.body, c.mime)
		if w.Code != 503 || strings.Contains(w.Body.String(), url) || strings.Contains(w.Body.String(), "127.0.0.1") {
			t.Errorf("%s %s: %d %s", c.method, c.path, w.Code, w.Body.String())
		}
	}
}
