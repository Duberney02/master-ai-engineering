package web

import (
	"encoding/json"
	"html/template"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"testing"

	"estimator-web/internal/session"
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

func TestTheHealthProbeAnswers200WithoutCallingAnyone(t *testing.T) {
	h := newHarness(t)

	p := h.get("/up")

	h.wantStatus(p, 200)
	if len(h.api.calls) != 0 {
		t.Errorf("la sonda de salud no debe llamar a la API (%d llamadas)", len(h.api.calls))
	}
}

func TestUnknownRoutesAreA404Page(t *testing.T) {
	h := newHarness(t)
	for _, path := range []string{"/nada", "/estimations/1/editar", "/rag", "/ai_settings/otra"} {
		p := h.get(path)
		h.wantStatus(p, 404)
		h.wantContains(p, "<!doctype html>")
	}
	request, _ := http.NewRequest(http.MethodDelete, h.app.URL+"/estimations", nil)
	h.wantStatus(h.do(request), 404)
}

func TestStaticPublicFilesAreServed(t *testing.T) {
	h := newHarness(t)
	h.wantStatus(h.get("/robots.txt"), 200)
	h.wantStatus(h.get("/404.html"), 200)
}

func TestAPostWithoutACSRFTokenIsRejectedAndNothingIsCalled(t *testing.T) {
	h := newHarness(t)
	h.get("/estimations/new")
	calls := len(h.api.calls)

	request, _ := http.NewRequest(http.MethodPost, h.app.URL+"/estimations", strings.NewReader(formValues(nil).Encode()))
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	p := h.do(request)

	h.wantStatus(p, 422)
	if len(h.api.calls) != calls {
		t.Error("una petición sin token no debe llegar a la API")
	}
}

func TestAPostWithAWrongTokenOrNoSessionIsRejected(t *testing.T) {
	h := newHarness(t)
	h.get("/")
	values := formValues(nil)
	values.Set("authenticity_token", "token-falso")
	p := h.post("/estimations", values)
	h.wantStatus(p, 422)

	fresh := newHarness(t)
	values = formValues(nil)
	values.Set("authenticity_token", h.csrf) // el token de otra sesión
	h.wantStatus(fresh.post("/estimations", values), 422)
}

func TestTheCSRFTokenCanTravelInAHeader(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, estimateBody(estimateOptions{id: 7}), 200)
	token := h.token()

	request, _ := http.NewRequest(http.MethodPost, h.app.URL+"/estimations", strings.NewReader(formValues(nil).Encode()))
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	request.Header.Set("X-CSRF-Token", token)

	h.wantStatus(h.do(request), 302)
}

func TestEveryFormCarriesTheCSRFToken(t *testing.T) {
	h := newHarness(t)
	h.api.stubJSON("GET", "/api/v1/estimations", 200, []any{})
	for path, forms := range map[string]int{"/estimations/new": 2, "/rag/chunking_comparisons/new": 1, "/ai_settings": 1} {
		p := h.get(path)
		if got := p.count(`name="authenticity_token" value="` + h.csrf + `"`); got != forms {
			t.Errorf("%s: %d formularios con token, se esperaban %d", path, got, forms)
		}
	}
}

func TestATamperedSessionCookieIsAnEmptySession(t *testing.T) {
	h := newHarness(t)
	stubEstimate(h, estimateBody(estimateOptions{id: 7, metadata: projectMetadata}), 200)
	h.post("/estimations", formValues(nil))
	if text, _ := h.get("/estimations/new").textOf("metadata-name"); text != "Orion" {
		t.Fatalf("el estado debe persistir entre peticiones: %q", text)
	}

	cookies := h.client.Jar.Cookies(mustURL(h.app.URL))
	for _, cookie := range cookies {
		if cookie.Name == session.CookieName {
			cookie.Value = "eyJjIjoiaGFja2VhZG8ifQ" + cookie.Value[strings.Index(cookie.Value, "."):]
			h.client.Jar.SetCookies(mustURL(h.app.URL), []*http.Cookie{cookie})
		}
	}

	p := h.get("/estimations/new")
	h.wantContains(p, `id="no-project-metadata"`)
	if h.api.count("POST", "/api/v1/sessions") != 2 {
		t.Error("una cookie manipulada debe abrir una conversación nueva")
	}
}

func TestTheSessionCookieIsHttpOnlyAndSameSiteLax(t *testing.T) {
	h := newHarness(t)
	p := h.get("/estimations/new")

	var found bool
	for _, header := range p.header.Values("Set-Cookie") {
		if strings.HasPrefix(header, session.CookieName+"=") {
			found = true
			if !strings.Contains(header, "HttpOnly") || !strings.Contains(header, "SameSite=Lax") {
				t.Errorf("atributos de la cookie: %s", header)
			}
		}
	}
	if !found {
		t.Error("falta la cookie de sesión")
	}
}

func TestAnOversizedBodyIsRejected(t *testing.T) {
	h := newHarness(t)
	big := strings.Repeat("x", 65<<20)
	request, _ := http.NewRequest(http.MethodPost, h.app.URL+"/estimations", strings.NewReader("estimation_form[description]="+big))
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")

	h.wantStatus(h.do(request), 413)
}

func TestAPanicInAHandlerIsASanitized500(t *testing.T) {
	h := newHarness(t)
	h.server.pages = map[string]*template.Template{} // fuerza el pánico de «plantilla desconocida»

	p := h.get("/")

	h.wantStatus(p, 500)
	h.wantAbsent(p, "plantilla desconocida", "goroutine")
}
