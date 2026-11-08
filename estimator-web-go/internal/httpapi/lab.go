package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"estimator-web/internal/estimatorai"
	"estimator-web/internal/rag"
)

// Chunking Lab (Sesión 7): compara estrategias de chunking sobre el corpus de presupuestos con POST /embeddings/compare
// y guarda cada ejecución para poder revisarla sin volver a pagar las de pago.
//
// Síncrono a propósito: la selección por defecto (gratuitas) responde en segundos; las de pago son opt-in, se avisan en
// el formulario y tienen un tiempo de espera propio y mayor. Solo transporte: el cálculo es del servicio.

const (
	historyLimit   = 20
	defaultTopK    = 3
	historyMessage = "El historial no está disponible en este momento."
	saveMessage    = "La comparación se calculó, pero no se pudo guardar en el historial."
)

// strategyJSON es una estrategia del catálogo tal como la necesita el formulario.
type strategyJSON struct {
	Name           string `json:"name"`
	Label          string `json:"label"`
	Description    string `json:"description"`
	CostTier       string `json:"cost_tier"`
	CostLabel      string `json:"cost_label"`
	Paid           bool   `json:"paid"`
	KeyName        string `json:"key_name"`
	DefaultChecked bool   `json:"default_checked"`
}

func (s *Server) labOptions(w http.ResponseWriter, r *http.Request) {
	strategies := make([]strategyJSON, len(rag.Catalog))
	for index, strategy := range rag.Catalog {
		strategies[index] = strategyJSON{
			Name: strategy.Name, Label: strategy.Label, Description: strategy.Description, CostTier: string(strategy.CostTier),
			CostLabel: strategy.CostLabel(), Paid: strategy.Paid(), KeyName: strategy.KeyName(), DefaultChecked: strategy.DefaultChecked,
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"strategies":              strategies,
		"default_strategies":      rag.Defaults(),
		"sample_queries":          estimatorai.SampleQueries(),
		"default_top_k":           defaultTopK,
		"compare_timeout_seconds": int(s.cfg.CompareTimeout / time.Second),
	})
}

// comparisonJSON es una ejecución del historial. `Response` es el JSON de la API de IA tal cual se guardó.
type comparisonJSON struct {
	ID             int64           `json:"id"`
	Strategies     []string        `json:"strategies"`
	StrategyLabels []string        `json:"strategy_labels"`
	Queries        []string        `json:"queries"`
	TopK           int             `json:"top_k"`
	CorpusLabel    string          `json:"corpus_label"`
	CorpusCount    int             `json:"corpus_count"`
	DurationMS     *int            `json:"duration_ms"`
	CreatedAt      *time.Time      `json:"created_at"`
	Saved          bool            `json:"saved"`
	TotalCostUSD   float64         `json:"total_ingestion_cost_usd"`
	Notice         string          `json:"notice,omitempty"`
	Response       json.RawMessage `json:"response,omitempty"`
}

func toComparisonJSON(comparison rag.Comparison, withResponse bool) comparisonJSON {
	view := comparisonJSON{
		ID: comparison.ID, Strategies: comparison.Strategies, StrategyLabels: comparison.StrategyLabels(),
		Queries: comparison.Queries, TopK: comparison.TopK, CorpusLabel: comparison.CorpusLabel, CorpusCount: comparison.CorpusCount,
		DurationMS: comparison.DurationMS, Saved: comparison.Saved(), TotalCostUSD: comparison.TotalCostUSD(),
	}
	if view.Strategies == nil {
		view.Strategies = []string{}
	}
	if view.Queries == nil {
		view.Queries = []string{}
	}
	if comparison.Saved() {
		created := comparison.CreatedAt
		view.CreatedAt = &created
	}
	if withResponse {
		view.Response = json.RawMessage("{}")
		if json.Valid(comparison.ResponsePayload) {
			view.Response = json.RawMessage(comparison.ResponsePayload)
		}
	}
	return view
}

func (s *Server) labIndex(w http.ResponseWriter, r *http.Request) {
	comparisons, err := s.recent(r.Context())
	if err != nil {
		s.log.Error("chunking_history_unavailable", "error_type", fmt.Sprintf("%T", err))
		writeDetail(w, http.StatusServiceUnavailable, historyMessage)
		return
	}
	items := make([]comparisonJSON, len(comparisons))
	for index, comparison := range comparisons {
		items[index] = toComparisonJSON(comparison, false)
	}
	writeJSON(w, http.StatusOK, items)
}

// labRequest es el cuerpo de POST /api/chunking-comparisons.
type labRequest struct {
	Strategies []string `json:"strategies"`
	Queries    []string `json:"queries"`
	TopK       *int     `json:"top_k"`
}

func (s *Server) labCreate(w http.ResponseWriter, r *http.Request) {
	var body labRequest
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeDetail(w, http.StatusUnprocessableEntity, estimatorai.ValidationMessage)
		return
	}
	strategies, queries, topK := normalizeLab(body)
	if len(strategies) == 0 {
		writeDetail(w, http.StatusUnprocessableEntity, "Selecciona al menos una estrategia.")
		return
	}

	budgets := estimatorai.Budgets()
	started := time.Now()
	payload, err := s.compare.CompareChunking(r.Context(), budgets, queries, strategies, topK)
	if err != nil {
		s.writeLabError(w, err)
		return
	}
	durationMS := int(time.Since(started).Milliseconds())

	comparison := rag.Comparison{
		Strategies: strategies, Queries: queries, TopK: topK, CorpusLabel: estimatorai.CorpusLabel,
		CorpusCount: len(budgets), ResponsePayload: payload, DurationMS: &durationMS,
	}
	// La comparación ya se calculó (y, si usó estrategias de pago, se pagó): si el historial no puede guardarla, se
	// devuelve igualmente en lugar de perderla.
	notice := ""
	if err := s.create(r.Context(), &comparison); err != nil {
		s.log.Error("chunking_history_save_failed", "error_type", fmt.Sprintf("%T", err))
		notice = saveMessage
	}
	view := toComparisonJSON(comparison, true)
	view.Notice = notice
	writeJSON(w, http.StatusCreated, view)
}

func (s *Server) labShow(w http.ResponseWriter, r *http.Request) {
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil {
		writeDetail(w, http.StatusNotFound, "No se encontró la comparación solicitada.")
		return
	}
	comparison, err := s.find(r.Context(), id)
	switch {
	case errors.Is(err, rag.ErrNotFound):
		writeDetail(w, http.StatusNotFound, "No se encontró la comparación solicitada.")
	case err != nil:
		s.log.Error("chunking_history_read_failed", "error_type", fmt.Sprintf("%T", err))
		writeDetail(w, http.StatusServiceUnavailable, historyMessage)
	default:
		writeJSON(w, http.StatusOK, toComparisonJSON(*comparison, true))
	}
}

// normalizeLab deja las estrategias válidas (únicas, en el orden recibido), las consultas sin vacías ni repetidas y
// `top_k` limitado a 1–10.
func normalizeLab(body labRequest) (strategies, queries []string, topK int) {
	seen := map[string]bool{}
	for _, name := range body.Strategies {
		if _, ok := rag.Find(name); ok && !seen[name] {
			seen[name] = true
			strategies = append(strategies, name)
		}
	}
	seenQuery := map[string]bool{}
	for _, candidate := range body.Queries {
		query := strings.TrimSpace(candidate)
		if query != "" && !seenQuery[query] {
			seenQuery[query] = true
			queries = append(queries, query)
		}
	}
	topK = defaultTopK
	if body.TopK != nil {
		topK = min(max(*body.TopK, 1), 10)
	}
	return strategies, queries, topK
}

// writeLabError traduce el error de la API al aviso accionable y a su estado HTTP.
func (s *Server) writeLabError(w http.ResponseWriter, err error) {
	switch {
	case estimatorai.IsKind(err, estimatorai.InvalidRequest):
		writeDetail(w, http.StatusUnprocessableEntity, "Petición inválida: "+err.Error())
	case estimatorai.IsKind(err, estimatorai.RequestTimeout):
		seconds := int(s.cfg.CompareTimeout / time.Second)
		writeDetail(w, http.StatusGatewayTimeout, fmt.Sprintf("El servicio IA no respondió en %d s. Las estrategias de pago pueden tardar varios minutos: prueba con menos estrategias.", seconds))
	case estimatorai.IsKind(err, estimatorai.ServiceUnavailable):
		// El 503 de la API nombra la variable de la clave ausente (OPENAI_API_KEY / ANTHROPIC_API_KEY).
		writeDetail(w, http.StatusServiceUnavailable, "El servicio IA no puede ejecutar esa comparación: "+err.Error())
	case estimatorai.IsKind(err, estimatorai.ConnectionFailed):
		writeDetail(w, http.StatusServiceUnavailable, err.Error())
	default:
		writeDetail(w, http.StatusBadGateway, "Error del servicio IA: "+err.Error())
	}
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
