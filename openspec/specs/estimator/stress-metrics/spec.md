# estimator/stress-metrics Specification

## Purpose
Medir presupuestos de latencia y coste por turno y la deriva de memoria con métricas deterministas.

## Requirements

### Requirement: LatencyBudgetMetric
La métrica SHALL devolver un `MetricResult` con puntuación 1.0 y `passed` verdadero si `latency_ms` es menor o igual que `budget_ms` y 0.0 en otro caso (el límite es inclusivo).

#### Scenario: Dentro y fuera del presupuesto
- **WHEN** la latencia es igual al presupuesto, y cuando lo supera en 1 ms
- **THEN** la puntuación es 1.0 en el primer caso y 0.0 en el segundo.

### Requirement: CostBudgetMetric
La métrica SHALL devolver 1.0 si `cost_usd` es menor o igual que `budget_usd` y 0.0 en otro caso. Un coste desconocido (nulo) SHALL puntuar 0.0 y declararlo en los detalles.

#### Scenario: Coste desconocido
- **WHEN** el coste es nulo
- **THEN** la puntuación es 0.0 y `details` indica que el coste es desconocido.

### Requirement: MemoryDriftMetric
La métrica SHALL devolver 1.0 si el hecho aparece, con coincidencia exacta sin distinguir mayúsculas y sin embeddings ni LLM, en el resumen, las anclas o los `ProjectMetadata` de un snapshot posterior al turno que lo introdujo, y 0.0 en otro caso. `details` SHALL indicar dónde se encontró. Un snapshot del mismo turno o anterior SHALL ser un error de uso.

#### Scenario: Hecho conservado
- **WHEN** el nombre original aparece en el nombre del proyecto del snapshot
- **THEN** la puntuación es 1.0 y `details.found_in` incluye `metadata`.

#### Scenario: Hecho olvidado
- **WHEN** el hecho no aparece en ninguna de las tres fuentes
- **THEN** la puntuación es 0.0.
