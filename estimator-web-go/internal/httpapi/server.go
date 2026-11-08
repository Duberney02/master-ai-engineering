// Package httpapi es la capa de transporte del servicio: un API JSON bajo `/api/` más `GET /up`.
//
// Los handlers solo hacen de transporte: validan parámetros, llaman al cliente de su contexto y traducen los errores
// tipados a `{"detail": "..."}` con un estado HTTP adecuado. La lógica vive en los paquetes de contexto. No hay HTML,
// cookies ni CSRF: los clientes (React y Streamlit) conservan su propio `conversation_id`.
package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"runtime/debug"
	"sync"
	"time"

	"estimator-web/internal/config"
	"estimator-web/internal/estimatorai"
	"estimator-web/internal/rag"
)

// maxBodyBytes acota el cuerpo de una petición: cinco adjuntos de 10 MB más el resto del formulario.
const maxBodyBytes = 64 << 20

// Server reúne las dependencias de los handlers.
type Server struct {
	cfg         config.Config
	log         *slog.Logger
	estimations *estimatorai.EstimationsClient
	chats       *estimatorai.SessionsClient
	compare     *estimatorai.EmbeddingsClient // con el tiempo de espera ampliado: solo lo usa el Chunking Lab
	models      *estimatorai.ConfigClient
	badge       *badgeCache
	store       rag.Store
}

// New construye el servidor. `store` puede ser nil (sin base de datos): el Chunking Lab degrada como con un fallo de BD.
func New(cfg config.Config, store rag.Store, logger *slog.Logger) *Server {
	if logger == nil {
		logger = slog.New(slog.NewTextHandler(io.Discard, nil))
	}
	settings := estimatorai.Settings{BaseURL: cfg.APIURL, OpenTimeout: cfg.OpenTimeout, ReadTimeout: cfg.ReadTimeout}
	badgeSettings := settings.WithTimeouts(cfg.BadgeTimeout, cfg.BadgeTimeout)
	server := &Server{
		cfg:         cfg,
		log:         logger,
		estimations: estimatorai.NewEstimationsClient(settings),
		chats:       estimatorai.NewSessionsClient(settings),
		compare:     estimatorai.NewEmbeddingsClient(settings.WithTimeouts(0, cfg.CompareTimeout)),
		models:      estimatorai.NewConfigClient(settings),
		store:       store,
	}
	badgeClient := estimatorai.NewConfigClient(badgeSettings)
	server.badge = newBadgeCache(15*time.Second, time.Now, func(ctx context.Context) string {
		models, err := badgeClient.Models(ctx)
		if err != nil {
			return ""
		}
		return models.Doc("models").Doc("primary_model").S("effective")
	})
	return server
}

// Handler devuelve las rutas del servicio, con recuperación de pánicos, límite de cuerpo y registro.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /up", s.health)

	// Contexto «estimaciones» y conversación.
	mux.HandleFunc("POST /api/conversations", s.conversationCreate)
	mux.HandleFunc("POST /api/conversations/{id}/estimations", s.estimationCreate)
	mux.HandleFunc("GET /api/estimations", s.estimationsIndex)
	mux.HandleFunc("GET /api/estimations/{id}", s.estimationsShow)
	mux.HandleFunc("GET /api/prompt-preview", s.promptPreview)

	// Contexto «RAG»: comparación de estrategias de chunking con historial persistido.
	mux.HandleFunc("GET /api/chunking-comparisons/options", s.labOptions)
	mux.HandleFunc("GET /api/chunking-comparisons", s.labIndex)
	mux.HandleFunc("POST /api/chunking-comparisons", s.labCreate)
	mux.HandleFunc("GET /api/chunking-comparisons/{id}", s.labShow)

	// Ajustes del servicio IA: modelos del LLM en tiempo de ejecución.
	mux.HandleFunc("GET /api/ai-settings", s.settingsShow)
	mux.HandleFunc("PUT /api/ai-settings", s.settingsUpdate)
	mux.HandleFunc("GET /api/primary-model", s.primaryModel)

	mux.HandleFunc("/", s.notFound)
	return s.recoverer(s.logging(s.limitBody(mux)))
}

func (s *Server) limitBody(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Body != nil {
			r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
		}
		next.ServeHTTP(w, r)
	})
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(status int) {
	r.status = status
	r.ResponseWriter.WriteHeader(status)
}

func (s *Server) logging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		started := time.Now()
		recorder := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(recorder, r)
		if r.URL.Path == "/up" {
			return
		}
		// Sin cadena de consulta ni parámetros: pueden llevar datos del usuario.
		s.log.Info("request", "method", r.Method, "path", r.URL.Path, "status", recorder.status, "duration_ms", time.Since(started).Milliseconds())
	})
}

func (s *Server) recoverer(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if recovered := recover(); recovered != nil && recovered != http.ErrAbortHandler {
				s.log.Error("panic", "path", r.URL.Path, "error_type", fmt.Sprintf("%T", recovered), "stack", string(debug.Stack()))
				writeDetail(w, http.StatusInternalServerError, "Error interno del servicio. Inténtalo de nuevo.")
			}
		}()
		next.ServeHTTP(w, r)
	})
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	_, _ = io.WriteString(w, "ok\n")
}

func (s *Server) notFound(w http.ResponseWriter, r *http.Request) {
	writeDetail(w, http.StatusNotFound, "Recurso no encontrado.")
}

// --- Respuestas JSON ---

func writeJSON(w http.ResponseWriter, status int, body any) {
	encoded, err := json.Marshal(body)
	if err != nil {
		writeDetail(w, http.StatusInternalServerError, "Error interno del servicio. Inténtalo de nuevo.")
		return
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_, _ = w.Write(encoded)
}

// writeDetail responde el error JSON `{"detail": "<mensaje saneado>"}`.
func writeDetail(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

// statusFor traduce un error tipado de la API de IA a su estado HTTP.
func statusFor(err error) int {
	switch {
	case estimatorai.IsKind(err, estimatorai.InvalidRequest), estimatorai.IsKind(err, estimatorai.GuardrailViolation):
		return http.StatusUnprocessableEntity
	case estimatorai.IsKind(err, estimatorai.NotFound):
		return http.StatusNotFound
	case estimatorai.IsKind(err, estimatorai.RequestTimeout):
		return http.StatusGatewayTimeout
	case estimatorai.IsKind(err, estimatorai.ConnectionFailed), estimatorai.IsKind(err, estimatorai.ServiceUnavailable):
		return http.StatusServiceUnavailable
	}
	return http.StatusBadGateway
}

// writeAPIError responde el error de la API de IA con su mensaje saneado (el de `estimatorai`, nunca un cuerpo crudo).
func (s *Server) writeAPIError(w http.ResponseWriter, err error) {
	if typed, ok := estimatorai.As(err); ok {
		writeDetail(w, statusFor(err), typed.Message)
		return
	}
	s.log.Error("error_inesperado", "error_type", fmt.Sprintf("%T", err))
	writeDetail(w, http.StatusBadGateway, estimatorai.ServerMessage)
}

// --- Indicador del modelo primario ---

// badgeCache guarda unos segundos el modelo primario vigente (a lo sumo una llamada HTTP cada `ttl`). Es pura
// decoración: si el servicio no responde, devuelve "" y el cliente omite el indicador. Un servicio caído nunca debe
// retrasar la respuesta; el fallo también se cachea para no reintentar en cada petición.
type badgeCache struct {
	mu      sync.Mutex
	ttl     time.Duration
	now     func() time.Time
	fetch   func(context.Context) string
	value   string
	expires time.Time
}

func newBadgeCache(ttl time.Duration, now func() time.Time, fetch func(context.Context) string) *badgeCache {
	return &badgeCache{ttl: ttl, now: now, fetch: fetch}
}

// Get devuelve el modelo primario ("" si no se pudo leer).
func (b *badgeCache) Get(ctx context.Context) string {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.now().Before(b.expires) {
		return b.value
	}
	b.value = b.fetch(ctx)
	b.expires = b.now().Add(b.ttl)
	return b.value
}

// Invalidate descarta el valor: la siguiente consulta vuelve a preguntar al servicio.
func (b *badgeCache) Invalidate() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.expires = time.Time{}
}

var errNoStore = errors.New("httpapi: sin base de datos para el historial")
