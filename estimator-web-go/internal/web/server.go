// Package web es la capa de transporte del servicio: la API REST y SSE que consume React, la autorización
// administrativa, la validación de origen de las mutaciones y la sonda `/up`. No sirve HTML de aplicación.
//
// Los handlers solo hacen de transporte: validan parámetros, llaman al cliente de su contexto, traducen los errores
// tipados a respuestas JSON con un estado HTTP adecuado y persisten el payload. La lógica vive en los paquetes de contexto.
package web

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"runtime/debug"
	"strings"
	"sync"
	"time"

	"estimator-web/internal/config"
	"estimator-web/internal/estimatorai"
	"estimator-web/internal/rag"
)

// legacyCookieName es la cookie firmada del antiguo cliente HTML. Ya no se emite ni se lee: el servicio solo la
// expira en el navegador que todavía la conserve.
const legacyCookieName = "_estimator_web_session"

// Server reúne las dependencias de los handlers.
type Server struct {
	adminDecision administrativeDecision
	publicAI      *estimatorai.PublicClient
	cfg           config.Config
	log           *slog.Logger
	compare       *estimatorai.EmbeddingsClient // con el tiempo de espera ampliado: solo lo usa el Chunking Lab
	settingsAPI   *estimatorai.ConfigClient     // plazo habitual de la API JSON de Ajustes
	badge         *badgeCache
	store         rag.Store
}

// New construye el servidor. `store` puede ser nil (sin base de datos): el Chunking Lab degrada como con un fallo de BD.
func New(cfg config.Config, store rag.Store, logger *slog.Logger) (*Server, error) {
	if logger == nil {
		logger = slog.New(slog.NewTextHandler(io.Discard, nil))
	}
	settings := estimatorai.Settings{BaseURL: cfg.APIURL, OpenTimeout: cfg.OpenTimeout, ReadTimeout: cfg.ReadTimeout}
	badgeSettings := settings.WithTimeouts(cfg.BadgeTimeout, cfg.BadgeTimeout)
	server := &Server{
		cfg:         cfg,
		publicAI:    estimatorai.NewPublicClient(cfg.APIURL, estimatorai.PublicTimeouts(cfg.PublicTimeouts())),
		log:         logger,
		compare:     estimatorai.NewEmbeddingsClient(settings.WithTimeouts(0, cfg.CompareTimeout)),
		settingsAPI: estimatorai.NewConfigClient(settings.WithTimeouts(0, cfg.PublicTimeouts().RegularTotal)),
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
	return server, nil
}

// Handler devuelve las rutas del servicio: la sonda `/up` y la API REST/SSE. Toda otra ruta, incluidas las del antiguo
// cliente HTML, recibe el 404 JSON de la API sin invocar a la IA. Con recuperación de pánicos, registro saneado y
// expiración de la cookie legada.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /up", s.health)
	mux.Handle("/", s.apiHandler())
	return s.logging(s.recoverer(s.expireLegacyCookie(mux)))
}

func safeMethod(method string) bool {
	return method == http.MethodGet || method == http.MethodHead || method == http.MethodOptions
}

// statusRecorder registra el estado y si ya se escribió la respuesta. No oculta las capacidades del escritor real:
// Unwrap permite a http.ResponseController alcanzar FlushError, Flush y los plazos de lectura y escritura, de los que
// dependen el streaming SSE y las subidas.
type statusRecorder struct {
	http.ResponseWriter
	status int
	wrote  bool
}

func (r *statusRecorder) WriteHeader(status int) {
	if !r.wrote {
		r.status = status
		r.wrote = true
	}
	r.ResponseWriter.WriteHeader(status)
}

func (r *statusRecorder) Write(data []byte) (int, error) {
	r.wrote = true
	return r.ResponseWriter.Write(data)
}

// Unwrap devuelve el escritor subyacente para http.ResponseController.
func (r *statusRecorder) Unwrap() http.ResponseWriter { return r.ResponseWriter }

// loggedRoute devuelve la ruta sin datos del usuario: el patrón del enrutador (con `{session_id}` sin resolver) o,
// si no coincidió ninguna ruta, un marcador fijo. Nunca la cadena de consulta ni identificadores de sesión.
func loggedRoute(r *http.Request) string {
	if pattern := r.Pattern; pattern != "" {
		if _, route, found := strings.Cut(pattern, " "); found {
			return route
		}
		return pattern
	}
	return "(sin ruta)"
}

func (s *Server) logging(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		started := time.Now()
		recorder := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		defer func() {
			if r.URL.Path == "/up" {
				return
			}
			s.log.Info("request", "method", r.Method, "route", loggedRoute(r), "status", recorder.status, "duration_ms", time.Since(started).Milliseconds())
		}()
		next.ServeHTTP(recorder, r)
	})
}

func (s *Server) recoverer(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			recovered := recover()
			if recovered == nil {
				return
			}
			if recovered == http.ErrAbortHandler {
				panic(recovered)
			}
			s.log.Error("panic", "route", loggedRoute(r), "error_type", fmt.Sprintf("%T", recovered), "stack", string(debug.Stack()))
			if recorder, ok := w.(*statusRecorder); ok && recorder.wrote {
				// La respuesta ya empezó (p. ej. un flujo SSE): solo se puede cortar la conexión.
				panic(http.ErrAbortHandler)
			}
			apiFailure(w, http.StatusInternalServerError, estimatorai.ServerMessage)
		}()
		next.ServeHTTP(w, r)
	})
}

// expireLegacyCookie borra en el navegador la cookie de sesión del antiguo cliente HTML, si la envía. El servicio ya
// no la emite ni la lee.
func (s *Server) expireLegacyCookie(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if _, err := r.Cookie(legacyCookieName); err == nil {
			http.SetCookie(w, &http.Cookie{Name: legacyCookieName, Value: "", Path: "/", MaxAge: -1, HttpOnly: true, SameSite: http.SameSiteLaxMode})
		}
		next.ServeHTTP(w, r)
	})
}

// health es la sonda local: no consulta IA ni PostgreSQL.
func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	_, _ = io.WriteString(w, "ok\n")
}

// --- Indicador del modelo primario ---

// badgeCache guarda unos segundos el modelo primario vigente (a lo sumo una llamada HTTP cada `ttl`). Es pura
// decoración: si el servicio no responde, devuelve "" y la barra no muestra nada. Un servicio caído nunca debe impedir
// ni retrasar el renderizado de una página; el fallo también se cachea para no reintentar en cada una.
//
// Concurrencia: las lecturas simultáneas comparten una única consulta en vuelo y esperan su resultado o la
// cancelación de su propio contexto. La consulta usa un contexto desligado del primer llamante (su cancelación no debe
// cachear una ausencia falsa) y sus plazos son los del cliente. Invalidate incrementa la generación: la consulta que
// estaba en vuelo entrega su valor a quienes ya la esperaban, pero no lo guarda, y la siguiente lectura consulta de nuevo.
type badgeCache struct {
	mu         sync.Mutex
	ttl        time.Duration
	now        func() time.Time
	fetch      func(context.Context) string
	value      string
	expires    time.Time
	generation uint64
	flight     *badgeFlight
}

type badgeFlight struct {
	done  chan struct{}
	value string
}

func newBadgeCache(ttl time.Duration, now func() time.Time, fetch func(context.Context) string) *badgeCache {
	return &badgeCache{ttl: ttl, now: now, fetch: fetch}
}

// Get devuelve el modelo primario ("" si no se pudo leer).
func (b *badgeCache) Get(ctx context.Context) string {
	b.mu.Lock()
	if b.now().Before(b.expires) {
		value := b.value
		b.mu.Unlock()
		return value
	}
	if flight := b.flight; flight != nil {
		b.mu.Unlock()
		select {
		case <-flight.done:
			return flight.value
		case <-ctx.Done():
			return ""
		}
	}
	flight := &badgeFlight{done: make(chan struct{})}
	b.flight = flight
	generation := b.generation
	b.mu.Unlock()

	value := b.fetch(context.WithoutCancel(ctx))

	b.mu.Lock()
	flight.value = value
	if b.generation == generation {
		b.value = value
		b.expires = b.now().Add(b.ttl)
		b.flight = nil
	}
	b.mu.Unlock()
	close(flight.done)
	return value
}

// Invalidate descarta el valor y la consulta en vuelo: el siguiente renderizado vuelve a consultar el servicio.
func (b *badgeCache) Invalidate() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.generation++
	b.expires = time.Time{}
	b.value = ""
	b.flight = nil
}
