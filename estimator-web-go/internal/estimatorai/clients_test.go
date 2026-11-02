package estimatorai

import (
	"context"
	"encoding/json"
	"io"
	"mime"
	"mime/multipart"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

const sessionID = "6f1c2c1e-6d0a-4a5e-9c1a-0d6f5b1f4a10"

// fakeAPI es una API simulada: cada prueba fija la respuesta de una ruta y registra lo que se le envió.
type fakeAPI struct {
	t        *testing.T
	server   *httptest.Server
	status   int
	body     string
	requests []*recorded
}

type recorded struct {
	method, path, rawQuery, contentType string
	body                                []byte
}

func newFakeAPI(t *testing.T, status int, body string) *fakeAPI {
	t.Helper()
	api := &fakeAPI{t: t, status: status, body: body}
	api.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		payload, _ := io.ReadAll(r.Body)
		api.requests = append(api.requests, &recorded{
			method: r.Method, path: r.URL.EscapedPath(), rawQuery: r.URL.RawQuery,
			contentType: r.Header.Get("Content-Type"), body: payload,
		})
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(api.status)
		_, _ = io.WriteString(w, api.body)
	}))
	t.Cleanup(api.server.Close)
	return api
}

func (a *fakeAPI) settings() Settings {
	return Settings{BaseURL: a.server.URL, OpenTimeout: time.Second, ReadTimeout: 5 * time.Second}
}

func (a *fakeAPI) last() *recorded { return a.requests[len(a.requests)-1] }

func mustKind(t *testing.T, err error, kind Kind) *Error {
	t.Helper()
	typed, ok := As(err)
	if !ok {
		t.Fatalf("se esperaba *Error, llegó %v", err)
	}
	if !typed.IsA(kind) {
		t.Fatalf("se esperaba la clase %d, llegó %d (%s)", kind, typed.Kind, typed.Message)
	}
	return typed
}

func TestErrorHierarchy(t *testing.T) {
	if !newError(RequestTimeout, "x", 0).IsA(ConnectionFailed) {
		t.Error("RequestTimeout debe ser un ConnectionFailed")
	}
	if !newError(SessionExpired, "x", 404).IsA(NotFound) {
		t.Error("SessionExpired debe ser un NotFound")
	}
	if newError(ConnectionFailed, "x", 0).IsA(RequestTimeout) || newError(NotFound, "x", 404).IsA(SessionExpired) {
		t.Error("la jerarquía no es simétrica")
	}
}

func TestStatusesMapToTypedErrorsWithSanitizedMessages(t *testing.T) {
	cases := []struct {
		status  int
		body    string
		kind    Kind
		message string
	}{
		{404, `{"detail":"x"}`, NotFound, NotFoundMessage},
		{422, `{"detail":[{"msg":"secret detail"}]}`, InvalidRequest, ValidationMessage},
		{503, `boom`, ServiceUnavailable, HistoryUnavailableMessage},
		{500, `Traceback (most recent call last): secret sk-abc http://estimator-api.test/internal`, ServerError, ServerMessage},
		{502, `Traceback password=hunter2`, ServerError, ServerMessage},
		{400, `{"reason":"pii","message":"Hay un correo."}`, GuardrailViolation, "Hay un correo."},
		{400, `<html>proxy</html>`, GuardrailViolation, RejectedMessage},
		{418, `x`, InvalidRequest, RejectedMessage},
	}
	for _, tc := range cases {
		api := newFakeAPI(t, tc.status, tc.body)
		_, err := NewEstimationsClient(api.settings()).FindEstimation(context.Background(), "7")
		typed := mustKind(t, err, tc.kind)
		if typed.Message != tc.message || typed.Status != tc.status {
			t.Errorf("estado %d: mensaje %q (estado %d), se esperaba %q", tc.status, typed.Message, typed.Status, tc.message)
		}
		for _, secret := range []string{"sk-abc", "hunter2", "estimator-api.test", "secret detail"} {
			if strings.Contains(typed.Message, secret) {
				t.Errorf("el mensaje filtra %q", secret)
			}
		}
	}
}

func TestGuardrailMessageIsTruncated(t *testing.T) {
	api := newFakeAPI(t, 400, `{"message":"`+strings.Repeat("ñ", 1000)+`"}`)
	_, err := NewEstimationsClient(api.settings()).CreateEstimation(context.Background(), map[string]string{"description": "x"}, "")
	if got := len([]rune(mustKind(t, err, GuardrailViolation).Message)); got != MessageLimit {
		t.Errorf("el mensaje debe acotarse a %d caracteres, tiene %d", MessageLimit, got)
	}
}

func TestHistoryMapsServiceUnavailableToFriendlyMessage(t *testing.T) {
	api := newFakeAPI(t, 503, `{"detail":"History is not configured"}`)
	_, err := NewEstimationsClient(api.settings()).ListEstimations(context.Background(), 10)
	typed := mustKind(t, err, ServiceUnavailable)
	if typed.Message != HistoryUnavailableMessage || strings.Contains(typed.Message, "configured") {
		t.Errorf("mensaje inesperado: %q", typed.Message)
	}
	if api.last().rawQuery != "limit=10" {
		t.Errorf("consulta: %q", api.last().rawQuery)
	}
}

func TestInvalidResponses(t *testing.T) {
	for _, body := range []string{"<html>no es json</html>", `{"nope":1}`, `[1,2]`, ``, `{"result":{}} {"x":1}`} {
		api := newFakeAPI(t, 200, body)
		_, err := NewEstimationsClient(api.settings()).CreateEstimation(context.Background(), map[string]string{"description": "x"}, "")
		if typed := mustKind(t, err, InvalidResponse); typed.Message != InvalidResponseMessage {
			t.Errorf("cuerpo %q: mensaje %q", body, typed.Message)
		}
	}
}

func TestConnectionFailureAndTimeoutAreTypedWithoutLeakingTheURL(t *testing.T) {
	listener, _ := net.Listen("tcp", "127.0.0.1:0")
	address := listener.Addr().String()
	_ = listener.Close() // nadie escucha: conexión rechazada
	refused := NewEstimationsClient(Settings{BaseURL: "http://" + address, OpenTimeout: time.Second, ReadTimeout: time.Second})
	_, err := refused.FindEstimation(context.Background(), "7")
	typed := mustKind(t, err, ConnectionFailed)
	if typed.Message != ConnectionMessage || strings.Contains(typed.Message, address) || typed.Kind == RequestTimeout {
		t.Errorf("fallo de conexión mal traducido: %+v", typed)
	}

	slow := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { time.Sleep(300 * time.Millisecond) }))
	defer slow.Close()
	timed := NewEstimationsClient(Settings{BaseURL: slow.URL, OpenTimeout: time.Second, ReadTimeout: 50 * time.Millisecond})
	_, err = timed.FindEstimation(context.Background(), "7")
	typed = mustKind(t, err, RequestTimeout)
	if !typed.IsA(ConnectionFailed) || typed.Message != ConnectionMessage || strings.Contains(typed.Message, slow.URL) {
		t.Errorf("tiempo agotado mal traducido: %+v", typed)
	}
}

func TestDetailModeShowsAPIDetail(t *testing.T) {
	cases := []struct {
		status int
		detail string
		kind   Kind
	}{
		{400, "El modelo 'x' requiere ANTHROPIC_API_KEY, que no está configurada", InvalidRequest},
		{422, "Knob desconocido: nope", InvalidRequest},
		{503, "El almacén de configuración no está disponible", ServiceUnavailable},
		{404, "No existe", NotFound},
		{500, "Fallo interno", ServerError},
	}
	for _, tc := range cases {
		payload, _ := json.Marshal(map[string]string{"detail": tc.detail})
		api := newFakeAPI(t, tc.status, string(payload))
		value := "x"
		_, err := NewConfigClient(api.settings()).UpdateModels(context.Background(), map[string]*string{"primary_model": &value})
		if typed := mustKind(t, err, tc.kind); typed.Message != tc.detail {
			t.Errorf("estado %d: %q", tc.status, typed.Message)
		}
	}

	api := newFakeAPI(t, 422, `{"detail":[{"msg":"privado"}]}`)
	_, err := NewConfigClient(api.settings()).Models(context.Background())
	if typed := mustKind(t, err, InvalidRequest); typed.Message != ValidationMessage || strings.Contains(typed.Message, "privado") {
		t.Errorf("un detail que no es texto debe caer al mensaje genérico: %q", typed.Message)
	}
}

func TestCreateEstimationSendsJSONAndPromptVersion(t *testing.T) {
	api := newFakeAPI(t, 200, `{"result":{"total_cost_eur":20000},"estimation_id":7}`)
	doc, err := NewEstimationsClient(api.settings()).CreateEstimation(context.Background(), map[string]string{"description": "x"}, "v2")
	if err != nil {
		t.Fatal(err)
	}
	if doc.S("estimation_id") != "7" || doc.Doc("result").S("total_cost_eur") != "20000" {
		t.Errorf("respuesta: %v", doc)
	}
	request := api.last()
	if request.method != "POST" || request.rawQuery != "prompt_version=v2" || !strings.HasPrefix(request.contentType, "application/json") {
		t.Errorf("petición: %+v", request)
	}
}

func TestFindEstimationNonNumericIsNotFoundWithoutCallingTheAPI(t *testing.T) {
	api := newFakeAPI(t, 200, `{}`)
	_, err := NewEstimationsClient(api.settings()).FindEstimation(context.Background(), "abc")
	typed := mustKind(t, err, NotFound)
	if typed.Status != 404 || typed.Message != NotFoundMessage || len(api.requests) != 0 {
		t.Errorf("%+v, peticiones: %d", typed, len(api.requests))
	}
}

func TestListEstimationsValidatesShape(t *testing.T) {
	api := newFakeAPI(t, 200, `[{"id":1},{"id":2}]`)
	items, err := NewEstimationsClient(api.settings()).ListEstimations(context.Background(), 10)
	if err != nil || len(items) != 2 {
		t.Fatalf("items %v, err %v", items, err)
	}
	api.body = `{"no":"lista"}`
	_, err = NewEstimationsClient(api.settings()).ListEstimations(context.Background(), 10)
	mustKind(t, err, InvalidResponse)
	api.body = `[1]`
	_, err = NewEstimationsClient(api.settings()).ListEstimations(context.Background(), 10)
	mustKind(t, err, InvalidResponse)
}

func TestPromptPreview(t *testing.T) {
	api := newFakeAPI(t, 200, `{"prompt_version":"v3","system_prompt":"Eres un arquitecto","examples":[]}`)
	doc, err := NewEstimationsClient(api.settings()).PromptPreview(context.Background(), "v3", "web_saas", "medium", "phases_table")
	if err != nil || doc.S("system_prompt") != "Eres un arquitecto" {
		t.Fatalf("%v %v", doc, err)
	}
	if api.last().rawQuery != "detail_level=medium&output_format=phases_table&project_type=web_saas&prompt_version=v3" {
		t.Errorf("consulta: %s", api.last().rawQuery)
	}
	api.body = `{"otro":1}`
	_, err = NewEstimationsClient(api.settings()).PromptPreview(context.Background(), "v3", "a", "b", "c")
	mustKind(t, err, InvalidResponse)
}

func TestCreateSession(t *testing.T) {
	api := newFakeAPI(t, 201, `{"session_id":"abc-123"}`)
	id, err := NewSessionsClient(api.settings()).CreateSession(context.Background())
	if err != nil || id != "abc-123" || api.last().method != "POST" || api.last().path != "/api/v1/sessions" {
		t.Fatalf("id %q err %v req %+v", id, err, api.last())
	}

	api.body = `{"otro":1}`
	_, err = NewSessionsClient(api.settings()).CreateSession(context.Background())
	mustKind(t, err, InvalidResponse)

	api.status, api.body = 200, `{"session_id":"x"}`
	_, err = NewSessionsClient(api.settings()).CreateSession(context.Background())
	if typed := mustKind(t, err, InvalidRequest); typed.Status != 200 {
		t.Errorf("se espera 201: un 200 no es válido (%+v)", typed)
	}

	api.status, api.body = 500, `Traceback password=hunter2`
	_, err = NewSessionsClient(api.settings()).CreateSession(context.Background())
	if typed := mustKind(t, err, ServerError); typed.Message != ServerMessage || typed.Status != 500 {
		t.Errorf("%+v", typed)
	}
}

const estimateOK = `{"result":{"summary":"ok"},"estimation_id":7,"project_metadata":{"mentioned_technologies":[]}}`

func parseMultipart(t *testing.T, request *recorded) *multipart.Form {
	t.Helper()
	mediaType, params, err := mime.ParseMediaType(request.contentType)
	if err != nil || mediaType != "multipart/form-data" {
		t.Fatalf("Content-Type %q", request.contentType)
	}
	form, err := multipart.NewReader(strings.NewReader(string(request.body)), params["boundary"]).ReadForm(1 << 20)
	if err != nil {
		t.Fatal(err)
	}
	return form
}

func TestSessionEstimationSendsMultipartEvenWithoutAttachments(t *testing.T) {
	api := newFakeAPI(t, 200, estimateOK)
	fields := []Field{{"transcript", "Portal ñandú"}, {"project_type", "web_saas"}, {"prompt_version", "v3"}}
	doc, err := NewSessionsClient(api.settings()).CreateSessionEstimation(context.Background(), sessionID, fields, nil)
	if err != nil || doc.S("estimation_id") != "7" {
		t.Fatalf("%v %v", doc, err)
	}
	form := parseMultipart(t, api.last())
	if form.Value["transcript"][0] != "Portal ñandú" || form.Value["project_type"][0] != "web_saas" || len(form.File) != 0 {
		t.Errorf("campos: %v archivos: %v", form.Value, form.File)
	}
	if !strings.Contains(string(api.last().body), "text/plain; charset=UTF-8") {
		t.Error("cada campo debe ir como parte de texto UTF-8")
	}
	if api.last().path != "/api/v1/sessions/"+sessionID+"/estimate" {
		t.Errorf("ruta: %s", api.last().path)
	}
}

func TestSessionEstimationSendsEachAttachmentInOrder(t *testing.T) {
	api := newFakeAPI(t, 200, estimateOK)
	attachments := []Attachment{
		{Filename: "requisitos.pdf", ContentType: "application/pdf", Data: []byte("%PDF-uno")},
		{Filename: "alcance.docx", Data: []byte("PK-dos")},
	}
	if _, err := NewSessionsClient(api.settings()).CreateSessionEstimation(context.Background(), sessionID, []Field{{"transcript", "x"}}, attachments); err != nil {
		t.Fatal(err)
	}
	files := parseMultipart(t, api.last()).File["attachments"]
	if len(files) != 2 || files[0].Filename != "requisitos.pdf" || files[1].Filename != "alcance.docx" {
		t.Fatalf("archivos: %v", files)
	}
	if files[1].Header.Get("Content-Type") != "application/octet-stream" {
		t.Errorf("sin tipo declarado debe usarse application/octet-stream: %s", files[1].Header.Get("Content-Type"))
	}
	handle, _ := files[0].Open()
	content, _ := io.ReadAll(handle)
	if string(content) != "%PDF-uno" {
		t.Errorf("contenido: %q", content)
	}
}

func TestSessionEstimationErrors(t *testing.T) {
	call := func(api *fakeAPI) error {
		_, err := NewSessionsClient(api.settings()).CreateSessionEstimation(context.Background(), sessionID, []Field{{"transcript", "x"}}, nil)
		return err
	}

	api := newFakeAPI(t, 404, `{"detail":"Session not found or expired"}`)
	typed := mustKind(t, call(api), SessionExpired)
	if typed.Message != SessionExpiredMessage || typed.Status != 404 || !typed.IsA(NotFound) {
		t.Errorf("sesión caducada: %+v", typed)
	}

	for _, tc := range []struct {
		status int
		detail string
	}{
		{422, "No se pudo extraer texto de «escaneado.pdf» (¿está escaneado o vacío?)."},
		{415, "Tipo de archivo no admitido."},
		{413, "El adjunto supera el máximo."},
	} {
		payload, _ := json.Marshal(map[string]string{"detail": tc.detail})
		api = newFakeAPI(t, tc.status, string(payload))
		if got := mustKind(t, call(api), InvalidRequest); got.Message != tc.detail || got.Status != tc.status {
			t.Errorf("estado %d: %+v", tc.status, got)
		}
	}

	api = newFakeAPI(t, 413, `<html>nginx</html>`)
	if got := mustKind(t, call(api), InvalidRequest); got.Message != RejectedMessage {
		t.Errorf("sin detail de texto: %q", got.Message)
	}
	api = newFakeAPI(t, 400, `{"reason":"pii_email","message":"Elimina el correo."}`)
	if got := mustKind(t, call(api), GuardrailViolation); got.Message != "Elimina el correo." || got.Status != 400 {
		t.Errorf("guardrail: %+v", got)
	}
	for _, body := range []string{`{"unexpected":true}`, `{"result":{},"project_metadata":{}}`, `{"result":{},"project_metadata":{"mentioned_technologies":"x"}}`} {
		api = newFakeAPI(t, 200, body)
		mustKind(t, call(api), InvalidResponse)
	}
}

func TestSessionIDIsEscapedInThePath(t *testing.T) {
	api := newFakeAPI(t, 200, estimateOK)
	if _, err := NewSessionsClient(api.settings()).CreateSessionEstimation(context.Background(), "a/b", nil, nil); err != nil {
		t.Fatal(err)
	}
	if api.last().path != "/api/v1/sessions/a%2Fb/estimate" {
		t.Errorf("ruta: %s", api.last().path)
	}
}

func TestCompareChunkingSendsCorpusAndReturnsPayload(t *testing.T) {
	api := newFakeAPI(t, 200, `{"stats_per_strategy":{"structural":{"n_chunks":10}},"queries_per_strategy":{}}`)
	payload, err := NewEmbeddingsClient(api.settings()).CompareChunking(context.Background(), Budgets(), []string{"oauth"}, []string{"structural"}, 2)
	if err != nil {
		t.Fatal(err)
	}
	var sent struct {
		Budgets    []json.RawMessage `json:"budgets"`
		Queries    []string          `json:"queries"`
		Strategies []string          `json:"strategies"`
		TopK       int               `json:"top_k"`
	}
	if err := json.Unmarshal(api.last().body, &sent); err != nil {
		t.Fatal(err)
	}
	if len(sent.Budgets) != len(Budgets()) || sent.Queries[0] != "oauth" || sent.Strategies[0] != "structural" || sent.TopK != 2 {
		t.Errorf("cuerpo enviado inesperado: %d presupuestos, %v %v %d", len(sent.Budgets), sent.Queries, sent.Strategies, sent.TopK)
	}
	if api.last().path != "/embeddings/compare" || !strings.Contains(string(payload), "stats_per_strategy") {
		t.Errorf("ruta %s, respuesta %s", api.last().path, payload)
	}

	if _, err := NewEmbeddingsClient(api.settings()).CompareChunking(context.Background(), nil, nil, nil, 3); err == nil {
		t.Error("sin presupuestos debe fallar")
	}
	api.body = `{"otro":1}`
	_, err = NewEmbeddingsClient(api.settings()).CompareChunking(context.Background(), Budgets(), nil, nil, 3)
	mustKind(t, err, InvalidResponse)
	if !strings.Contains(string(api.last().body), `"queries":[]`) || !strings.Contains(string(api.last().body), `"strategies":[]`) {
		t.Error("las listas vacías deben enviarse como [] y no como null")
	}
}

func TestEmbeddedCorpus(t *testing.T) {
	if got := len(Budgets()); got != 18 {
		t.Errorf("se esperaban 18 presupuestos (15 + 3 casos límite), hay %d", got)
	}
	if len(SampleQueries()) == 0 {
		t.Error("faltan las consultas de referencia")
	}
}

func TestConfigClientRoundTrip(t *testing.T) {
	api := newFakeAPI(t, 200, `{"models":{"primary_model":{"effective":"gpt-4o","default":"gpt-4o-mini","overridden":true}},"available_models":["gpt-4o"]}`)
	client := NewConfigClient(api.settings())
	doc, err := client.Models(context.Background())
	if err != nil || doc.Doc("models").Doc("primary_model").S("effective") != "gpt-4o" {
		t.Fatalf("%v %v", doc, err)
	}
	value := "gpt-4o"
	if _, err := client.UpdateModels(context.Background(), map[string]*string{"primary_model": &value, "critic_model": nil}); err != nil {
		t.Fatal(err)
	}
	var sent map[string]map[string]*string
	_ = json.Unmarshal(api.last().body, &sent)
	if api.last().method != "PUT" || sent["models"]["primary_model"] == nil || sent["models"]["critic_model"] != nil {
		t.Errorf("cuerpo enviado: %s", api.last().body)
	}
	if _, err := client.UpdateModels(context.Background(), nil); err == nil {
		t.Error("un cambio vacío debe fallar sin llamar a la API")
	}
	api.body = `{"x":1}`
	_, err = client.Models(context.Background())
	mustKind(t, err, InvalidResponse)
}

func TestTimeoutsAreIndependentPerClient(t *testing.T) {
	var calls atomic.Int32
	slow := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		time.Sleep(150 * time.Millisecond)
		_, _ = io.WriteString(w, `{"stats_per_strategy":{}}`)
	}))
	defer slow.Close()
	base := Settings{BaseURL: slow.URL, OpenTimeout: time.Second, ReadTimeout: 30 * time.Millisecond}

	_, err := NewEmbeddingsClient(base).CompareChunking(context.Background(), Budgets(), nil, nil, 3)
	mustKind(t, err, RequestTimeout)
	if _, err := NewEmbeddingsClient(base.WithTimeouts(0, 2*time.Second)).CompareChunking(context.Background(), Budgets(), nil, nil, 3); err != nil {
		t.Errorf("con el tiempo ampliado debe responder: %v", err)
	}
	if base.ReadTimeout != 30*time.Millisecond {
		t.Error("WithTimeouts no debe modificar el original")
	}
}
