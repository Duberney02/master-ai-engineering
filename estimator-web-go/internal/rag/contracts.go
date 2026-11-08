package rag

import (
	"math"

	"estimator-web/internal/jsondoc"
)

// El backend no interpreta la respuesta de POST /embeddings/compare: la guarda tal cual en el historial y la reexpone
// a los clientes, que la tipan (estadísticas por estrategia y top-k por consulta). Solo lee de ella el coste de
// ingesta por estrategia (`stats_per_strategy[*].ingestion_cost_usd`, del schema `ChunkingStats`) para resumir cada
// ejecución en el historial. Los atributos desconocidos que añada una versión nueva del servicio se ignoran.

// ComparisonResponse es el resumen de costes de la respuesta de la API (o de la guardada en el historial).
type ComparisonResponse struct {
	costs map[string]float64
}

// ParseResponse construye el resumen a partir del JSON de la API; un cuerpo inválido da un resumen vacío.
func ParseResponse(payload []byte) ComparisonResponse {
	response := ComparisonResponse{costs: map[string]float64{}}
	for name, raw := range jsondoc.ParseDoc(payload).Doc("stats_per_strategy") {
		response.costs[name] = jsondoc.From(raw).Float("ingestion_cost_usd")
	}
	return response
}

// TotalIngestionCostUSD es la suma del coste de ingesta, redondeada a 6 decimales.
func (r ComparisonResponse) TotalIngestionCostUSD() float64 {
	total := 0.0
	for _, cost := range r.costs {
		total += cost
	}
	return math.Round(total*1e6) / 1e6
}
