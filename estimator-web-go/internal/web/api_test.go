package web

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
	"unicode/utf8"

	"estimator-web/internal/config"
)

const testSessionID = "c843f44b-78c8-42e2-9ba1-0861267dade3"
const estimateRequest = `{"description":"Una descripción suficiente para estimar.","project_type":"mobile_app","detail_level":"medium","output_format":"phases_table"}`
const estimateResult = `{"summary":"Resultado","confidence_pct":20,"phases":[{"name":"Diseño","duration_weeks":1,"cost_eur":0}],"total_duration_weeks":1,"total_cost_eur":0,"out_of_scope":true}`

func testAPI(t *testing.T, upstream http.HandlerFunc, change func(*config.Config)) http.Handler {
	t.Helper()
	p := httptest.NewServer(upstream)
	t.Cleanup(p.Close)
	cfg := config.Config{APIURL: p.URL}
	if change != nil {
		change(&cfg)
	}
	server, err := New(cfg, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	return server.Handler()
}

func callPublicAPI(handler http.Handler, method, path, body, mime string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	if mime != "" {
		r.Header.Set("Content-Type", mime)
	}
	handler.ServeHTTP(w, r)
	return w
}

func TestPublicRESTContracts(t *testing.T) {
	handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/api/v1/sessions":
			w.WriteHeader(201)
			fmt.Fprintf(w, `{"session_id":%q}`, testSessionID)
		case "/api/v1/sessions/" + testSessionID + "/estimate":
			if err := r.ParseForm(); err != nil || r.Form.Get("project_type") != "mobile_app" {
				t.Error("formulario no conservado")
			}
			fmt.Fprintf(w, `{"session_id":%q,"project_metadata":{},"turn_count":1,"max_turns":8,"result":%s,"prompt_version":"v4","estimation_id":null}`, testSessionID, estimateResult)
		case "/api/v1/estimate":
			body, _ := io.ReadAll(r.Body)
			if !strings.Contains(string(body), `"reference_projects":[{`) || r.URL.Query().Get("prompt_version") != "v3" {
				t.Error("referencias o versión no conservadas")
			}
			fmt.Fprintf(w, `{"result":%s,"prompt_version":"v3","estimation_id":42,"adicional":null}`, estimateResult)
		case "/api/v1/prompts/estimation":
			if r.URL.Query().Get("project_type") != "mobile_app" || r.URL.Query().Has("session_id") {
				t.Error("query de vista previa incorrecta")
			}
			io.WriteString(w, `{"prompt_version":"v3","system_prompt":"Prompt","examples":[]}`)
		case "/api/v1/estimations":
			if r.URL.Query().Get("limit") != "10" {
				t.Error("límite incorrecto")
			}
			io.WriteString(w, `[]`)
		case "/api/v1/estimations/42":
			fmt.Fprintf(w, `{"id":42,"description":"Proyecto","requested_at":"2026-01-01T00:00:00Z","completed_at":"2026-01-01T00:00:01Z","options":{"project_type":"mobile_app","detail_level":"medium","output_format":"phases_table","reference_projects":null},"prompt_version":"v3","result":%s,"cached":false,"cache_source":"none","model":"fake","provider":"fake","metrics":null,"metadata_snapshot":null}`, estimateResult)
		case "/health":
			io.WriteString(w, `{"status":"healthy","environment":"test","provider":"fake","model":"fake"}`)
		default:
			http.NotFound(w, r)
		}
	}, nil)
	for _, c := range []struct {
		method, path, body, mime, contains string
		status                             int
	}{
		{"POST", "/api/v1/sessions", "", "", "session_id", 201},
		{"POST", "/api/v1/sessions/" + testSessionID + "/estimate", "project_type=mobile_app", "application/x-www-form-urlencoded", `"estimation_id":null`, 200},
		{"POST", "/api/v1/estimate", strings.TrimSuffix(estimateRequest, "}") + `,"reference_projects":[{"name":"Anterior","description":"Referencia","actual_hours":10}]}`, "application/json", `"adicional":null`, 200},
		{"GET", "/api/v1/prompts/estimation?session_id=ignored", "", "", "system_prompt", 200},
		{"GET", "/api/v1/estimations", "", "", "[]", 200},
		{"GET", "/api/v1/estimations/42", "", "", `"metrics":null`, 200},
		{"GET", "/health", "", "", "healthy", 200},
	} {
		w := callPublicAPI(handler, c.method, c.path, c.body, c.mime)
		if w.Code != c.status || !strings.Contains(w.Body.String(), c.contains) || w.Header().Get("Content-Type") != "application/json" {
			t.Errorf("%s: %d %s", c.path, w.Code, w.Body.String())
		}
	}
}

func TestInvalidRESTTransportNeverCallsUpstream(t *testing.T) {
	handler := testAPI(t, func(http.ResponseWriter, *http.Request) { t.Error("llamada upstream inesperada") }, nil)
	for _, c := range []struct {
		method, path, body, mime string
		status                   int
	}{
		{"GET", "/api/v1/search", "", "", 404},
		{"DELETE", "/api/v1/sessions", "", "", 405},
		{"POST", "/api/v1/estimate", "{", "application/json", 400},
		{"POST", "/api/v1/estimate", "{}", "text/plain", 415},
		{"POST", "/api/v1/estimate", "{}", "application/json", 422},
		{"POST", "/api/v1/estimate", strings.Repeat("x", jsonLimit+1), "application/json", 413},
		{"GET", "/api/v1/estimations?limit=51", "", "", 422},
		{"GET", "/api/v1/estimations/invalid", "", "", 422},
	} {
		w := callPublicAPI(handler, c.method, c.path, c.body, c.mime)
		if w.Code != c.status {
			t.Errorf("%s: %d, se esperaba %d", c.path, w.Code, c.status)
		}
	}
}

func TestPublicTimeoutCancelsUpstream(t *testing.T) {
	closed := make(chan struct{})
	handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.ReadAll(r.Body)
		<-r.Context().Done()
		close(closed)
	}, func(c *config.Config) { c.PublicLongHeaders = 150 * time.Millisecond })
	w := callPublicAPI(handler, "POST", "/api/v1/estimate", estimateRequest, "application/json")
	if w.Code != 504 {
		t.Fatalf("estado %d: %s", w.Code, w.Body.String())
	}
	select {
	case <-closed:
	case <-time.After(2 * time.Second):
		t.Fatal("upstream no cancelado")
	}
}

func TestMultipartTurnPreservesRepeatedFileParts(t *testing.T) {
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	if err := writer.WriteField("project_type", "mobile_app"); err != nil {
		t.Fatal(err)
	}
	attachments := []string{"uno.pdf", "dos.docx"}
	for _, name := range attachments {
		part, err := writer.CreateFormFile("attachments", name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = io.WriteString(part, "contenido "+name); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		if got, _ := io.ReadAll(r.Body); !bytes.Equal(got, body.Bytes()) {
			t.Error("el cuerpo multipart cambió")
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"session_id":%q,"project_metadata":{},"turn_count":1,"max_turns":8,"result":%s,"prompt_version":"v4"}`, testSessionID, estimateResult)
	}, nil)
	w := callPublicAPI(handler, "POST", "/api/v1/sessions/"+testSessionID+"/estimate", body.String(), writer.FormDataContentType())
	if w.Code != 200 {
		t.Fatalf("%d: %s", w.Code, w.Body.String())
	}
}

func TestPublicErrorsAndHealthAreSanitized(t *testing.T) {
	handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/health":
			io.WriteString(w, `{"status":"healthy","secret":"interno"}`)
		case "/api/v1/estimate":
			w.WriteHeader(400)
			io.WriteString(w, `{"reason":"pii_email","message":"secreto interno"}`)
		case "/api/v1/estimations":
			w.WriteHeader(503)
			io.WriteString(w, `{"detail":"secreto interno"}`)
		default:
			w.WriteHeader(404)
			io.WriteString(w, `{"detail":"secreto interno"}`)
		}
	}, nil)
	for _, c := range []struct {
		method, path, body, contentType string
		status                          int
	}{
		{"GET", "/up", "", "", 200},
		{"GET", "/health", "", "", 503},
		{"GET", "/api/v1/estimations", "", "", 503},
		{"POST", "/api/v1/estimate", estimateRequest, "application/json", 400},
		{"POST", "/api/v1/sessions/" + testSessionID + "/estimate", "project_type=mobile_app", "application/x-www-form-urlencoded", 404},
	} {
		w := callPublicAPI(handler, c.method, c.path, c.body, c.contentType)
		if w.Code != c.status || strings.Contains(w.Body.String(), "interno") {
			t.Errorf("%s: %d %s", c.path, w.Code, w.Body.String())
		}
		if c.status == 400 && !strings.Contains(w.Body.String(), "pii_email") {
			t.Error("se perdió el motivo del guardrail")
		}
	}
}

func TestPublicJSONKeepsMaximumUnicodeDescription(t *testing.T) {
	text := strings.Repeat(`\ud83d\ude00`, 80000)
	payload := strings.Replace(estimateRequest, "Una descripción suficiente para estimar.", text, 1)
	handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		var input struct{ Description string }
		if err := json.NewDecoder(r.Body).Decode(&input); err != nil || utf8.RuneCountInString(input.Description) != 80000 {
			t.Error("conversión UTF-8 incorrecta")
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"result":%s,"prompt_version":"v3"}`, estimateResult)
	}, nil)
	w := callPublicAPI(handler, "POST", "/api/v1/estimate", payload, "application/json")
	if w.Code != 200 {
		t.Fatalf("estado %d: %s", w.Code, w.Body.String())
	}
}

func TestPublicPOSTDoesNotFollowRedirect(t *testing.T) {
	var requests atomic.Int32
	handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		http.Redirect(w, r, "/segundo-paso", 303)
	}, nil)
	w := callPublicAPI(handler, "POST", "/api/v1/sessions", "", "")
	if w.Code != 502 || requests.Load() != 1 {
		t.Fatalf("resultado %d, solicitudes %d", w.Code, requests.Load())
	}
}

func TestLongEstimationRemainsActiveAfterRegularBudget(t *testing.T) {
	started := make(chan struct{})
	release := make(chan struct{})
	handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		if r.Method == "GET" {
			waitRequestClose(t, r)
			return
		}
		close(started)
		select {
		case <-release:
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprintf(w, `{"result":%s,"prompt_version":"v3"}`, estimateResult)
		case <-r.Context().Done():
			t.Error("la generación perdió su presupuesto largo")
		}
	}, func(c *config.Config) {
		c.PublicRegularTotal = 120 * time.Millisecond
		c.PublicLongTotal = 3 * time.Second
	})
	finished := make(chan *httptest.ResponseRecorder, 1)
	go func() {
		finished <- callPublicAPI(handler, "POST", "/api/v1/estimate", estimateRequest, "application/json")
	}()
	select {
	case <-started:
	case <-time.After(2 * time.Second):
		t.Fatal("no empezó la generación simulada")
	}
	regular := callPublicAPI(handler, "GET", "/api/v1/estimations", "", "")
	close(release)
	if regular.Code != 504 {
		t.Errorf("plazo corto: estado %d", regular.Code)
	}
	if long := <-finished; long.Code != 200 {
		t.Fatalf("plazo largo: %d %s", long.Code, long.Body.String())
	}
}

func TestTurnLimitsRejectOversizedAndUnsupportedParts(t *testing.T) {
	handler := testAPI(t, func(http.ResponseWriter, *http.Request) {
		t.Error("adjunto inválido llegó a IA")
	}, nil)
	for _, test := range []struct {
		name   string
		size   int
		status int
	}{
		{"archivo.exe", 1, 415},
		{"archivo.pdf", fileLimit + 1, 413},
	} {
		t.Run(test.name, func(t *testing.T) {
			var body bytes.Buffer
			writer := multipart.NewWriter(&body)
			if err := writer.WriteField("project_type", "mobile_app"); err != nil {
				t.Fatal(err)
			}
			part, err := writer.CreateFormFile("attachments", test.name)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := io.WriteString(part, strings.Repeat("a", test.size)); err != nil {
				t.Fatal(err)
			}
			if err := writer.Close(); err != nil {
				t.Fatal(err)
			}
			req := httptest.NewRequest("POST", "/api/v1/sessions/"+testSessionID+"/estimate", &body)
			req.ContentLength = -1
			req.Header.Set("Content-Type", writer.FormDataContentType())
			w := httptest.NewRecorder()
			handler.ServeHTTP(w, req)
			if w.Code != test.status {
				t.Fatalf("%d: %s", w.Code, w.Body.String())
			}
		})
	}
}

func TestRESTRejectsInvalidUpstreamContracts(t *testing.T) {
	phase := `{"name":"Diseño","duration_weeks":1,"cost_eur":0}`
	for _, tc := range []struct{ name, method, path, input, mime, upstream string }{
		{"fase vacía", "POST", "/api/v1/estimate", estimateRequest, "application/json", `{"prompt_version":"v3","result":` + strings.Replace(estimateResult, phase, `{}`, 1) + `}`},
		{"coste ausente", "POST", "/api/v1/estimate", estimateRequest, "application/json", `{"prompt_version":"v3","result":` + strings.Replace(estimateResult, `,"cost_eur":0`, "", 1) + `}`},
		{"duración de tipo incorrecto", "POST", "/api/v1/estimate", estimateRequest, "application/json", `{"prompt_version":"v3","result":` + strings.Replace(estimateResult, `"duration_weeks":1`, `"duration_weeks":"1"`, 1) + `}`},
		{"campo no anulable", "POST", "/api/v1/estimate", estimateRequest, "application/json", `{"prompt_version":"v3","cached":null,"result":` + estimateResult + `}`},
		{"métricas incompletas", "POST", "/api/v1/estimate", estimateRequest, "application/json", `{"prompt_version":"v3","metrics":{"usage":{}},"result":` + estimateResult + `}`},
		{"ingreso de tipo incorrecto", "GET", "/api/v1/estimations", "", "", `{"id":1}`},
		{"entrada de historial incompleta", "GET", "/api/v1/estimations", "", "", `[{"id":1,"description_excerpt":""}]`},
		{"ejemplo nulo", "GET", "/api/v1/prompts/estimation", "", "", `{"prompt_version":"v3","system_prompt":"","examples":[{"title":null,"description":""}]}`},
		{"detalle sin opciones", "GET", "/api/v1/estimations/42", "", "", `{"id":42,"options":{},"description":"Proyecto","prompt_version":"v3","result":` + estimateResult + `}`},
		{"metadatos de conversación inválidos", "POST", "/api/v1/sessions/" + testSessionID + "/estimate", "project_type=mobile_app", "application/x-www-form-urlencoded", `{"session_id":"` + testSessionID + `","project_metadata":{"mentioned_technologies":[null]},"turn_count":1,"max_turns":8,"result":` + estimateResult + `,"prompt_version":"v4"}`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				io.WriteString(w, strings.Replace(tc.upstream, "{", `{"privado":"valor no publicable",`, 1))
			}, nil)
			w := callPublicAPI(handler, tc.method, tc.path, tc.input, tc.mime)
			if w.Code != 502 || w.Header().Get("Content-Type") != "application/json" || strings.Contains(w.Body.String(), "no publicable") {
				t.Fatalf("respuesta no saneada: %d %s", w.Code, w.Body.String())
			}
		})
	}
}

func TestRESTPreservesAdditiveFieldsAndExactNumbers(t *testing.T) {
	handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"prompt_version":"v3","result":%s,"estimation_id":9007199254740993,"metrics":null,"ext":{"n":9007199254740995,"d":0.1234567890123456789}}`, estimateResult)
	}, nil)
	w := callPublicAPI(handler, "POST", "/api/v1/estimate", estimateRequest, "application/json")
	for _, fragment := range []string{"9007199254740993", "9007199254740995", "0.1234567890123456789", `"metrics":null`} {
		if w.Code != 200 || !strings.Contains(w.Body.String(), fragment) {
			t.Fatalf("respuesta alterada: %d %s", w.Code, w.Body.String())
		}
	}
}

func TestRESTSessionRequiresExactSessionIDKey(t *testing.T) {
	handler := testAPI(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		fmt.Fprintf(w, `{"SESSION_ID":%q}`, testSessionID)
	}, nil)
	w := callPublicAPI(handler, "POST", "/api/v1/sessions", "", "")
	if w.Code != 502 || strings.Contains(w.Body.String(), testSessionID) {
		t.Fatalf("respuesta no saneada: %d %s", w.Code, w.Body.String())
	}
}
