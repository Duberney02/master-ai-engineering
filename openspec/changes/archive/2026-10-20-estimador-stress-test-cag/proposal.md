# Proposal

## Why

La sesión 6 introduce RAG como alternativa a la memoria CAG (contexto completo + resumen + anclas). Sin un baseline cuantitativo de dónde degrada el CAG actual —latencia, coste, tokens y recuerdo de hechos a medida que crecen los turnos y los adjuntos— cualquier comparación posterior sería anecdótica. El servicio tampoco expone hoy qué ocurrió en cada turno (tokens, coste, ventana, resumen, anclas) de forma consultable.

## What Changes

- **Instrumentación por turno**: evento structlog `turn_observed` al confirmar cada turno de sesión, con el mismo contenido embebido como `last_turn` en `GET /api/v1/sessions/{id}` (aditivo) para poder medir por HTTP sin acceso a los logs del servidor. Opcionalmente `?include_memory=true` devuelve el resumen y las anclas para evaluar la deriva de memoria.
- **Paquete `evals/stress/`**: escenarios multi-turno (`growing`, `pivot`, `contradiction`; N ∈ {1, 3, 6, 10, 20}) con fact-tracker; generador determinista de PDFs sintéticos (5, 20, 50 y 100 KB); métricas deterministas `LatencyBudgetMetric`, `CostBudgetMetric` y `MemoryDriftMetric` (reutilizan `MetricResult`); runner `python -m evals.stress.run` (HTTP o en proceso) que escribe un CSV con una fila por turno; generador de `REPORT.md` a partir del CSV.
- **Mediciones reales** (`results.csv`) y reporte (`REPORT.md`) versionados como baseline.

**No incluido**: RAG, optimizaciones del CAG, cambio de constantes, comparación de proveedores, notebooks, gráficos, interfaz o bases de datos.

## Capabilities

### New Capabilities
- `estimator/turn-observability`: evento `turn_observed` y último turno en el estado de sesión.
- `estimator/stress-scenarios`: escenarios, fact-tracker y adjuntos sintéticos.
- `estimator/stress-metrics`: presupuestos de latencia y coste y deriva de memoria.
- `estimator/stress-runner`: runner, CSV y reporte.

### Modified Capabilities
- Ninguna con cambio de requisitos existentes: `GET /sessions/{id}` solo gana campos opcionales.

## Impact

- Código: `app/services/sessions.py`, `app/services/session_estimation.py`, `app/schemas/sessions.py`, `app/routers/sessions.py`, `app/schemas/project_estimation.py` (campo excluido `attachments_chars`), `app/logging_config.py` (campos permitidos); paquete nuevo `evals/stress/`; pruebas nuevas.
- Dependencias: `fpdf2` solo en el grupo `dev`.
- Las pruebas nunca requieren claves reales; las mediciones reales las ejecuta el usuario con su proveedor.
