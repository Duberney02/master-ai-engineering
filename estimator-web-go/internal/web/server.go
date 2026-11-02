// Package web es la capa de transporte del servicio: rutas, handlers, plantillas HTML y la sesión del navegador.
//
// Los handlers solo hacen de transporte: validan parámetros, llaman al cliente de su contexto, traducen los errores
// tipados a avisos con un estado HTTP adecuado y persisten el payload. La lógica vive en los paquetes de contexto.
package web

import (
	"bytes"
	"context"
	"embed"
	"errors"
	"fmt"
	"html/template"
	"io"
	"io/fs"
	"log/slog"
	"net/http"
	"runtime/debug"
	"strings"
	"sync"
	"time"

	"estimator-web/internal/config"
	"estimator-web/internal/estimatorai"
	"estimator-web/internal/jsondoc"
	"estimator-web/internal/rag"
	"estimator-web/internal/session"
)

//go:embed templates/*.html
var templateFiles embed.FS

//go:embed public/*
var publicFiles embed.FS

// maxBodyBytes acota el cuerpo de una petición: cinco adjuntos de 10 MB más el resto del formulario.
const maxBodyBytes = 64 << 20

// Server reúne las dependencias de los handlers.
type Server struct {
	cfg         config.Config
	log         *slog.Logger
	sessions    *session.Manager
	estimations *estimatorai.EstimationsClient
	chats       *estimatorai.SessionsClient
	compare     *estimatorai.EmbeddingsClient // con el tiempo de espera ampliado: solo lo usa el Chunking Lab
	models      *estimatorai.ConfigClient
	badge       *badgeCache
	store       rag.Store
	pages       map[string]*template.Template
}

// New construye el servidor. `store` puede ser nil (sin base de datos): el Chunking Lab degrada como con un fallo de BD.
func New(cfg config.Config, store rag.Store, logger *slog.Logger) (*Server, error) {
	if logger == nil {
		logger = slog.New(slog.NewTextHandler(io.Discard, nil))
	}
	settings := estimatorai.Settings{BaseURL: cfg.APIURL, OpenTimeout: cfg.OpenTimeout, ReadTimeout: cfg.ReadTimeout}
	badgeSettings := settings.WithTimeouts(cfg.BadgeTimeout, cfg.BadgeTimeout)
	pages, err := loadPages()
	if err != nil {
		return nil, err
	}
	server := &Server{
		cfg:         cfg,
		log:         logger,
		sessions:    session.NewManager(cfg.SecretKeyBase),
		estimations: estimatorai.NewEstimationsClient(settings),
		chats:       estimatorai.NewSessionsClient(settings),
		compare:     estimatorai.NewEmbeddingsClient(settings.WithTimeouts(0, cfg.CompareTimeout)),
		models:      estimatorai.NewConfigClient(settings),
		store:       store,
		pages:       pages,
	}
	badgeClient := estimatorai.NewConfigClient(badgeSettings)
	server.badge = newBadgeCache(15*time.Second, time.Now, func(ctx context.Context) string {
		models, err := badgeClient.Models(ctx)
		if err != nil {
			return ""
		}
		return models.Doc("models").Doc("primary_model").S("effective")
	})
	return server, nil
}

// handler es un handler con la sesión del navegador ya cargada.
type handler func(w http.ResponseWriter, r *http.Request, sess *session.Session)

// Handler devuelve las rutas del servicio, con recuperación de pánicos, límite de cuerpo, `_method` y registro.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /up", s.health)
	mux.HandleFunc("GET /robots.txt", s.staticFile("public/robots.txt", "text/plain; charset=utf-8"))
	for _, page := range []string{"404", "422", "500"} {
		mux.HandleFunc("GET /"+page+".html", s.staticFile("public/"+page+".html", "text/html; charset=utf-8"))
	}

	// Inicio: un panel con una tarjeta por contexto (estimaciones, Chunking Lab, Ajustes).
	mux.HandleFunc("GET /{$}", s.route(s.home))

	// Contexto «estimaciones».
	mux.HandleFunc("GET /estimations/new", s.route(s.estimationsNew))
	mux.HandleFunc("GET /estimations", s.route(s.estimationsIndex))
	mux.HandleFunc("POST /estimations", s.route(s.estimationsCreate))
	mux.HandleFunc("GET /estimations/{id}", s.route(s.estimationsShow))
	// «Nueva conversación»: abre otra sesión en la API y reinicia el estado.
	mux.HandleFunc("POST /conversation", s.route(s.conversationCreate))

	// Contexto «RAG» (Sesión 7): comparación de estrategias de chunking con historial persistido.
	mux.HandleFunc("GET /rag/chunking_comparisons", s.route(s.labIndex))
	mux.HandleFunc("GET /rag/chunking_comparisons/new", s.route(s.labNew))
	mux.HandleFunc("POST /rag/chunking_comparisons", s.route(s.labCreate))
	mux.HandleFunc("GET /rag/chunking_comparisons/{id}", s.route(s.labShow))

	// Ajustes del servicio IA: modelos del LLM en tiempo de ejecución.
	mux.HandleFunc("GET /ai_settings", s.route(s.settingsShow))
	mux.HandleFunc("PATCH /ai_settings", s.route(s.settingsUpdate))
	mux.HandleFunc("PUT /ai_settings", s.route(s.settingsUpdate))

	mux.HandleFunc("/", s.notFound)
	return s.recoverer(s.logging(s.methodOverride(mux)))
}

// route carga la sesión y exige el token CSRF en las peticiones que cambian estado.
func (s *Server) route(next handler) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		sess := s.sessions.Load(r)
		if !safeMethod(r.Method) {
			token := r.PostForm.Get("authenticity_token")
			if token == "" {
				token = r.Header.Get("X-CSRF-Token")
			}
			if !sess.VerifyCSRF(token) {
				s.log.Warn("csrf_rejected", "method", r.Method, "path", r.URL.Path)
				s.servePublicPage(w, http.StatusUnprocessableEntity, "public/422.html")
				return
			}
		}
		next(w, r, sess)
	}
}

func safeMethod(method string) bool {
	return method == http.MethodGet || method == http.MethodHead || method == http.MethodOptions
}

// methodOverride interpreta `_method` en los formularios POST (Rails: PATCH, PUT, DELETE) y deja el formulario
// analizado para los handlers.
func (s *Server) methodOverride(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost || r.Method == http.MethodPatch || r.Method == http.MethodPut || r.Method == http.MethodDelete {
			r.Body = http.MaxBytesReader(w, r.Body, maxBodyBytes)
			if err := parseForm(r); err != nil {
				s.log.Warn("form_rejected", "path", r.URL.Path, "error_type", fmt.Sprintf("%T", err))
				http.Error(w, "La solicitud es demasiado grande o no es válida.", http.StatusRequestEntityTooLarge)
				return
			}
			if r.Method == http.MethodPost {
				switch strings.ToLower(r.PostForm.Get("_method")) {
				case "patch":
					r.Method = http.MethodPatch
				case "put":
					r.Method = http.MethodPut
				case "delete":
					r.Method = http.MethodDelete
				}
			}
		}
		next.ServeHTTP(w, r)
	})
}

func parseForm(r *http.Request) error {
	if strings.HasPrefix(r.Header.Get("Content-Type"), "multipart/form-data") {
		return r.ParseMultipartForm(maxBodyBytes)
	}
	return r.ParseForm()
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
				s.servePublicPage(w, http.StatusInternalServerError, "public/500.html")
			}
		}()
		next.ServeHTTP(w, r)
	})
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	_, _ = io.WriteString(w, `<!DOCTYPE html><html><body style="background-color: green"></body></html>`)
}

func (s *Server) staticFile(name, contentType string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		content, err := fs.ReadFile(publicFiles, name)
		if err != nil {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", contentType)
		_, _ = w.Write(content)
	}
}

// servePublicPage responde con una de las páginas de error estáticas.
func (s *Server) servePublicPage(w http.ResponseWriter, status int, name string) {
	content, err := fs.ReadFile(publicFiles, name)
	if err != nil {
		http.Error(w, http.StatusText(status), status)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(status)
	_, _ = w.Write(content)
}

func (s *Server) notFound(w http.ResponseWriter, r *http.Request) {
	s.servePublicPage(w, http.StatusNotFound, "public/404.html")
}

// --- Renderizado ---

// view son los datos comunes a todas las pantallas; `Data` lleva los de cada una.
type view struct {
	Title        string
	Section      string
	Flashes      []session.Flash
	CSRF         string
	PrimaryModel string
	Sidebar      *sidebar
	Data         any
}

// sidebar es la barra lateral de las pantallas de estimación (como la de Streamlit): prompt de sistema, ejemplos
// few-shot y métricas de la última llamada.
type sidebar struct {
	Preview       jsondoc.Doc // nil si la API no pudo renderizar el prompt
	Metrics       jsondoc.Doc // nil si aún no hay métricas
	PromptVersion string
	Metadata      session.Metadata
}

// HasMetrics indica que hay métricas de una llamada (un objeto vacío también cuenta, como en Rails).
func (s *sidebar) HasMetrics() bool { return s.Metrics != nil }

const defaultTitle = "Estimador de proyectos"

func (s *Server) render(w http.ResponseWriter, r *http.Request, sess *session.Session, status int, page string, v *view) {
	tmpl, ok := s.pages[page]
	if !ok {
		panic("plantilla desconocida: " + page)
	}
	if v.Title == "" {
		v.Title = defaultTitle
	}
	v.Flashes = sess.Flashes()
	v.CSRF = sess.CSRFToken()
	v.PrimaryModel = s.badge.Get(r.Context())

	var body bytes.Buffer
	if err := tmpl.ExecuteTemplate(&body, "layout", v); err != nil {
		s.log.Error("template_failed", "page", page, "error", err.Error())
		sess.Commit(w)
		s.servePublicPage(w, http.StatusInternalServerError, "public/500.html")
		return
	}
	sess.Commit(w)
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(status)
	_, _ = w.Write(body.Bytes())
}

func (s *Server) redirect(w http.ResponseWriter, r *http.Request, sess *session.Session, location string) {
	sess.Commit(w)
	http.Redirect(w, r, location, http.StatusFound)
}

// --- Indicador del modelo primario ---

// badgeCache guarda unos segundos el modelo primario vigente (a lo sumo una llamada HTTP cada `ttl`). Es pura
// decoración: si el servicio no responde, devuelve "" y la barra no muestra nada. Un servicio caído nunca debe impedir
// ni retrasar el renderizado de una página; el fallo también se cachea para no reintentar en cada una.
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

// Invalidate descarta el valor: el siguiente renderizado vuelve a consultar el servicio.
func (b *badgeCache) Invalidate() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.expires = time.Time{}
}

var errNoStore = errors.New("web: sin base de datos para el historial")
