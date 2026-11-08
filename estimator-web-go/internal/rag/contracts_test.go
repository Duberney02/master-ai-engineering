package rag

import (
	"encoding/json"
	"reflect"
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
func TestCatalogHasTheEightStrategiesInCanonicalOrder(t *testing.T) {
	var names []string
	for _, strategy := range Catalog {
		names = append(names, strategy.Name)
	}
	want := []string{"structural", "fixed_size", "recursive", "sentence_window", "hierarchical", "semantic", "propositional", "contextual_retrieval"}
	if !reflect.DeepEqual(names, want) {
		t.Errorf("catálogo: %v", names)
	}
}

func TestFreeStrategiesAreDefaultAndPaidOnesAreOptInAndDeclareTheirKey(t *testing.T) {
	if !reflect.DeepEqual(Defaults(), []string{"structural", "fixed_size", "recursive"}) {
		t.Errorf("por defecto: %v", Defaults())
	}
	paid := map[string]string{}
	for _, strategy := range Catalog {
		if strategy.Paid() {
			paid[strategy.Name] = strategy.KeyName()
		}
		if strategy.Paid() && strategy.DefaultChecked {
			t.Errorf("%s es de pago y no puede venir marcada", strategy.Name)
		}
	}
	want := map[string]string{"semantic": "OPENAI_API_KEY", "propositional": "OPENAI_API_KEY", "contextual_retrieval": "ANTHROPIC_API_KEY"}
	if !reflect.DeepEqual(paid, want) {
		t.Errorf("de pago: %v", paid)
	}
	if strategy, ok := Find("structural"); !ok || strategy.KeyName() != "" || strategy.CostLabel() != "gratis" {
		t.Errorf("estructural: %+v", strategy)
	}
	if _, ok := Find("magic"); ok {
		t.Error("una estrategia desconocida no se encuentra")
	}
	if LabelFor("fixed_size") != "Tamaño fijo" || LabelFor("magic") != "magic" {
		t.Error("etiquetas")
	}
}

func TestCostsAddUp(t *testing.T) {
	response := ParseResponse(compareBody([]string{"structural", "contextual_retrieval"}, nil, 0.14))
	if response.TotalIngestionCostUSD() != 0.14 {
		t.Errorf("coste: %v", response.TotalIngestionCostUSD())
	}
	if ParseResponse(compareBody([]string{"structural"}, nil, 0)).TotalIngestionCostUSD() != 0 {
		t.Error("las gratuitas no tienen coste")
	}
}

func TestUnknownAttributesFromANewerServiceAreIgnored(t *testing.T) {
	body := `{"stats_per_strategy":{"structural":{"n_chunks":10,"something_new":1,"ingestion_cost_usd":0.5}},"extra":true}`
	if got := ParseResponse([]byte(body)).TotalIngestionCostUSD(); got != 0.5 {
		t.Errorf("coste: %v", got)
	}
}

func TestAnEmptyOrInvalidPayloadYieldsAnEmptyResponse(t *testing.T) {
	for _, payload := range []string{`{}`, ``, `[1]`, `no json`} {
		if got := ParseResponse([]byte(payload)).TotalIngestionCostUSD(); got != 0 {
			t.Errorf("payload %q debe producir una respuesta vacía", payload)
		}
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
