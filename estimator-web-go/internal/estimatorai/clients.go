package estimatorai

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"net/url"
	"strconv"
	"strings"

	"estimator-web/internal/jsondoc"
)

// --- Contexto «estimación transaccional»: estimar, historial y vista previa del prompt ---

// EstimationsClient habla con /api/v1/estimate, /api/v1/estimations y /api/v1/prompts/estimation.
type EstimationsClient struct{ base baseClient }

func NewEstimationsClient(settings Settings) *EstimationsClient {
	return &EstimationsClient{base: newBase(settings)}
}

// CreateEstimation solicita una estimación. Devuelve el cuerpo de la API (con «result», «estimation_id»…).
func (c *EstimationsClient) CreateEstimation(ctx context.Context, attributes map[string]string, promptVersion string) (jsondoc.Doc, error) {
	payload, err := json.Marshal(attributes)
	if err != nil {
		return nil, newError(ServerError, ServerMessage, 0)
	}
	opts := requestOptions{body: bytes.NewReader(payload), contentType: "application/json"}
	if promptVersion != "" {
		opts.query = url.Values{"prompt_version": {promptVersion}}
	}
	body, err := c.base.request(ctx, http.MethodPost, "/api/v1/estimate", opts)
	if err != nil {
		return nil, err
	}
	return expectDoc(body, "result")
}

// ListEstimations devuelve las últimas estimaciones del historial.
func (c *EstimationsClient) ListEstimations(ctx context.Context, limit int) ([]jsondoc.Doc, error) {
	body, err := c.base.request(ctx, http.MethodGet, "/api/v1/estimations", requestOptions{
		query: url.Values{"limit": {strconv.Itoa(limit)}}, history: true,
	})
	if err != nil {
		return nil, err
	}
	items, ok := body.([]any)
	if !ok {
		return nil, invalidResponse()
	}
	docs := make([]jsondoc.Doc, 0, len(items))
	for _, item := range items {
		doc := jsondoc.From(item)
		if doc == nil {
			return nil, invalidResponse()
		}
		docs = append(docs, doc)
	}
	return docs, nil
}

// PromptPreview devuelve el prompt de sistema renderizado y los ejemplos few-shot para unas opciones (barra lateral).
func (c *EstimationsClient) PromptPreview(ctx context.Context, promptVersion, projectType, detailLevel, outputFormat string) (jsondoc.Doc, error) {
	body, err := c.base.request(ctx, http.MethodGet, "/api/v1/prompts/estimation", requestOptions{
		query: url.Values{
			"prompt_version": {promptVersion}, "project_type": {projectType},
			"detail_level": {detailLevel}, "output_format": {outputFormat},
		},
	})
	if err != nil {
		return nil, err
	}
	doc := jsondoc.From(body)
	if _, ok := doc.Get("system_prompt").(string); !ok {
		return nil, invalidResponse()
	}
	return doc, nil
}

// FindEstimation lee una estimación del historial. Un id no numérico es «no encontrada» sin llamar a la API.
func (c *EstimationsClient) FindEstimation(ctx context.Context, id string) (jsondoc.Doc, error) {
	number, err := strconv.Atoi(strings.TrimSpace(id))
	if err != nil {
		return nil, newError(NotFound, NotFoundMessage, http.StatusNotFound)
	}
	body, err := c.base.request(ctx, http.MethodGet, "/api/v1/estimations/"+strconv.Itoa(number), requestOptions{history: true})
	if err != nil {
		return nil, err
	}
	return expectDoc(body, "result")
}

// --- Contexto «conversación»: sesiones con memoria y estimaciones dentro de ellas ---

// SessionsClient habla con /api/v1/sessions.
type SessionsClient struct{ base baseClient }

func NewSessionsClient(settings Settings) *SessionsClient {
	return &SessionsClient{base: newBase(settings)}
}

// Field es un campo de formulario del envío multipart (el orden se conserva).
type Field struct{ Name, Value string }

// Attachment es un archivo subido que se reenvía a la API.
type Attachment struct {
	Filename    string
	ContentType string
	Data        []byte
}

// CreateSession crea una conversación vacía (vive en memoria de la API) y devuelve su `session_id`.
func (c *SessionsClient) CreateSession(ctx context.Context) (string, error) {
	body, err := c.base.request(ctx, http.MethodPost, "/api/v1/sessions", requestOptions{expected: http.StatusCreated})
	if err != nil {
		return "", err
	}
	id, ok := jsondoc.From(body).Get("session_id").(string)
	if !ok {
		return "", invalidResponse()
	}
	return id, nil
}

// CreateSessionEstimation envía una estimación dentro de la conversación. Cada campo va como parte multipart
// explícita: así el cuerpo es siempre `multipart/form-data`, incluso sin adjuntos (la API solo lee formularios).
// Devuelve el cuerpo de la API (con «result», «project_metadata», «estimation_id»…).
func (c *SessionsClient) CreateSessionEstimation(ctx context.Context, sessionID string, fields []Field, attachments []Attachment) (jsondoc.Doc, error) {
	var buffer bytes.Buffer
	writer := multipart.NewWriter(&buffer)
	for _, field := range fields {
		header := textproto.MIMEHeader{}
		header.Set("Content-Disposition", fmt.Sprintf(`form-data; name="%s"`, escapeQuotes(field.Name)))
		header.Set("Content-Type", "text/plain; charset=UTF-8")
		part, err := writer.CreatePart(header)
		if err != nil {
			return nil, newError(ServerError, ServerMessage, 0)
		}
		_, _ = part.Write([]byte(field.Value))
	}
	for _, file := range attachments {
		contentType := file.ContentType
		if contentType == "" {
			contentType = "application/octet-stream"
		}
		header := textproto.MIMEHeader{}
		header.Set("Content-Disposition", fmt.Sprintf(`form-data; name="attachments"; filename="%s"`, escapeQuotes(file.Filename)))
		header.Set("Content-Type", contentType)
		part, err := writer.CreatePart(header)
		if err != nil {
			return nil, newError(ServerError, ServerMessage, 0)
		}
		_, _ = part.Write(file.Data)
	}
	if err := writer.Close(); err != nil {
		return nil, newError(ServerError, ServerMessage, 0)
	}

	body, err := c.base.request(ctx, http.MethodPost, "/api/v1/sessions/"+url.PathEscape(sessionID)+"/estimate", requestOptions{
		body: &buffer, contentType: writer.FormDataContentType(), session: true,
	})
	if err != nil {
		return nil, err
	}
	doc, err := expectDoc(body, "result")
	if err != nil {
		return nil, err
	}
	if !doc.Doc("project_metadata").IsArray("mentioned_technologies") {
		return nil, invalidResponse()
	}
	return doc, nil
}

func escapeQuotes(text string) string {
	return strings.NewReplacer("\\", "\\\\", `"`, "\\\"", "\r", "%0D", "\n", "%0A").Replace(text)
}

// --- Contexto «RAG»: comparación de estrategias de chunking ---

// EmbeddingsClient habla con /embeddings/compare. Las estrategias de pago tardan minutos: la llamada del Chunking Lab
// crea el cliente con su propio tiempo de espera (Settings.WithTimeouts) sin tocar el global.
type EmbeddingsClient struct{ base baseClient }

func NewEmbeddingsClient(settings Settings) *EmbeddingsClient {
	return &EmbeddingsClient{base: newBase(settings)}
}

// CompareChunking llama a POST /embeddings/compare. `budgets` son los presupuestos tal cual (la API los valida con
// Pydantic). Sin `queries` se calculan solo las estadísticas; sin `strategies` la API ejecuta solo las gratuitas.
// Devuelve el cuerpo crudo de la respuesta (se guarda tal cual en el historial).
func (c *EmbeddingsClient) CompareChunking(ctx context.Context, budgets []json.RawMessage, queries, strategies []string, topK int) ([]byte, error) {
	if len(budgets) == 0 {
		return nil, fmt.Errorf("budgets must be a non-empty array")
	}
	payload, err := json.Marshal(struct {
		Budgets    []json.RawMessage `json:"budgets"`
		Queries    []string          `json:"queries"`
		Strategies []string          `json:"strategies"`
		TopK       int               `json:"top_k"`
	}{budgets, nonNil(queries), nonNil(strategies), topK})
	if err != nil {
		return nil, newError(ServerError, ServerMessage, 0)
	}
	body, err := c.base.request(ctx, http.MethodPost, "/embeddings/compare", requestOptions{
		body: bytes.NewReader(payload), contentType: "application/json", detail: true,
	})
	if err != nil {
		return nil, err
	}
	doc := jsondoc.From(body)
	if doc.Doc("stats_per_strategy") == nil {
		return nil, invalidResponse()
	}
	return json.Marshal(doc)
}

func nonNil(values []string) []string {
	if values == nil {
		return []string{}
	}
	return values
}

// --- Contexto «configuración del servicio»: modelos del LLM en tiempo de ejecución ---

// ConfigClient habla con /api/v1/config/models.
type ConfigClient struct{ base baseClient }

func NewConfigClient(settings Settings) *ConfigClient {
	return &ConfigClient{base: newBase(settings)}
}

// Models lee la instantánea: { "models": { knob: { effective, default, overridden } }, "available_models": […], … }.
func (c *ConfigClient) Models(ctx context.Context) (jsondoc.Doc, error) {
	body, err := c.base.request(ctx, http.MethodGet, "/api/v1/config/models", requestOptions{detail: true})
	if err != nil {
		return nil, err
	}
	return expectModels(body)
}

// UpdateModels envía un cambio parcial: un valor nil restablece ese knob a su valor por defecto. La API valida todo
// antes de aplicar nada.
func (c *ConfigClient) UpdateModels(ctx context.Context, changes map[string]*string) (jsondoc.Doc, error) {
	if len(changes) == 0 {
		return nil, fmt.Errorf("changes must be a non-empty hash")
	}
	payload, err := json.Marshal(map[string]any{"models": changes})
	if err != nil {
		return nil, newError(ServerError, ServerMessage, 0)
	}
	body, err := c.base.request(ctx, http.MethodPut, "/api/v1/config/models", requestOptions{
		body: bytes.NewReader(payload), contentType: "application/json", detail: true,
	})
	if err != nil {
		return nil, err
	}
	return expectModels(body)
}

func expectModels(body any) (jsondoc.Doc, error) {
	doc := jsondoc.From(body)
	if doc == nil || doc.Doc("models") == nil {
		return nil, invalidResponse()
	}
	return doc, nil
}
