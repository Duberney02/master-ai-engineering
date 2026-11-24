# Tasks

Todas las verificaciones se ejecutan en Docker desde la raíz (`docker compose -f docker-compose.verify.yml run --rm …`).

## 1. Configuración y dependencias

- [x] 1.1 Añadir `slowapi` a `estimador-cag/pyproject.toml`, regenerar `uv.lock` con `api-uv lock` y reconstruir `api-test`; verificar que `api-test -q` sigue en verde
- [x] 1.2 Añadir a `Settings` `reformulation_model`, `generation_model`, `retrieval_top_k`, `retrieval_distance_threshold`, `max_context_tokens`, `idempotency_ttl`, `retrieval_api_key`, `estimate_api_key`, y documentarlos en `.env.example`; verificar con un test en `tests/test_config.py`

## 2. Seguridad, rate limiting y correlación

- [x] 2.1 Implementar las dependencias de clave de API (comparación en tiempo constante, `401` + `WWW-Authenticate`) y verificar con `tests/test_rag_security.py` (clave ausente, errónea, cruzada, no configurada)
- [x] 2.2 Configurar el limitador por `X-API-Key` y el handler `429` con `Retry-After`; verificar con `tests/test_rag_rate_limiting.py` (límite superado y cubos por clave)
- [x] 2.3 Añadir el middleware `X-Request-ID` y el registro de etapas con duración; verificar con un test que la cabecera se propaga o se genera y que los logs llevan `request_id`

## 3. Recuperación filtrada

- [x] 3.1 Añadir esquemas `RetrievalRequest`, `RetrievedChunk`, `RetrievalResult` y la búsqueda con filtros JSONB + umbral en `generation/rag/`; verificar con tests de integración contra `api-db` (filtro por sector, umbral, soft-fail) y con un test de que el statement mantiene la expresión halfvec
- [x] 3.2 Exponer `POST /v1/retrieval/search` con errores `500`/`502` saneados; verificar con `tests/test_retrieval_api.py`

## 4. Estimación fundamentada

- [x] 4.1 Implementar el reformulador (brief estructurado + texto de búsqueda canónico) con plantilla en `foundation/prompts/rag/`; verificar con tests usando un generador falso
- [x] 4.2 Implementar el ensamblador (bloque `<source id=…>` y truncado por presupuesto de tokens con chunks completos); verificar con tests unitarios
- [x] 4.3 Implementar el esquema `Estimate` (módulos/tareas, citas, supuestos, confianza) y la regla de coherencia; verificar con tests de validación
- [x] 4.4 Implementar el orquestador (soft-fail → `insufficient`, reintento ante ids inventados, rebaja a `low`, reparación de coherencia) y verificar con `tests/test_grounded_estimation.py` cubriendo cada escenario del spec
- [x] 4.5 Implementar el almacén de idempotencia (Redis asíncrono + memoria) y verificar con `fakeredis` y sin Redis
- [x] 4.6 Exponer `POST /v1/estimate/from-transcript` y registrar las fábricas en `app/dependencies.py`; verificar con tests de API (200, 422, 401, 502, idempotencia) y que `tests/test_layer_dependencies.py` sigue en verde

## 5. Endpoints por etapa

- [x] 5.1 Exponer `/v1/estimate/stages/{reformulate,retrieve,assemble,generate}` reutilizando las funciones del orquestador; verificar con `tests/test_estimate_stages.py` (cadena completa e ids inventados)

## 6. Datos y documentación

- [x] 6.1 Portar `scripts/build_task_corpus.py` (determinista, idempotente) e ingestarlo con `chunk_type="historical_task"`; verificar ejecutándolo dos veces contra el stack y comprobando que no duplica
- [x] 6.2 Actualizar `estimador-cag/README.md` y `ARCHITECTURE.md` (endpoints, claves, límites, flujo RAG) y retirar el «hueco de la Sesión 8»; verificar que los ejemplos `curl` documentados responden contra `docker compose up`

## 7. Integración

- [x] 7.1 Ejecutar `api-test`, `api-lint` y `openspec validate --all --strict` en Docker y verificar que todo queda en verde
