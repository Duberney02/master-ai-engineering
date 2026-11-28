package estimatorai

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"mime"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"time"
	"unicode/utf8"
)

// PublicClient contiene exclusivamente las operaciones públicas de IA.
type PublicClient struct {
	session       baseClient
	regular       baseClient
	long          baseClient
	probe         baseClient
	structured    baseClient
	transcription baseClient
}

type PublicTimeouts struct {
	Connection, RegularHeaders, RegularTotal, LongHeaders, LongTotal, Probe time.Duration
	StructuredTotal, TranscriptionTotal                                     time.Duration
}

func NewPublicClient(baseURL string, t PublicTimeouts) *PublicClient {
	makeClient := func(headers, total time.Duration) baseClient {
		b := newBase(Settings{BaseURL: baseURL, OpenTimeout: t.Connection, ReadTimeout: total})
		transport := b.http.Transport.(*http.Transport)
		transport.ResponseHeaderTimeout = headers
		b.http.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
		return b
	}
	session := makeClient(t.RegularHeaders, t.RegularTotal)
	// El POST sin cuerpo no usa conexiones reutilizadas para evitar reintentos de transporte.
	session.http.Transport.(*http.Transport).DisableKeepAlives = true
	return &PublicClient{
		session:       session,
		regular:       makeClient(t.RegularHeaders, t.RegularTotal),
		long:          makeClient(t.LongHeaders, t.LongTotal),
		probe:         makeClient(t.Probe, t.Probe),
		structured:    makeClient(t.LongHeaders, t.StructuredTotal),
		transcription: makeClient(t.LongHeaders, t.TranscriptionTotal),
	}
}

type ReferenceProject struct {
	Name        string  `json:"name"`
	Description string  `json:"description"`
	ActualHours float64 `json:"actual_hours"`
}

type EstimateInput struct {
	Description       string          `json:"description"`
	ProjectType       string          `json:"project_type"`
	DetailLevel       string          `json:"detail_level"`
	OutputFormat      string          `json:"output_format"`
	ReferenceProjects json.RawMessage `json:"reference_projects,omitempty"`
}

// Response retiene los campos aditivos y los nulos del servicio tras validar la forma esperada.
type Response = json.RawMessage

var uuid4 = regexp.MustCompile(`(?i)^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

func (c *PublicClient) CreateSession(ctx context.Context) (Response, error) {
	return c.session.publicJSON(ctx, "POST", "/api/v1/sessions", nil, nil, "", 201, func(data []byte) bool {
		return object(fields{"session_id": func(raw json.RawMessage) bool {
			var value string
			return json.Unmarshal(raw, &value) == nil && uuid4.MatchString(value)
		}}, nil)(data)
	})
}

func (c *PublicClient) Estimate(ctx context.Context, version string, input EstimateInput) (Response, error) {
	data, err := json.Marshal(input)
	if err != nil {
		return nil, invalidResponse()
	}
	return c.long.publicJSON(ctx, "POST", "/api/v1/estimate", url.Values{"prompt_version": {version}}, bytes.NewReader(data), "application/json", 200, validEstimate)
}

func (c *PublicClient) Turn(ctx context.Context, id string, body io.Reader, mimeType string) (Response, error) {
	return c.long.publicJSON(ctx, "POST", "/api/v1/sessions/"+url.PathEscape(id)+"/estimate", nil, body, mimeType, 200, func(data []byte) bool {
		return validTurnResponse(data, id)
	})
}

func (c *PublicClient) Preview(ctx context.Context, query url.Values) (Response, error) {
	return c.regular.publicJSON(ctx, "GET", "/api/v1/prompts/estimation", query, nil, "", 200, func(data []byte) bool {
		return previewResponse(data)
	})
}

func (c *PublicClient) History(ctx context.Context, limit int) (Response, error) {
	return c.regular.publicJSON(ctx, "GET", "/api/v1/estimations", url.Values{"limit": {strconv.Itoa(limit)}}, nil, "", 200, func(data []byte) bool {
		return historyResponse(data)
	})
}

func (c *PublicClient) Detail(ctx context.Context, id int64) (Response, error) {
	return c.regular.publicJSON(ctx, "GET", "/api/v1/estimations/"+strconv.FormatInt(id, 10), nil, nil, "", 200, func(data []byte) bool {
		return detailResponse(data) && object(fields{"id": integer(id, id)}, nil)(data)
	})
}

func (c *PublicClient) Health(ctx context.Context) (Response, error) {
	return c.probe.publicJSON(ctx, "GET", "/health", nil, nil, "", 200, func(data []byte) bool {
		return healthResponse(data)
	})
}

func (b baseClient) publicRequest(ctx context.Context, method, path string, query url.Values, body io.Reader, contentType, accept string) (*http.Response, error) {
	target := b.baseURL + path
	if len(query) > 0 {
		target += "?" + query.Encode()
	}
	req, err := http.NewRequestWithContext(ctx, method, target, body)
	if err != nil {
		return nil, invalidResponse()
	}
	req.GetBody = nil
	req.Header.Set("Accept", accept)
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	response, err := b.http.Do(req)
	if err != nil {
		return nil, connectionError(err)
	}
	return response, nil
}

func (b baseClient) publicJSON(ctx context.Context, method, path string, query url.Values, body io.Reader, contentType string, status int, valid func([]byte) bool) (Response, error) {
	res, err := b.publicRequest(ctx, method, path, query, body, contentType, "application/json")
	if err != nil {
		return nil, err
	}
	defer res.Body.Close()
	if res.StatusCode != status {
		return nil, publicError(res)
	}
	kind, _, _ := mime.ParseMediaType(res.Header.Get("Content-Type"))
	if kind != "application/json" {
		return nil, invalidResponse()
	}
	data, err := io.ReadAll(io.LimitReader(res.Body, maxResponseBytes+1))
	if err != nil {
		return nil, connectionError(err)
	}
	if len(data) > maxResponseBytes || !utf8.Valid(data) || !valid(data) {
		return nil, invalidResponse()
	}
	return Response(data), nil
}

func publicError(res *http.Response) *Error {
	switch status := res.StatusCode; status {
	case 400:
		body, _ := io.ReadAll(io.LimitReader(res.Body, 8192))
		reason := textField(body, "reason")
		if message, ok := guardrailMessages[reason]; ok {
			return &Error{Kind: GuardrailViolation, Message: message, Status: status, Reason: reason}
		}
		return newError(InvalidRequest, RejectedMessage, status)
	case 404:
		return newError(NotFound, NotFoundMessage, status)
	case 413, 415, 422:
		return newError(InvalidRequest, ValidationMessage, status)
	case 429, 503:
		return newError(ServiceUnavailable, ServerMessage, status)
	case 504:
		return newError(RequestTimeout, ConnectionMessage, status)
	default:
		return newError(InvalidResponse, InvalidResponseMessage, 502)
	}
}

var guardrailMessages = map[string]string{
	"moderation":       "El contenido no es apropiado para una estimación. Reformula la descripción.",
	"prompt_injection": "La descripción parece contener instrucciones dirigidas al modelo. Describe solo el proyecto que quieres estimar.",
	"pii_email":        "La descripción contiene una dirección de correo electrónico. Elimínala.",
	"pii_phone":        "La descripción contiene un número de teléfono. Elimínalo.",
	"pii_iban":         "La descripción contiene un IBAN. Elimínalo.",
}
