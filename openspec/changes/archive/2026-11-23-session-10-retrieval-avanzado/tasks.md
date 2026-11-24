# Tasks

Requiere `session-09-rag-estimacion-fundamentada` aplicado. Verificaciones en Docker desde la raíz
(`docker compose -f docker-compose.verify.yml run --rm …`).

## 1. Dependencias y configuración

- [x] 1.1 Añadir `sentence-transformers` a `pyproject.toml`, regenerar `uv.lock` con `api-uv lock` y reconstruir `api-test`; verificar que `api-test -q` sigue en verde
- [x] 1.2 Añadir a `Settings` los parámetros de modo de búsqueda, *reranker*, `rrf_k`, *routing*, transformación, *decay* y horas por tarea, documentados en `.env.example`; verificar con tests de validación de rangos en `tests/test_config.py`

## 2. Persistencia

- [x] 2.1 Crear la migración `0004` (columna `content_tsv` generada + GIN en `chunks`) y verificar contra `api-db` que `upgrade`/`downgrade`/`alembic check` pasan
- [x] 2.2 Crear la migración `0005` (`transcript_chunks`, `technical_doc_chunks`) y sus modelos ORM; verificar `alembic check` y que `tests/test_search_halfvec.py` sigue en verde

## 3. Híbrido y reranking

- [x] 3.1 Implementar la rama léxica y la fusión RRF; verificar con tests unitarios de RRF y un test de integración del identificador léxico
- [x] 3.2 Implementar el *reranker* con carga diferida y su fábrica falsificable; verificar con un *reranker* falso que reordena (`tests/test_reranker.py`)
- [x] 3.3 Añadir `search_mode`/`rerank` opcionales a `/v1/retrieval/search` con la precedencia petición → runtime → settings; verificar con tests de API

## 4. Configuración de recuperación en runtime

- [x] 4.1 Extender el runtime config con los *toggles* de recuperación y exponer `GET/PUT /api/v1/config/retrieval`; verificar con `fakeredis` (parcial, `null`, `422`, `503`)

## 5. Multi-índice y búsqueda avanzada

- [x] 5.1 Implementar el registro de colecciones y los filtros duros; verificar con tests unitarios de mapeo y fecha por colección
- [x] 5.2 Implementar el *router* en cascada; verificar los cuatro niveles con un clasificador falso
- [x] 5.3 Implementar la transformación de consulta (heurística + generación, máx. 4); verificar elección de técnica y degradación a `direct`
- [x] 5.4 Implementar el *decay* temporal; verificar con tests puros de peso y desempate
- [x] 5.5 Implementar el pipeline avanzado y `POST /v1/retrieval/advanced-search`; verificar con tests de API (diagnóstico, cardinalidad 0, 401, 429, 502)
- [x] 5.6 Portar los datos de transcripciones y documentación técnica y `scripts/build_multi_index_corpus.py`; verificar ejecutándolo dos veces contra el stack sin duplicar

## 6. Horas por tarea

- [x] 6.1 Implementar el consenso ponderado y la fiabilidad como funciones puras; verificar con `tests/test_task_hours.py`
- [x] 6.2 Exponer `POST /v1/estimate/stages/structure` y `POST /v1/estimate/tasks/hours`; verificar con tests de API (horas nulas en la estructura, `has_match=false`)

## 7. Evaluación y documentación

- [x] 7.1 Portar `evals/golden_retrieval.json` y `scripts/eval_retrieval_s10.py`; verificar ejecutándolo con `--entrypoint python api-test` contra el stack con el corpus ingestado
- [x] 7.2 Documentar en `README.md`/`ARCHITECTURE.md` los modos, la búsqueda avanzada, la configuración de runtime y las horas por tarea; verificar que los ejemplos documentados responden

## 8. Integración

- [x] 8.1 Ejecutar `api-test`, `api-lint` y `openspec validate --all --strict` en Docker y verificar que todo queda en verde
