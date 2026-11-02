package rag

import (
	"math"
	"sort"

	"estimator-web/internal/jsondoc"
)

// Los contratos reflejan los schemas Pydantic de la API (`CompareResponse`, `ChunkingStats`, `TopChunk`…). Si el
// contrato cambia en Python, cambia aquí y solo aquí. Se leen de forma tolerante: los atributos desconocidos que
// añada una versión nueva del servicio se ignoran y los ausentes quedan en su valor vacío.

// TokenDistribution refleja `TokenDistribution`: mínimo, p50, p95 y máximo de tokens por chunk.
type TokenDistribution struct {
	Min, P50, P95, Max float64
}

// Stats refleja `ChunkingStats`: estadísticas del corpus de una estrategia.
type Stats struct {
	Strategy          string
	NChunks           int
	NOrphanChunks     int // chunks de menos de 20 tokens
	NObeseChunks      int // chunks de más de 800 tokens
	IngestionCostUSD  float64
	ExtraAPICalls     int
	IngestionSeconds  float64
	TokenDistribution TokenDistribution
}

// Orphans indica que hay chunks huérfanos.
func (s Stats) Orphans() bool { return s.NOrphanChunks > 0 }

// Obese indica que hay chunks obesos.
func (s Stats) Obese() bool { return s.NObeseChunks > 0 }

// Free indica que la ingesta no tuvo coste.
func (s Stats) Free() bool { return s.IngestionCostUSD == 0 }

// TopChunk refleja `TopChunk`: un chunk ordenado en la recuperación de una consulta. `Level` («parent» o «child») y
// `ParentChunkID` solo existen en la estrategia jerárquica.
type TopChunk struct {
	ChunkID       string
	Cosine        float64
	TextPreview   string
	Level         string
	ParentChunkID string
}

func (c TopChunk) Parent() bool { return c.Level == "parent" }
func (c TopChunk) Child() bool  { return c.Level == "child" }

// CosinePct es la puntuación como porcentaje 0-100 para dibujar la barra.
func (c TopChunk) CosinePct() int {
	return int(math.Round(math.Min(math.Max(c.Cosine, 0), 1) * 100))
}

// QueryResult refleja `QueryResult`: los mejores chunks que recupera una estrategia para una consulta.
type QueryResult struct {
	Strategy string
	Query    string
	TopK     []TopChunk
}

// ComparisonResponse refleja `CompareResponse`: estadísticas del corpus por estrategia y, si hubo consultas, el top-k
// que recupera cada una.
type ComparisonResponse struct {
	stats   map[string]Stats
	queries map[string][]QueryResult
	extras  []string // estrategias fuera del catálogo, en orden alfabético
}

// ParseResponse construye la respuesta a partir del JSON de la API (o del guardado en el historial).
func ParseResponse(payload []byte) ComparisonResponse {
	return ResponseFromDoc(jsondoc.ParseDoc(payload))
}

// ResponseFromDoc construye la respuesta a partir de un documento ya decodificado.
func ResponseFromDoc(doc jsondoc.Doc) ComparisonResponse {
	response := ComparisonResponse{stats: map[string]Stats{}, queries: map[string][]QueryResult{}}
	for name, raw := range doc.Doc("stats_per_strategy") {
		response.stats[name] = statsFromDoc(jsondoc.From(raw))
	}
	for name, raw := range doc.Doc("queries_per_strategy") {
		items, _ := raw.([]any)
		results := make([]QueryResult, 0, len(items))
		for _, item := range items {
			results = append(results, queryResultFromDoc(jsondoc.From(item)))
		}
		response.queries[name] = results
	}
	known := map[string]bool{}
	for _, name := range AllNames() {
		known[name] = true
	}
	for name := range response.stats {
		if !known[name] {
			response.extras = append(response.extras, name)
		}
	}
	sort.Strings(response.extras)
	return response
}

func statsFromDoc(doc jsondoc.Doc) Stats {
	distribution := doc.Doc("token_distribution")
	return Stats{
		Strategy:         doc.S("strategy"),
		NChunks:          doc.Int("n_chunks"),
		NOrphanChunks:    doc.Int("n_orphan_chunks"),
		NObeseChunks:     doc.Int("n_obese_chunks"),
		IngestionCostUSD: doc.Float("ingestion_cost_usd"),
		ExtraAPICalls:    doc.Int("extra_api_calls"),
		IngestionSeconds: doc.Float("ingestion_seconds"),
		TokenDistribution: TokenDistribution{
			Min: distribution.Float("min"), P50: distribution.Float("p50"),
			P95: distribution.Float("p95"), Max: distribution.Float("max"),
		},
	}
}

func queryResultFromDoc(doc jsondoc.Doc) QueryResult {
	result := QueryResult{Strategy: doc.S("strategy"), Query: doc.S("query")}
	for _, chunk := range doc.List("top_k") {
		result.TopK = append(result.TopK, TopChunk{
			ChunkID: chunk.S("chunk_id"), Cosine: chunk.Float("cosine"), TextPreview: chunk.S("text_preview"),
			Level: chunk.S("level"), ParentChunkID: chunk.S("parent_chunk_id"),
		})
	}
	return result
}

// StrategyNames devuelve el orden canónico del catálogo, limitado a las estrategias presentes, y después las demás.
func (r ComparisonResponse) StrategyNames() []string {
	var names []string
	for _, name := range AllNames() {
		if _, ok := r.stats[name]; ok {
			names = append(names, name)
		}
	}
	return append(names, r.extras...)
}

// StatsFor devuelve las estadísticas de una estrategia.
func (r ComparisonResponse) StatsFor(name string) Stats { return r.stats[name] }

// QueryResultsFor devuelve los resultados por consulta de una estrategia.
func (r ComparisonResponse) QueryResultsFor(name string) []QueryResult { return r.queries[name] }

// Queries devuelve las consultas únicas, en el orden de emisión (todas las estrategias recibieron las mismas).
func (r ComparisonResponse) Queries() []string {
	var queries []string
	seen := map[string]bool{}
	names := r.StrategyNames()
	var orphans []string // estrategias con consultas pero sin estadísticas
	for name := range r.queries {
		if _, ok := r.stats[name]; !ok {
			orphans = append(orphans, name)
		}
	}
	sort.Strings(orphans)
	names = append(names, orphans...)
	for _, name := range names {
		for _, result := range r.queries[name] {
			if !seen[result.Query] {
				seen[result.Query] = true
				queries = append(queries, result.Query)
			}
		}
	}
	return queries
}

// StrategyResult es el top-k de una estrategia para una consulta.
type StrategyResult struct {
	Name   string
	Result QueryResult
}

// ResultsByStrategyFor devuelve el top-k de cada estrategia para una consulta.
func (r ComparisonResponse) ResultsByStrategyFor(query string) []StrategyResult {
	var results []StrategyResult
	for _, name := range r.StrategyNames() {
		for _, result := range r.queries[name] {
			if result.Query == query {
				results = append(results, StrategyResult{Name: name, Result: result})
				break
			}
		}
	}
	return results
}

// AnyQueries indica si alguna estrategia tiene resultados por consulta.
func (r ComparisonResponse) AnyQueries() bool {
	for _, results := range r.queries {
		if len(results) > 0 {
			return true
		}
	}
	return false
}

// TotalIngestionCostUSD es la suma del coste de ingesta, redondeada a 6 decimales.
func (r ComparisonResponse) TotalIngestionCostUSD() float64 {
	total := 0.0
	for _, stats := range r.stats {
		total += stats.IngestionCostUSD
	}
	return math.Round(total*1e6) / 1e6
}

// MaxIngestionCostUSD es el mayor coste de ingesta entre las estrategias.
func (r ComparisonResponse) MaxIngestionCostUSD() float64 {
	maximum := 0.0
	for _, stats := range r.stats {
		maximum = math.Max(maximum, stats.IngestionCostUSD)
	}
	return maximum
}
