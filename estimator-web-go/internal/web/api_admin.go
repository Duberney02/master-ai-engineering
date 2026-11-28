package web

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"

	"estimator-web/internal/ai"
	"estimator-web/internal/estimatorai"
	"estimator-web/internal/rag"
)

// API JSON administrativa de React: Ajustes de IA, indicador del modelo primario y Chunking Lab. Solo transporte: la
// validación y persistencia de modelos son de IA, el cálculo de la comparación también y el historial es de Go. Cada
// operación administrativa se registra detrás de `administrativeAPI`, que decide antes de leer, invocar o persistir.

const (
	historyUnavailableDetail = estimatorai.HistoryUnavailableMessage
	comparisonNotFound       = "No se encontró la comparación solicitada."
	saveWarning              = "La comparación se calculó, pero no se pudo guardar en el historial."
	timeoutMessage           = "El servicio IA no respondió a tiempo. Inténtalo de nuevo."
	// defaultTopK es el valor inicial y el de un `top_k` omitido. DA-28: exclusivo del Chunking Lab.
	defaultTopK, minTopK, maxTopK = 3, 1, 10
)

var (
	// Los únicos nombres de variable que un detalle de IA puede mencionar tal cual (DA-06: no se exponen otros).
	allowedVariables = map[string]bool{"OPENAI_API_KEY": true, "ANTHROPIC_API_KEY": true}
	variableName     = regexp.MustCompile(`[A-Z][A-Z0-9]*_[A-Z0-9_]+`)
	jsonInteger      = regexp.MustCompile(`^-?(0|[1-9][0-9]*)$`)
	decimalID        = regexp.MustCompile(`^(0|[1-9][0-9]*)$`)
)

// safeDetail deja pasar el `detail` redactado por IA solo si no puede filtrar datos internos: sin URL, trazas, claves,
// saltos de línea ni nombres de variable que no sean los de claves de proveedor conocidas.
func safeDetail(message, fallback string) string {
	if strings.TrimSpace(message) == "" || strings.ContainsAny(message, "\r\n") ||
		strings.Contains(message, "://") || strings.Contains(message, "sk-") ||
		strings.Contains(message, "Traceback") || strings.Contains(message, "File \"") {
		return fallback
	}
	for _, name := range variableName.FindAllString(message, -1) {
		if !allowedVariables[name] {
			return fallback
		}
	}
	return message
}

// adminFailure traduce un error tipado a su estado y a un `detail` saneado. `reject` prefija los rechazos (422).
func adminFailure(w http.ResponseWriter, err error, reject string) {
	typed, ok := estimatorai.As(err)
	if !ok {
		apiFailure(w, http.StatusBadGateway, estimatorai.ServerMessage)
		return
	}
	switch {
	case typed.IsA(estimatorai.RequestTimeout):
		apiFailure(w, http.StatusGatewayTimeout, timeoutMessage)
	case typed.IsA(estimatorai.ConnectionFailed):
		apiFailure(w, http.StatusServiceUnavailable, estimatorai.ConnectionMessage)
	case typed.IsA(estimatorai.InvalidRequest), typed.IsA(estimatorai.GuardrailViolation):
		apiFailure(w, http.StatusUnprocessableEntity, reject+safeDetail(typed.Message, estimatorai.ValidationMessage))
	case typed.IsA(estimatorai.ServiceUnavailable):
		apiFailure(w, http.StatusServiceUnavailable, safeDetail(typed.Message, estimatorai.ServerMessage))
	case typed.IsA(estimatorai.InvalidResponse):
		apiFailure(w, http.StatusBadGateway, estimatorai.InvalidResponseMessage)
	default:
		apiFailure(w, http.StatusBadGateway, estimatorai.ServerMessage)
	}
}

func noStore(w http.ResponseWriter) { w.Header().Set("Cache-Control", "no-store") }

// --- Ajustes de IA ---

func (s *Server) apiSettingsRead(w http.ResponseWriter, r *http.Request) {
	models, err := s.settingsAPI.Models(r.Context())
	if r.Context().Err() != nil {
		return
	}
	if err != nil {
		adminFailure(w, err, "")
		return
	}
	noStore(w)
	apiJSON(w, http.StatusOK, ai.FromDoc(models).Settings())
}

// settingsChanges normaliza `{models: {campo: string|null}}`: ignora los campos desconocidos y convierte vacío en null.
// Devuelve false si un campo conocido no es cadena ni null.
func settingsChanges(raw map[string]json.RawMessage) (map[string]*string, bool) {
	changes := map[string]*string{}
	for _, key := range ai.Keys() {
		value, submitted := raw[key]
		if !submitted {
			continue
		}
		if bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			changes[key] = nil
			continue
		}
		var text string
		if json.Unmarshal(value, &text) != nil {
			return nil, false
		}
		if strings.TrimSpace(text) == "" {
			changes[key] = nil
			continue
		}
		changes[key] = &text
	}
	return changes, true
}

func (s *Server) apiSettingsWrite(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Models map[string]json.RawMessage `json:"models"`
	}
	if !readJSON(w, r, &body) {
		return
	}
	changes, valid := settingsChanges(body.Models)
	if !valid {
		apiFailure(w, http.StatusUnprocessableEntity, estimatorai.ValidationMessage)
		return
	}
	if len(changes) == 0 {
		apiFailure(w, http.StatusUnprocessableEntity, "No hay ningún modelo que cambiar.")
		return
	}
	models, err := s.settingsAPI.UpdateModels(r.Context(), changes)
	if r.Context().Err() != nil {
		return
	}
	if err != nil {
		adminFailure(w, err, "Cambio rechazado: ")
		return
	}
	// El indicador cachea el primario unos segundos: se descarta para que el cambio se vea en la siguiente lectura.
	s.badge.Invalidate()
	noStore(w)
	apiJSON(w, http.StatusOK, ai.FromDoc(models).Settings())
}

// apiPrimaryModel es la proyección de solo lectura del nombre efectivo del primario. De acceso general: no expone el
// catálogo, y un fallo o una ausencia devuelven null para que la barra omita el indicador.
func (s *Server) apiPrimaryModel(w http.ResponseWriter, r *http.Request) {
	var model any
	if name := s.badge.Get(r.Context()); name != "" {
		model = name
	}
	noStore(w)
	apiJSON(w, http.StatusOK, map[string]any{"model": model})
}

// --- Chunking Lab: contratos ---

type strategyOption struct {
	Name           string  `json:"name"`
	Label          string  `json:"label"`
	Description    string  `json:"description"`
	CostTier       string  `json:"cost_tier"`
	CostLabel      string  `json:"cost_label"`
	KeyName        *string `json:"key_name"`
	DefaultChecked bool    `json:"default_checked"`
}

type topKLimits struct {
	Default int `json:"default"`
	Min     int `json:"min"`
	Max     int `json:"max"`
}

type labOptions struct {
	Strategies     []strategyOption `json:"strategies"`
	SampleQueries  []string         `json:"sample_queries"`
	TopK           topKLimits       `json:"top_k"`
	CompareTimeout int              `json:"compare_timeout_seconds"`
}

type tokenSpread struct {
	Min float64 `json:"min"`
	P50 float64 `json:"p50"`
	P95 float64 `json:"p95"`
	Max float64 `json:"max"`
}

type strategyStats struct {
	Strategy          string      `json:"strategy"`
	NChunks           int         `json:"n_chunks"`
	TokenDistribution tokenSpread `json:"token_distribution"`
	NOrphanChunks     int         `json:"n_orphan_chunks"`
	NObeseChunks      int         `json:"n_obese_chunks"`
	IngestionCostUSD  float64     `json:"ingestion_cost_usd"`
	ExtraAPICalls     int         `json:"extra_api_calls"`
	IngestionSeconds  float64     `json:"ingestion_seconds"`
}

type retrievedChunk struct {
	ChunkID       string  `json:"chunk_id"`
	Cosine        float64 `json:"cosine"`
	TextPreview   string  `json:"text_preview"`
	Level         *string `json:"level"`
	ParentChunkID *string `json:"parent_chunk_id"`
}

type queryOutcome struct {
	Strategy string           `json:"strategy"`
	Query    string           `json:"query"`
	TopK     []retrievedChunk `json:"top_k"`
}

// comparisonResult lista las estrategias en el orden canónico del catálogo y, dentro de cada una, sus consultas en el
// orden de emisión.
type comparisonResult struct {
	StatsPerStrategy   []strategyStats `json:"stats_per_strategy"`
	QueriesPerStrategy []queryOutcome  `json:"queries_per_strategy"`
}

type comparisonSummary struct {
	ID                    *string  `json:"id"`
	Strategies            []string `json:"strategies"`
	Queries               []string `json:"queries"`
	TopK                  int      `json:"top_k"`
	CorpusLabel           string   `json:"corpus_label"`
	CorpusCount           int      `json:"corpus_count"`
	DurationMS            *int     `json:"duration_ms"`
	CreatedAt             *string  `json:"created_at"`
	TotalIngestionCostUSD float64  `json:"total_ingestion_cost_usd"`
}

type comparisonDetail struct {
	comparisonSummary
	Result  comparisonResult `json:"result"`
	Warning *string          `json:"warning"`
}

func nullable(text string) *string {
	if text == "" {
		return nil
	}
	return &text
}

func summaryOf(c rag.Comparison) comparisonSummary {
	summary := comparisonSummary{
		Strategies: append([]string{}, c.Strategies...), Queries: append([]string{}, c.Queries...), TopK: c.TopK,
		CorpusLabel: c.CorpusLabel, CorpusCount: c.CorpusCount, DurationMS: c.DurationMS,
		TotalIngestionCostUSD: c.TotalCostUSD(),
	}
	if c.Saved() {
		// DA-27: el ID viaja como cadena decimal; un número JSON perdería dígitos por encima de 2^53 − 1.
		id := strconv.FormatInt(c.ID, 10)
		created := c.CreatedAt.UTC().Format(time.RFC3339Nano)
		summary.ID, summary.CreatedAt = &id, &created
	}
	return summary
}

func detailOf(c rag.Comparison, warning string) comparisonDetail {
	response := c.Response()
	result := comparisonResult{StatsPerStrategy: []strategyStats{}, QueriesPerStrategy: []queryOutcome{}}
	for _, name := range response.StrategyNames() {
		stats := response.StatsFor(name)
		result.StatsPerStrategy = append(result.StatsPerStrategy, strategyStats{
			Strategy: name, NChunks: stats.NChunks,
			TokenDistribution: tokenSpread{Min: stats.TokenDistribution.Min, P50: stats.TokenDistribution.P50, P95: stats.TokenDistribution.P95, Max: stats.TokenDistribution.Max},
			NOrphanChunks:     stats.NOrphanChunks, NObeseChunks: stats.NObeseChunks, IngestionCostUSD: stats.IngestionCostUSD,
			ExtraAPICalls: stats.ExtraAPICalls, IngestionSeconds: stats.IngestionSeconds,
		})
		for _, outcome := range response.QueryResultsFor(name) {
			chunks := []retrievedChunk{}
			for _, chunk := range outcome.TopK {
				chunks = append(chunks, retrievedChunk{
					ChunkID: chunk.ChunkID, Cosine: chunk.Cosine, TextPreview: chunk.TextPreview,
					Level: nullable(chunk.Level), ParentChunkID: nullable(chunk.ParentChunkID),
				})
			}
			result.QueriesPerStrategy = append(result.QueriesPerStrategy, queryOutcome{Strategy: outcome.Strategy, Query: outcome.Query, TopK: chunks})
		}
	}
	return comparisonDetail{comparisonSummary: summaryOf(c), Result: result, Warning: nullable(warning)}
}

// --- Chunking Lab: opciones ---

func (s *Server) apiLabOptions(w http.ResponseWriter, r *http.Request) {
	options := labOptions{
		Strategies: []strategyOption{}, SampleQueries: append([]string{}, estimatorai.SampleQueries()...),
		TopK: topKLimits{Default: defaultTopK, Min: minTopK, Max: maxTopK}, CompareTimeout: int(s.cfg.CompareTimeout / time.Second),
	}
	for _, strategy := range rag.Catalog {
		options.Strategies = append(options.Strategies, strategyOption{
			Name: strategy.Name, Label: strategy.Label, Description: strategy.Description, CostTier: string(strategy.CostTier),
			CostLabel: strategy.CostLabel(), KeyName: nullable(strategy.KeyName()), DefaultChecked: strategy.DefaultChecked,
		})
	}
	noStore(w)
	apiJSON(w, http.StatusOK, options)
}

// --- Chunking Lab: comparación ---

// labInput es el cuerpo normalizado de una comparación.
type labInput struct {
	strategies, queries []string
	topK                int
}

// labStrings lee un campo que debe ser una lista de cadenas (ausente = vacío).
func labStrings(raw map[string]json.RawMessage, key string) ([]string, bool) {
	value, present := raw[key]
	if !present {
		return nil, true
	}
	var items []string
	if json.Unmarshal(value, &items) != nil || items == nil {
		return nil, false
	}
	return items, true
}

// normalizeTopK aplica DA-28: omitido vale 3 y los enteros JSON se acotan a 1–10. Decimales, exponentes, cadenas,
// booleanos y null son inválidos. Un entero fuera del rango de int64 también se acota.
func normalizeTopK(raw json.RawMessage, present bool) (int, bool) {
	if !present {
		return defaultTopK, true
	}
	text := string(bytes.TrimSpace(raw))
	if !jsonInteger.MatchString(text) {
		return 0, false
	}
	number, err := strconv.ParseInt(text, 10, 64)
	if err != nil {
		if strings.HasPrefix(text, "-") {
			return minTopK, true
		}
		return maxTopK, true
	}
	return int(min(max(number, minTopK), maxTopK)), true
}

// parseLabInput filtra estrategias a las conocidas y únicas y combina las consultas marcadas y las propias (una por
// línea), sin espacios exteriores, vacías ni repetidas. No limita su cantidad ni su longitud: lo acota el límite de
// transporte del cuerpo.
func parseLabInput(raw map[string]json.RawMessage) (labInput, bool) {
	var input labInput
	names, ok := labStrings(raw, "strategies")
	if !ok {
		return input, false
	}
	queries, ok := labStrings(raw, "queries")
	if !ok {
		return input, false
	}
	var custom string
	if value, present := raw["custom_queries"]; present && json.Unmarshal(value, &custom) != nil {
		return input, false
	}
	topValue, present := raw["top_k"]
	if input.topK, ok = normalizeTopK(topValue, present); !ok {
		return input, false
	}
	seen := map[string]bool{}
	for _, name := range names {
		if _, known := rag.Find(name); known && !seen[name] {
			seen[name] = true
			input.strategies = append(input.strategies, name)
		}
	}
	seenQuery := map[string]bool{}
	for _, candidate := range append(queries, strings.Split(custom, "\n")...) {
		query := strings.TrimSpace(candidate)
		if query != "" && !seenQuery[query] {
			seenQuery[query] = true
			input.queries = append(input.queries, query)
		}
	}
	return input, true
}

func (s *Server) apiLabCreate(w http.ResponseWriter, r *http.Request) {
	raw := map[string]json.RawMessage{}
	if !readJSON(w, r, &raw) {
		return
	}
	input, valid := parseLabInput(raw)
	if !valid {
		apiFailure(w, http.StatusUnprocessableEntity, estimatorai.ValidationMessage)
		return
	}
	if len(input.strategies) == 0 {
		apiFailure(w, http.StatusUnprocessableEntity, "Selecciona al menos una estrategia.")
		return
	}

	budgets := estimatorai.Budgets()
	started := time.Now()
	payload, err := s.compare.CompareChunking(r.Context(), budgets, input.queries, input.strategies, input.topK)
	// Cancelar aborta la operación: sin escritura posterior ni respuesta. Un único INSERT es atómico: o queda la fila
	// completa o ninguna.
	if r.Context().Err() != nil {
		return
	}
	if err != nil {
		s.labFailure(w, err)
		return
	}
	durationMS := int(time.Since(started).Milliseconds())
	comparison := rag.Comparison{
		Strategies: input.strategies, Queries: input.queries, TopK: input.topK, CorpusLabel: estimatorai.CorpusLabel,
		CorpusCount: len(budgets), ResponsePayload: payload, DurationMS: &durationMS,
	}
	// La comparación ya se calculó (y quizá se pagó): si el historial no puede guardarla, se devuelve igualmente.
	if err := s.create(r.Context(), &comparison); err != nil {
		if r.Context().Err() != nil {
			return
		}
		s.log.Error("chunking_history_save_failed", "error_type", fmt.Sprintf("%T", err))
		noStore(w)
		apiJSON(w, http.StatusOK, detailOf(comparison, saveWarning))
		return
	}
	noStore(w)
	w.Header().Set("Location", "/api/v1/rag/chunking-comparisons/"+strconv.FormatInt(comparison.ID, 10))
	apiJSON(w, http.StatusCreated, detailOf(comparison, ""))
}

// labFailure traduce los errores de la comparación a avisos accionables.
func (s *Server) labFailure(w http.ResponseWriter, err error) {
	if estimatorai.IsKind(err, estimatorai.RequestTimeout) {
		seconds := int(s.cfg.CompareTimeout / time.Second)
		apiFailure(w, http.StatusGatewayTimeout, fmt.Sprintf("El servicio IA no respondió en %d s. Las estrategias de pago pueden tardar varios minutos: prueba con menos estrategias.", seconds))
		return
	}
	if estimatorai.IsKind(err, estimatorai.ServiceUnavailable) {
		// El 503 de IA nombra la variable de la clave ausente (OPENAI_API_KEY / ANTHROPIC_API_KEY).
		message := safeDetail(err.Error(), estimatorai.ServerMessage)
		apiFailure(w, http.StatusServiceUnavailable, "El servicio IA no puede ejecutar esa comparación: "+message)
		return
	}
	adminFailure(w, err, "Petición inválida: ")
}

// --- Chunking Lab: historial y detalle ---

func (s *Server) apiLabList(w http.ResponseWriter, r *http.Request) {
	items := []comparisonSummary{}
	var warning *string
	comparisons, err := s.recent(r.Context())
	if err != nil {
		if r.Context().Err() != nil {
			return
		}
		s.log.Error("chunking_history_unavailable", "error_type", fmt.Sprintf("%T", err))
		message := historyUnavailableDetail
		warning = &message
	}
	for _, comparison := range comparisons {
		items = append(items, summaryOf(comparison))
	}
	noStore(w)
	apiJSON(w, http.StatusOK, map[string]any{"items": items, "warning": warning})
}

func (s *Server) apiLabDetail(w http.ResponseWriter, r *http.Request) {
	text := r.PathValue("id")
	id, err := strconv.ParseInt(text, 10, 64)
	if !decimalID.MatchString(text) || err != nil {
		apiFailure(w, http.StatusNotFound, comparisonNotFound)
		return
	}
	comparison, err := s.find(r.Context(), id)
	if r.Context().Err() != nil {
		return
	}
	switch {
	case errors.Is(err, rag.ErrNotFound):
		apiFailure(w, http.StatusNotFound, comparisonNotFound)
	case err != nil:
		s.log.Error("chunking_history_read_failed", "error_type", fmt.Sprintf("%T", err))
		apiFailure(w, http.StatusInternalServerError, historyUnavailableDetail)
	default:
		noStore(w)
		apiJSON(w, http.StatusOK, detailOf(*comparison, ""))
	}
}
