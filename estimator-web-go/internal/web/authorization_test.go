package web

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
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
	production, err := New(config.Config{APIURL: upstream.URL, SecretKeyBase: "solo-pruebas"}, forbiddenStore{}, nil)
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
			{"GET", "/ai_settings"}, {"POST", "/ai_settings"}, {"PATCH", "/ai_settings"}, {"PUT", "/ai_settings"},
			{"GET", "/rag/chunking_comparisons/new"}, {"GET", "/rag/chunking_comparisons"}, {"POST", "/rag/chunking_comparisons"},
			{"GET", "/rag/chunking_comparisons/1"},
		} {
			r := httptest.NewRequest(request.method, request.path, strings.NewReader("_method=patch"))
			r.Header.Set("Content-Type", "application/x-www-form-urlencoded")
			r.Header.Set("X-Role", "admin")
			r.Header.Set("Authorization", "Bearer "+testSessionID)
			sessionCookie := httptest.NewRecorder()
			session := production.sessions.Load(r)
			session.SetConversation(testSessionID)
			session.Commit(sessionCookie)
			for _, cookie := range sessionCookie.Result().Cookies() {
				r.AddCookie(cookie)
			}
			w := httptest.NewRecorder()
			handler.ServeHTTP(w, r)
			if w.Code != 403 || strings.Contains(w.Body.String(), "interno") {
				t.Errorf("%s %s: %d %s", request.method, request.path, w.Code, w.Body.String())
			}
			if strings.HasPrefix(request.path, "/api/") && w.Header().Get("Content-Type") != "application/json" {
				t.Errorf("error API sin JSON: %s", request.path)
			}
		}
	}
}

func TestOriginRejectionAndLegacyCSRFPrecedeUpstream(t *testing.T) {
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
		{"/rag/chunking_comparisons", "https://estimador.example", 422},
		{"/ai_settings", "https://estimador.example", 422},
	} {
		t.Run(fmt.Sprintf("%s %s", test.path, test.origin), func(t *testing.T) {
			form := ""
			if test.path == "/ai_settings" {
				form = "_method=patch"
			}
			req := httptest.NewRequest("POST", test.path, strings.NewReader(form))
			req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
			req.Header.Set("Origin", test.origin)
			w := httptest.NewRecorder()
			server.Handler().ServeHTTP(w, req)
			if w.Code != test.status {
				t.Fatalf("estado %d, se esperaba %d", w.Code, test.status)
			}
		})
	}
}
