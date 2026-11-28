package web

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"estimator-web/internal/config"
	"estimator-web/internal/rag"
)

// Un acceso al repositorio desde una solicitud desautorizada no debe llegar a este doble.
type forbiddenStore struct{ rag.Store }

func (forbiddenStore) Recent(context.Context, int) ([]rag.Comparison, error) {
	panic("lectura no autorizada")
}
func (forbiddenStore) Find(context.Context, int64) (*rag.Comparison, error) {
	panic("detalle no autorizado")
}
func (forbiddenStore) Create(context.Context, *rag.Comparison) error {
	panic("escritura no autorizada")
}

func TestAdministrativeOperationsDenyBeforeEffects(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {
		t.Error("operación denegada llamó a IA")
	}))
	defer upstream.Close()
	production, err := New(config.Config{APIURL: upstream.URL}, forbiddenStore{}, nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, decider := range []administrativeDecision{
		nil,
		func(context.Context, administrativeOperation) (bool, error) { return false, nil },
		func(context.Context, administrativeOperation) (bool, error) { return true, errors.New("dato interno") },
	} {
		production.adminDecision = decider
		handler := production.Handler()
		for _, request := range []struct{ method, path string }{
			{"GET", "/api/v1/ai/settings"}, {"PUT", "/api/v1/ai/settings"},
			{"GET", "/api/v1/rag/chunking-comparisons/options"},
			{"GET", "/api/v1/rag/chunking-comparisons"}, {"POST", "/api/v1/rag/chunking-comparisons"},
			{"GET", "/api/v1/rag/chunking-comparisons/1"},
		} {
			r := httptest.NewRequest(request.method, request.path, strings.NewReader(`{"models":{"primary_model":"gpt-4o"}}`))
			r.Header.Set("Content-Type", "application/json")
			r.Header.Set("X-Role", "admin")
			r.Header.Set("Authorization", "Bearer "+testSessionID)
			r.AddCookie(&http.Cookie{Name: legacyCookieName, Value: "cookie-legada"})
			w := httptest.NewRecorder()
			handler.ServeHTTP(w, r)
			if w.Code != 403 || strings.Contains(w.Body.String(), "interno") {
				t.Errorf("%s %s: %d %s", request.method, request.path, w.Code, w.Body.String())
			}
			if w.Header().Get("Content-Type") != "application/json" {
				t.Errorf("error API sin JSON: %s", request.path)
			}
		}
	}
}

func TestOriginRejectionPrecedesUpstream(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { t.Error("llamada no autorizada") }))
	defer upstream.Close()
	server, err := New(config.Config{APIURL: upstream.URL, PublicOrigin: "https://estimador.example"}, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	server.adminDecision = func(context.Context, administrativeOperation) (bool, error) { return true, nil }
	for _, test := range []struct {
		path, origin string
		status       int
	}{
		{"/api/v1/sessions", "null", 403},
		{"/api/v1/sessions", "https://otro.example", 403},
		{"/estimations", "https://otro.example", 403},
		{"/api/v1/rag/chunking-comparisons", "https://otro.example", 403},
		{"/rag/chunking_comparisons", "null", 403},
		// Con el origen configurado las rutas retiradas ya no existen (antes respondían 422 por CSRF de formulario).
		{"/rag/chunking_comparisons", "https://estimador.example", 404},
		{"/ai_settings", "https://estimador.example", 404},
	} {
		t.Run(fmt.Sprintf("%s %s", test.path, test.origin), func(t *testing.T) {
			req := httptest.NewRequest("POST", test.path, strings.NewReader(""))
			req.Header.Set("Origin", test.origin)
			w := httptest.NewRecorder()
			server.Handler().ServeHTTP(w, req)
			if w.Code != test.status {
				t.Fatalf("estado %d, se esperaba %d", w.Code, test.status)
			}
		})
	}
}

var assignsDecision = regexp.MustCompile(`adminDecision\s*(=[^=]|:=|:\s)`)

// El fake de decisión solo puede componerse desde pruebas: ningún código de producción asigna `adminDecision`.
func TestNoProductionCodeEnablesAnAdministrativeDecision(t *testing.T) {
	entries, err := filepath.Glob("*.go")
	if err != nil || len(entries) == 0 {
		t.Fatalf("fuentes: %v %v", entries, err)
	}
	for _, name := range entries {
		if strings.HasSuffix(name, "_test.go") {
			continue
		}
		data, err := os.ReadFile(name)
		if err != nil {
			t.Fatal(err)
		}
		for number, line := range strings.Split(string(data), "\n") {
			trimmed := strings.TrimSpace(line)
			if strings.HasPrefix(trimmed, "//") || !strings.Contains(trimmed, "adminDecision") {
				continue
			}
			// Solo la declaración del campo y su lectura en la decisión: ninguna asignación.
			if assignsDecision.MatchString(trimmed) {
				t.Errorf("%s:%d asigna adminDecision en código de producción: %s", name, number+1, trimmed)
			}
		}
	}
	for _, directory := range []string{"../../cmd/server", "../config", "../estimatorai"} {
		files, _ := filepath.Glob(directory + "/*.go")
		for _, name := range files {
			if strings.HasSuffix(name, "_test.go") {
				continue
			}
			data, _ := os.ReadFile(name)
			text := strings.ToLower(string(data))
			for _, banned := range []string{"admindecision", "fake_admin", "admin_override", "x-role", "x-forwarded-user"} {
				if strings.Contains(text, banned) {
					t.Errorf("%s contiene %q: no debe existir un interruptor ni identidad de proxy", name, banned)
				}
			}
		}
	}
}

// La composición normal (la de cmd/server: configuración del entorno y sin decisión) deniega toda ruta administrativa
// aunque el cliente falsifique cabeceras, cookies, credenciales predeterminadas o variables de entorno.
func TestNormalCompositionDeniesEveryAdministrativeRouteWhateverTheClientSends(t *testing.T) {
	for _, name := range []string{"ESTIMATOR_ADMIN", "ESTIMATOR_TEST_AUTH", "ADMIN_FAKE", "ESTIMATOR_AUTH_BYPASS", "ESTIMATOR_ROLE", "ADMIN_PASSWORD"} {
		t.Setenv(name, "admin")
	}
	upstream := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { t.Error("operación denegada llamó a IA") }))
	defer upstream.Close()
	t.Setenv("ESTIMATOR_API_URL", upstream.URL)
	cfg, err := config.FromEnv(os.Getenv)
	if err != nil {
		t.Fatal(err)
	}
	server, err := New(cfg, forbiddenStore{}, nil)
	if err != nil {
		t.Fatal(err)
	}
	handler := server.Handler()
	forged := [][]string{
		{"X-Role", "admin"}, {"X-Forwarded-User", "admin"}, {"X-Admin", "true"}, {"X-Authenticated-User", "root"},
		{"Authorization", "Basic YWRtaW46YWRtaW4="}, {"Authorization", "Bearer admin"}, {"Cookie", "role=admin; admin=1; session=" + testSessionID},
		{"X-Conversation-Id", testSessionID}, {"Origin", "http://localhost:3001"}, {"Sec-Fetch-Site", "same-origin"},
	}
	for _, request := range []struct{ method, path, body string }{
		{"GET", "/api/v1/ai/settings", ""}, {"PUT", "/api/v1/ai/settings", `{"models":{"primary_model":"gpt-4o"}}`},
		{"GET", "/api/v1/rag/chunking-comparisons/options", ""}, {"GET", "/api/v1/rag/chunking-comparisons", ""},
		{"POST", "/api/v1/rag/chunking-comparisons", `{"strategies":["structural"]}`}, {"GET", "/api/v1/rag/chunking-comparisons/9007199254740993", ""},
	} {
		for _, header := range forged {
			r := httptest.NewRequest(request.method, request.path, strings.NewReader(request.body))
			r.Header.Set("Content-Type", "application/json")
			r.Header.Set(header[0], header[1])
			w := httptest.NewRecorder()
			handler.ServeHTTP(w, r)
			if w.Code != 403 {
				t.Errorf("%s %s con %s: %d", request.method, request.path, header[0], w.Code)
			}
			if strings.Contains(w.Body.String(), "interno") || strings.Contains(w.Body.String(), "models") {
				t.Errorf("la denegación expone datos: %s", w.Body.String())
			}
		}
	}
	// El único dato administrativo general es el nombre efectivo del primario: la IA simulada no responde aquí.
	upstream.Close()
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, httptest.NewRequest("GET", "/api/v1/ai/primary-model", nil))
	if w.Code != 200 || strings.TrimSpace(w.Body.String()) != `{"model":null}` {
		t.Errorf("proyección general: %d %s", w.Code, w.Body.String())
	}
}
