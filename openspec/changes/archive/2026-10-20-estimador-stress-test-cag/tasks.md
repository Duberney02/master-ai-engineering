# Tasks

Todo se ejecuta en Docker: `docker compose -f docker-compose.verify.yml run --rm api-test` (el `.venv` del host está bloqueado por la política de aplicaciones de Windows).

## 1. Instrumentación por turno

- [x] 1.1 Añadir `TurnObservation`, `Session.turns_total`/`last_turn`, `EstimationRequest.attachments_chars` y los campos de `SAFE_FIELDS`; emitir `turn_observed` en `SessionEstimationService.commit()`; verificar con `tests/test_turn_observed.py`.
- [x] 1.2 Exponer `last_turn` y `include_memory` en `GET /sessions/{id}` (aditivo); verificar con la misma prueba y las de estado existentes.

## 2. Escenarios y adjuntos

- [x] 2.1 Crear `evals/stress/scenarios.py` (perfiles, checkpoints, fact-tracker); verificar con `tests/test_stress_scenarios.py`.
- [x] 2.2 Crear `evals/stress/fixtures/build_pdfs.py` (fpdf2, manifiesto, `.gitignore`); verificar tamaños y determinismo.

## 3. Métricas

- [x] 3.1 Crear `evals/stress/metrics.py` (`LatencyBudgetMetric`, `CostBudgetMetric`, `MemoryDriftMetric`) y documentar presupuestos; verificar con `tests/test_stress_metrics.py` (éxito, fallo, límites).

## 4. Runner, CSV y reporte

- [x] 4.1 Crear `evals/stress/run.py` (HTTP/en proceso, CSV por turno, `--workers`); verificar con una prueba en proceso con proveedores simulados.
- [x] 4.2 Crear `evals/stress/report.py` y generar `REPORT.md` desde un CSV; verificar con prueba sobre un CSV sintético.
- [x] 4.3 Ejecutar las mediciones reales (≥ 50 filas) y versionar `results.csv` y `REPORT.md`.

## 5. Cierre

- [x] 5.1 Documentar uso en el README; ejecutar `pytest`, `ruff` y `openspec validate --all --strict`; registrar el resultado en `verification.md`.
