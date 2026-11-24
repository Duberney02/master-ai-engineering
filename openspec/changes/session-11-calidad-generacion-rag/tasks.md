# Tasks

Requiere `session-09-rag-estimacion-fundamentada` y `session-10-retrieval-avanzado` aplicados. Verificaciones en
Docker desde la raíz (`docker compose -f docker-compose.verify.yml run --rm …`).

## 1. Configuración

- [x] 1.1 Añadir a `Settings` y a los *toggles* de runtime los parámetros del *gate*, la aumentación y la síntesis, documentados en `.env.example`; verificar con tests de config y de `GET /api/v1/config/retrieval`

## 2. Citas por línea

- [x] 2.1 Extender el esquema de tarea con `grounded`/`sources` (cita con `evidence`) y su validador de integridad; verificar con tests de validación
- [x] 2.2 Exponer `document_id` en cada `<source>` y exigir la atribución por línea en la plantilla de generación; verificar con un test de renderizado del prompt
- [x] 2.3 Implementar el informe de citas por línea e integrarlo en el orquestador y en `stages/generate`; verificar con `tests/test_citation_verification.py` (grounded, dangling, insufficient, reintento y rebaja)
- [x] 2.4 Portar `scripts/demo_verify_citations_s11.py` (offline); verificar que imprime `ACCEPTANCE: PASS` con `--entrypoint python api-test`

## 3. Gate de alucinaciones

- [x] 3.1 Implementar ancla numérica y calificación por línea como funciones puras; verificar sobreestimación, fracción e `insufficient`
- [x] 3.2 Implementar el juez en una sola llamada y el conductor del *gate*; verificar con un generador falso y la rebaja `high` → `low`
- [x] 3.3 Exponer `POST /v1/estimate/stages/verify` (15/min); verificar con tests de API, incluido `use_judge=false` sin llamada al LLM

## 4. Aumentación y síntesis

- [x] 4.1 Implementar compresión extractiva y reordenación de bordes e integrarlas tras el truncado; verificar ids preservados y extremos fuertes
- [x] 4.2 Implementar la dispersión y el rango (LLM + determinista) en horas por tarea; verificar el caso 40 h/90 h, el caso coherente y el *fallback* sin LLM
- [ ] 4.3 Portar `scripts/build_contradictions_s11.py` (idempotente); verificar ejecutándolo dos veces contra el stack sin duplicar

## 5. Expansión del corpus

- [x] 5.1 Crear la migración HNSW de `transcript_chunks`/`technical_doc_chunks`; verificar `upgrade`/`downgrade`/`alembic check` y el `EXPLAIN` contra `api-db`
- [x] 5.2 Implementar el servicio de expansión (omite duplicados, progreso) y los endpoints `/embeddings/index/{runs,jobs/{id},stats}`; verificar con tests de integración (202, duplicado, 404, estadísticas)

## 6. Evaluación de generación

- [x] 6.1 Añadir `ragas` y `datasets` al grupo `dev` (o al servicio aislado si chocan), regenerar `uv.lock` y reconstruir `api-test`; verificar que `api-test -q` sigue en verde
- [ ] 6.2 Portar `evals/golden_generation_s11.json`, `scripts/eval_ragas_s11.py` y `scripts/score_ragas_s11.py`; verificar la recolección con `--collect-only` contra el stack
- [x] 6.3 Portar `scripts/eval_generation_s11.py` (`--gate`/`--monitor`); verificar con tests de umbral y código de salida usando métricas falsas
- [ ] 6.4 Generar la línea base propia (`evals/ragas_baseline_s11.json` + informe) con claves reales fuera de las pruebas y versionarla

## 7. Documentación e integración

- [x] 7.1 Documentar citas por línea, *gate*, aumentación, rangos, expansión y RAGAS en `README.md`/`ARCHITECTURE.md`; verificar que los ejemplos documentados responden
- [x] 7.2 Ejecutar `api-test`, `api-lint` y `openspec validate --all --strict` en Docker y verificar que todo queda en verde
