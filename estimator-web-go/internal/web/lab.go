package web

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"estimator-web/internal/estimatorai"
	"estimator-web/internal/jsondoc"
	"estimator-web/internal/rag"
	"estimator-web/internal/session"
)

// Chunking Lab (Sesión 7): compara estrategias de chunking sobre el corpus de presupuestos con POST /embeddings/compare
// y guarda cada ejecución para poder revisarla sin volver a pagar las de pago.
//
// Síncrono a propósito (no hay infraestructura de trabajos en el cliente): la selección por defecto (gratuitas)
// responde en segundos; las de pago son opt-in, se avisan en el formulario y tienen un tiempo de espera propio y mayor.
// Solo transporte: el cálculo es del servicio.

const historyLimit = 20

// labFormPage son los datos del formulario del laboratorio.
type labFormPage struct {
	SelectedStrategies []string
	Queries            []string
	TopK               int
	CompareTimeout     int // segundos
}

// labShowPage son los datos del detalle de una ejecución.
type labShowPage struct {
	Comparison rag.Comparison
	Response   rag.ComparisonResponse
}

func (s *Server) labIndex(w http.ResponseWriter, r *http.Request, sess *session.Session) {
	comparisons, err := s.recent(r.Context())
	if err != nil {
		s.log.Error("chunking_history_unavailable", "error_type", fmt.Sprintf("%T", err))
		comparisons = nil
		sess.FlashNow("alert", "El historial no está disponible en este momento.")
	}
	s.render(w, r, sess, http.StatusOK, "lab_index", &view{Title: "Historial · Chunking Lab", Section: sectionRag, Data: comparisons})
}

func (s *Server) labNew(w http.ResponseWriter, r *http.Request, sess *session.Session) {
	s.renderLabForm(w, r, sess, http.StatusOK, labFormPage{SelectedStrategies: rag.Defaults(), TopK: 3})
}

func (s *Server) renderLabForm(w http.ResponseWriter, r *http.Request, sess *session.Session, status int, page labFormPage) {
	page.CompareTimeout = int(s.cfg.CompareTimeout / time.Second)
	s.render(w, r, sess, status, "lab_new", &view{Title: "Nueva comparación · Chunking Lab", Section: sectionRag, Data: page})
}

func (s *Server) labCreate(w http.ResponseWriter, r *http.Request, sess *session.Session) {
	page := readLabForm(r)
	if len(page.SelectedStrategies) == 0 {
		sess.FlashNow("alert", "Selecciona al menos una estrategia.")
		s.renderLabForm(w, r, sess, http.StatusUnprocessableEntity, page)
		return
	}

	budgets := estimatorai.Budgets()
	started := time.Now()
	payload, err := s.compare.CompareChunking(r.Context(), budgets, page.Queries, page.SelectedStrategies, page.TopK)
	if err != nil {
		message, status := s.labErrorMessage(err)
		sess.FlashNow("alert", message)
		s.renderLabForm(w, r, sess, status, page)
		return
	}
	durationMS := int(time.Since(started).Milliseconds())

	comparison := rag.Comparison{
		Strategies: page.SelectedStrategies, Queries: page.Queries, TopK: page.TopK, CorpusLabel: estimatorai.CorpusLabel,
		CorpusCount: len(budgets), ResponsePayload: payload, DurationMS: &durationMS,
	}
	s.saveAndShow(w, r, sess, &comparison)
}

// saveAndShow: la comparación ya se calculó (y, si usó estrategias de pago, se pagó): si el historial no puede
// guardarla, se muestra igualmente en lugar de perderla.
func (s *Server) saveAndShow(w http.ResponseWriter, r *http.Request, sess *session.Session, comparison *rag.Comparison) {
	if err := s.create(r.Context(), comparison); err != nil {
		s.log.Error("chunking_history_save_failed", "error_type", fmt.Sprintf("%T", err))
		sess.FlashNow("alert", "La comparación se calculó, pero no se pudo guardar en el historial.")
		s.renderLabShow(w, r, sess, *comparison)
		return
	}
	s.redirect(w, r, sess, "/rag/chunking_comparisons/"+strconv.FormatInt(comparison.ID, 10))
}

func (s *Server) labShow(w http.ResponseWriter, r *http.Request, sess *session.Session) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		s.servePublicPage(w, http.StatusNotFound, "public/404.html")
		return
	}
	comparison, err := s.find(r.Context(), id)
	switch {
	case errors.Is(err, rag.ErrNotFound):
		s.servePublicPage(w, http.StatusNotFound, "public/404.html")
	case err != nil:
		s.log.Error("chunking_history_read_failed", "error_type", fmt.Sprintf("%T", err))
		s.servePublicPage(w, http.StatusInternalServerError, "public/500.html")
	default:
		s.renderLabShow(w, r, sess, *comparison)
	}
}

func (s *Server) renderLabShow(w http.ResponseWriter, r *http.Request, sess *session.Session, comparison rag.Comparison) {
	s.render(w, r, sess, http.StatusOK, "lab_show", &view{
		Title: "Comparación · Chunking Lab", Section: sectionRag,
		Data: labShowPage{Comparison: comparison, Response: comparison.Response()},
	})
}

// readLabForm lee el formulario: estrategias válidas (únicas), consultas marcadas y propias (sin vacías ni repetidas)
// y `top_k` limitado a 1–10.
func readLabForm(r *http.Request) labFormPage {
	var strategies []string
	seen := map[string]bool{}
	for _, name := range r.PostForm["strategies[]"] {
		if _, ok := rag.Find(name); ok && !seen[name] {
			seen[name] = true
			strategies = append(strategies, name)
		}
	}

	candidates := append([]string{}, r.PostForm["queries[]"]...)
	candidates = append(candidates, strings.Split(r.PostForm.Get("custom_queries"), "\n")...)
	var queries []string
	seenQuery := map[string]bool{}
	for _, candidate := range candidates {
		query := strings.TrimSpace(candidate)
		if query != "" && !seenQuery[query] {
			seenQuery[query] = true
			queries = append(queries, query)
		}
	}

	topK := min(max(jsondoc.RubyToI(r.PostForm.Get("top_k")), 1), 10)
	return labFormPage{SelectedStrategies: strategies, Queries: queries, TopK: topK}
}

// labErrorMessage traduce el error de la API al aviso del formulario y a su estado HTTP.
func (s *Server) labErrorMessage(err error) (string, int) {
	switch {
	case estimatorai.IsKind(err, estimatorai.InvalidRequest):
		return "Petición inválida: " + err.Error(), http.StatusUnprocessableEntity
	case estimatorai.IsKind(err, estimatorai.RequestTimeout):
		seconds := int(s.cfg.CompareTimeout / time.Second)
		return fmt.Sprintf("El servicio IA no respondió en %d s. Las estrategias de pago pueden tardar varios minutos: prueba con menos estrategias.", seconds), http.StatusGatewayTimeout
	case estimatorai.IsKind(err, estimatorai.ServiceUnavailable):
		// El 503 de la API nombra la variable de la clave ausente (OPENAI_API_KEY / ANTHROPIC_API_KEY).
		return "El servicio IA no puede ejecutar esa comparación: " + err.Error(), http.StatusServiceUnavailable
	case estimatorai.IsKind(err, estimatorai.ConnectionFailed):
		return err.Error(), http.StatusServiceUnavailable
	}
	return "Error del servicio IA: " + err.Error(), http.StatusBadGateway
}

// --- Historial (sin base de datos configurada, todo es «no disponible») ---

func (s *Server) recent(ctx context.Context) ([]rag.Comparison, error) {
	if s.store == nil {
		return nil, errNoStore
	}
	return s.store.Recent(ctx, historyLimit)
}

func (s *Server) create(ctx context.Context, comparison *rag.Comparison) error {
	if s.store == nil {
		return errNoStore
	}
	return s.store.Create(ctx, comparison)
}

func (s *Server) find(ctx context.Context, id int64) (*rag.Comparison, error) {
	if s.store == nil {
		return nil, errNoStore
	}
	return s.store.Find(ctx, id)
}
