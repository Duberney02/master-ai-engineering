# estimator/stress-runner Specification

## Purpose
Ejecutar los escenarios contra la API, volcar un CSV por turno y generar el reporte del baseline.

## Requirements

### Requirement: Runner de stress
`python -m evals.stress.run` SHALL aceptar `--http URL` (sin ella, en proceso con `TestClient`), `--scenarios`, `--attachment-sizes`, `--repeats` y `--output`; SHALL crear una sesión por escenario × tamaño × repetición, ejecutar los turnos, consultar `GET /sessions/{id}?include_memory=true` tras cada uno, evaluar las métricas y escribir una fila por turno con los campos de `turn_observed`, las métricas y los identificadores de agrupación. Un turno fallido SHALL producir su fila con el error y no interrumpir la ejecución. SHALL regenerar los PDFs antes de medir.

#### Scenario: Matriz completa
- **WHEN** se piden 3 escenarios, 2 tamaños y 2 repeticiones con 3 turnos
- **THEN** el CSV contiene 36 filas.

#### Scenario: Turno con error
- **WHEN** la API responde 413 en un turno
- **THEN** la fila de ese turno incluye `http_status` 413 y `error`, y la sesión continúa.

### Requirement: Reporte
`evals/stress/report.py` SHALL generar `REPORT.md` a partir del CSV con la tabla por escenario × tamaño (P50/P95 de latencia, coste acumulado, tasas de acierto exacto y semántico, recall medio), las curvas latencia vs `tokens_in`, coste acumulado vs turno y recall vs N en tablas Markdown, el análisis de dónde degrada el CAG y las instrucciones de reproducción. Las cifras SHALL provenir del CSV.

#### Scenario: Generación desde CSV
- **WHEN** se ejecuta el generador sobre un CSV
- **THEN** el reporte contiene las tres curvas y la tabla por escenario × tamaño.
