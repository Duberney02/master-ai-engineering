package estimatorai

import (
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
	"unicode/utf8"

	"estimator-web/internal/jsondoc"
)

// maxResponseBytes acota lo que se lee de la API (una estimación o una comparación caben de sobra).
const maxResponseBytes = 64 << 20

// Settings es la configuración de conexión con la API de IA.
type Settings struct {
	BaseURL     string
	OpenTimeout time.Duration
	ReadTimeout time.Duration
}

// WithTimeouts devuelve una copia con otros tiempos de espera (cero conserva el valor actual). Cada cliente crea su
// propia conexión: el tiempo ampliado del Chunking Lab no afecta al resto de flujos.
func (s Settings) WithTimeouts(open, read time.Duration) Settings {
	if open > 0 {
		s.OpenTimeout = open
	}
	if read > 0 {
		s.ReadTimeout = read
	}
	return s
}

type baseClient struct {
	baseURL string
	http    *http.Client
}

func newBase(settings Settings) baseClient {
	transport := &http.Transport{
		DialContext:           (&net.Dialer{Timeout: settings.OpenTimeout}).DialContext,
		TLSHandshakeTimeout:   settings.OpenTimeout,
		ResponseHeaderTimeout: settings.ReadTimeout,
		MaxIdleConns:          10,
		IdleConnTimeout:       60 * time.Second,
	}
	return baseClient{
		baseURL: strings.TrimRight(settings.BaseURL, "/"),
		http:    &http.Client{Transport: transport, Timeout: settings.ReadTimeout},
	}
}

// requestOptions describe una llamada. `history`: un 503 significa «historial no disponible». `session`: un 404
// significa «sesión caducada» y los rechazos de adjuntos (413/415/422) traen un `detail` redactado por la API.
// `detail`: los `detail` de texto de la API (configuración, embeddings) se muestran tal cual; los redacta el servicio
// sin datos del usuario.
type requestOptions struct {
	query       url.Values
	body        io.Reader
	contentType string
	history     bool
	session     bool
	detail      bool
	expected    int
}

func (b baseClient) request(ctx context.Context, method, path string, opts requestOptions) (any, error) {
	target := b.baseURL + path
	if len(opts.query) > 0 {
		target += "?" + opts.query.Encode()
	}
	request, err := http.NewRequestWithContext(ctx, method, target, opts.body)
	if err != nil {
		return nil, newError(ServerError, ServerMessage, 0)
	}
	request.Header.Set("Accept", "application/json")
	if opts.contentType != "" {
		request.Header.Set("Content-Type", opts.contentType)
	}

	response, err := b.http.Do(request)
	if err != nil {
		return nil, connectionError(err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(io.LimitReader(response.Body, maxResponseBytes))
	if err != nil {
		return nil, connectionError(err)
	}
	return b.handle(response.StatusCode, body, opts)
}

// connectionError traduce un fallo de transporte sin exponer la URL ni el detalle de red.
func connectionError(err error) *Error {
	var netErr net.Error
	switch {
	case errors.Is(err, context.DeadlineExceeded), errors.As(err, &netErr) && netErr.Timeout():
		return newError(RequestTimeout, ConnectionMessage, 0)
	case errors.Is(err, context.Canceled):
		return newError(ConnectionFailed, ConnectionMessage, 0)
	}
	var urlErr *url.Error
	if errors.As(err, &urlErr) || errors.As(err, &netErr) {
		return newError(ConnectionFailed, ConnectionMessage, 0)
	}
	return newError(ServerError, ServerMessage, 0)
}

func (b baseClient) handle(status int, body []byte, opts requestOptions) (any, error) {
	expected := opts.expected
	if expected == 0 {
		expected = http.StatusOK
	}
	if status == expected {
		return parse(body)
	}
	if opts.session && status == http.StatusNotFound {
		return nil, newError(SessionExpired, SessionExpiredMessage, http.StatusNotFound)
	}
	return nil, errorFor(status, body, opts)
}

func errorFor(status int, body []byte, opts requestOptions) *Error {
	if opts.session && (status == 413 || status == 415 || status == 422) {
		fallback := RejectedMessage
		if status == 422 {
			fallback = ValidationMessage
		}
		return newError(InvalidRequest, orDefault(detailMessage(body), fallback), status)
	}
	if opts.detail {
		return detailErrorFor(status, body)
	}
	switch {
	case status == 400:
		return newError(GuardrailViolation, orDefault(textField(body, "message"), RejectedMessage), status)
	case status == 404:
		return newError(NotFound, NotFoundMessage, status)
	case status == 422:
		return newError(InvalidRequest, ValidationMessage, status)
	case status == 503 && opts.history:
		return newError(ServiceUnavailable, HistoryUnavailableMessage, status)
	case status == 503:
		return newError(ServiceUnavailable, ServerMessage, status)
	case status >= 500 && status <= 599:
		return newError(ServerError, ServerMessage, status)
	}
	return newError(InvalidRequest, RejectedMessage, status)
}

func detailErrorFor(status int, body []byte) *Error {
	message := detailMessage(body)
	switch {
	case status == 400 || status == 422:
		fallback := RejectedMessage
		if status == 422 {
			fallback = ValidationMessage
		}
		return newError(InvalidRequest, orDefault(message, fallback), status)
	case status == 404:
		return newError(NotFound, orDefault(message, RejectedMessage), status)
	case status == 503:
		return newError(ServiceUnavailable, orDefault(message, ServerMessage), status)
	case status >= 500 && status <= 599:
		return newError(ServerError, orDefault(message, ServerMessage), status)
	}
	return newError(InvalidRequest, RejectedMessage, status)
}

// detailMessage: los `detail` de texto los redacta la API sin datos del usuario.
func detailMessage(body []byte) string { return textField(body, "detail") }

// textField lee un campo de texto no vacío de un cuerpo objeto JSON, acotado a MessageLimit caracteres.
func textField(body []byte, key string) string {
	value, err := jsondoc.Parse(body)
	if err != nil {
		return ""
	}
	text, ok := jsondoc.From(value).Get(key).(string)
	if !ok || strings.TrimSpace(text) == "" {
		return ""
	}
	return truncateRunes(text, MessageLimit)
}

func truncateRunes(text string, limit int) string {
	if utf8.RuneCountInString(text) <= limit {
		return text
	}
	return string([]rune(text)[:limit])
}

func orDefault(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

func parse(body []byte) (any, error) {
	value, err := jsondoc.Parse(body)
	if err != nil {
		return nil, newError(InvalidResponse, InvalidResponseMessage, 0)
	}
	return value, nil
}

// expectDoc exige un objeto cuya clave `key` sea otro objeto (p. ej. `result`).
func expectDoc(body any, key string) (jsondoc.Doc, error) {
	doc := jsondoc.From(body)
	if doc == nil || doc.Doc(key) == nil {
		return nil, newError(InvalidResponse, InvalidResponseMessage, 0)
	}
	return doc, nil
}

func invalidResponse() *Error { return newError(InvalidResponse, InvalidResponseMessage, 0) }
