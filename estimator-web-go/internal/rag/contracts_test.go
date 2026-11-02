package rag

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

func statsBody(strategy string, cost float64, orphans int) map[string]any {
	return map[string]any{
		"strategy": strategy, "n_chunks": 10,
		"token_distribution": map[string]any{"min": 40, "p50": 79.0, "p95": 120.5, "max": 300},
		"n_orphan_chunks":    orphans, "n_obese_chunks": 0, "ingestion_cost_usd": cost, "extra_api_calls": 0, "ingestion_seconds": 0.012,
	}
}

func topChunk(id string, cosine float64, level, parent string) map[string]any {
	chunk := map[string]any{"chunk_id": id, "cosine": cosine, "text_preview": "Vista previa de " + id, "level": nil, "parent_chunk_id": nil}
	if level != "" {
		chunk["level"] = level
	}
	if parent != "" {
		chunk["parent_chunk_id"] = parent
	}
	return chunk
}

// compareBody es la respuesta de POST /embeddings/compare para las estrategias y consultas dadas.
func compareBody(strategies []string, queries []string, contextualCost float64) []byte {
	stats := map[string]any{}
	perStrategy := map[string]any{}
	for _, name := range strategies {
		cost := 0.0
		if name == "contextual_retrieval" {
			cost = contextualCost
		}
		stats[name] = statsBody(name, cost, 0)
		var results []any
		for _, query := range queries {
			top := []any{topChunk("BUD-1::AUTH-1", 0.64, "", "")}
			if name == "hierarchical" {
				top = []any{topChunk("BUD-1::parent", 0.71, "parent", ""), topChunk("BUD-1::AUTH-1", 0.64, "child", "BUD-1::parent")}
			}
			results = append(results, map[string]any{"strategy": name, "query": query, "top_k": top})
		}
		perStrategy[name] = results
	}
	body := map[string]any{"stats_per_strategy": stats, "queries_per_strategy": map[string]any{}}
	if len(queries) > 0 {
		body["queries_per_strategy"] = perStrategy
	}
	encoded, _ := json.Marshal(body)
	return encoded
}

func TestCatalogMirrorsTheEightStrategiesInCanonicalOrder(t *testing.T) {
	want := []string{"structural", "fixed_size", "recursive", "sentence_window", "hierarchical", "semantic", "propositional", "contextual_retrieval"}
	if !reflect.DeepEqual(AllNames(), want) {
		t.Errorf("catálogo: %v", AllNames())
	}
}

func TestFreeStrategiesAreDefaultAndPaidOnesAreOptIn(t *testing.T) {
	if !reflect.DeepEqual(Defaults(), []string{"structural", "fixed_size", "recursive"}) {
		t.Errorf("por defecto: %v", Defaults())
	}
	var paid []string
	for _, name := range AllNames() {
		if IsPaid(name) {
			paid = append(paid, name)
		}
	}
	if !reflect.DeepEqual(paid, []string{"semantic", "propositional", "contextual_retrieval"}) || PaidSelected(Defaults()) {
		t.Errorf("de pago: %v", paid)
	}
}

func TestPaidStrategiesDeclareTheKeyTheyNeed(t *testing.T) {
	keys := KeysNeeded([]string{"semantic", "structural", "contextual_retrieval", "propositional"})
	if !reflect.DeepEqual(keys, []string{"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}) {
		t.Errorf("claves: %v", keys)
	}
	if len(KeysNeeded(Defaults())) != 0 || !PaidSelected([]string{"structural", "propositional"}) || PaidSelected([]string{"structural", "magic"}) {
		t.Error("claves o coste mal calculados")
	}
	if LabelFor("fixed_size") != "Tamaño fijo" || LabelFor("magic") != "magic" {
		t.Error("etiquetas")
	}
}

func TestStatsMirrorChunkingStatsIncludingTokenDistribution(t *testing.T) {
	stats := ParseResponse(compareBody([]string{"structural"}, nil, 0)).StatsFor("structural")
	if stats.NChunks != 10 || stats.TokenDistribution.P50 != 79.0 || stats.TokenDistribution.Max != 300 || !stats.Free() || stats.Orphans() {
		t.Errorf("estadísticas: %+v", stats)
	}
}

func TestUnknownAttributesFromANewerServiceAreIgnored(t *testing.T) {
	body := `{"stats_per_strategy":{"structural":{"n_chunks":10,"something_new":1,"token_distribution":{"p99":5,"max":3}}},"extra":true}`
	stats := ParseResponse([]byte(body)).StatsFor("structural")
	if stats.NChunks != 10 || stats.TokenDistribution.Max != 3 {
		t.Errorf("estadísticas: %+v", stats)
	}
}

func TestStrategyNamesKeepCanonicalOrderAndQueriesAreUnique(t *testing.T) {
	response := ParseResponse(compareBody([]string{"hierarchical", "structural"}, []string{"a", "b"}, 0))
	if !reflect.DeepEqual(response.StrategyNames(), []string{"structural", "hierarchical"}) {
		t.Errorf("orden: %v", response.StrategyNames())
	}
	if !reflect.DeepEqual(response.Queries(), []string{"a", "b"}) || !response.AnyQueries() {
		t.Errorf("consultas: %v", response.Queries())
	}
	if ParseResponse(compareBody([]string{"structural"}, nil, 0)).AnyQueries() {
		t.Error("sin consultas no hay recuperación")
	}
}

func TestResultsAreGroupedByStrategyForOneQuery(t *testing.T) {
	grouped := ParseResponse(compareBody([]string{"structural", "hierarchical"}, []string{"oauth"}, 0)).ResultsByStrategyFor("oauth")
	if len(grouped) != 2 || grouped[0].Name != "structural" || grouped[0].Result.Query != "oauth" {
		t.Errorf("agrupación: %+v", grouped)
	}
}

func TestHierarchicalTopChunksExposeParentAndChildLevel(t *testing.T) {
	response := ParseResponse(compareBody([]string{"structural", "hierarchical"}, []string{"oauth"}, 0))
	top := response.QueryResultsFor("hierarchical")[0].TopK
	if !top[0].Parent() || !top[1].Child() || top[1].ParentChunkID != "BUD-1::parent" || top[0].CosinePct() != 71 {
		t.Errorf("jerarquía: %+v", top)
	}
	chunk := response.QueryResultsFor("structural")[0].TopK[0]
	if chunk.Level != "" || chunk.Parent() || chunk.Child() {
		t.Errorf("otras estrategias no tienen nivel: %+v", chunk)
	}
	if (TopChunk{Cosine: 1.7}).CosinePct() != 100 || (TopChunk{Cosine: -0.3}).CosinePct() != 0 {
		t.Error("el porcentaje debe acotarse a 0-100")
	}
}

func TestCostsAddUpAndTheMaximumDrivesTheBars(t *testing.T) {
	response := ParseResponse(compareBody([]string{"structural", "contextual_retrieval"}, nil, 0.14))
	if response.TotalIngestionCostUSD() != 0.14 || response.MaxIngestionCostUSD() != 0.14 {
		t.Errorf("costes: %v %v", response.TotalIngestionCostUSD(), response.MaxIngestionCostUSD())
	}
	if ParseResponse(compareBody([]string{"structural"}, nil, 0)).MaxIngestionCostUSD() != 0 {
		t.Error("las gratuitas no tienen coste")
	}
}

func TestAnEmptyOrInvalidPayloadYieldsAnEmptyResponse(t *testing.T) {
	for _, payload := range []string{`{}`, ``, `[1]`, `no json`} {
		response := ParseResponse([]byte(payload))
		if len(response.StrategyNames()) != 0 || response.TotalIngestionCostUSD() != 0 {
			t.Errorf("payload %q debe producir una respuesta vacía", payload)
		}
	}
}

func TestStrategiesOutsideTheCatalogAreKeptAfterTheKnownOnes(t *testing.T) {
	response := ParseResponse([]byte(`{"stats_per_strategy":{"zeta":{"n_chunks":1},"structural":{"n_chunks":2},"alfa":{"n_chunks":3}}}`))
	if got := strings.Join(response.StrategyNames(), ","); got != "structural,alfa,zeta" {
		t.Errorf("orden: %s", got)
	}
}

func TestComparisonValidationLabelsAndDuration(t *testing.T) {
	duration := 1500
	comparison := Comparison{
		Strategies: []string{"structural", "contextual_retrieval"}, TopK: 3, DurationMS: &duration,
		ResponsePayload: compareBody([]string{"structural", "contextual_retrieval"}, nil, 0.14),
	}
	if comparison.Validate() != nil || !reflect.DeepEqual(comparison.StrategyLabels(), []string{"Estructural", "Contextual retrieval"}) {
		t.Errorf("etiquetas: %v", comparison.StrategyLabels())
	}
	if seconds, ok := comparison.DurationSeconds(); !ok || seconds != 1.5 {
		t.Errorf("duración: %v", seconds)
	}
	if comparison.TotalCostUSD() != 0.14 {
		t.Errorf("coste: %v", comparison.TotalCostUSD())
	}
	if _, ok := (Comparison{}).DurationSeconds(); ok {
		t.Error("sin duración registrada debe ser nula")
	}
	for _, invalid := range []Comparison{{TopK: 3}, {Strategies: []string{"a"}, TopK: 0}, {Strategies: []string{"a"}, TopK: 11}} {
		if invalid.Validate() == nil {
			t.Errorf("%+v debería ser inválida", invalid)
		}
	}
	if (Comparison{Strategies: []string{"a"}, TopK: 10}).Validate() != nil {
		t.Error("top_k 10 es válido")
	}
}
