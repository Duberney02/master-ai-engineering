# Tasks

Toda verificación se ejecuta en Docker (ver diseño, decisión 10).

## 1. Transcripciones largas (API)

- [x] 1.1 Añadir `MIN_DESCRIPTION_CHARS`/`MAX_DESCRIPTION_CHARS` (80 000) a `app/schemas/project_estimation.py` y usarlas en `EstimationRequest`; verificar con pruebas de límites (19, 20, 80 000 y 80 001 caracteres → 422 sin llamar al proveedor).
- [x] 1.2 Moderación por tramos de 30 000 caracteres en `InputGuardrails`; verificar con pruebas de PII al final, inyección en mitad, tramo marcado y número de tramos.
- [x] 1.3 Añadir `semantic_cache_max_chars` (8 000) a `Settings`/`.env.example` y omitir la caché semántica por longitud; verificar con pruebas de no embeber ni tocar Redis, y del límite exacto.

## 2. Procedencia de caché e historial

- [x] 2.1 Añadir `cache_source` a `PipelineOutcome` (`none`/`exact`/`semantic`) y a `EstimationResponse` y `EstimationStreamMetadata` junto con `estimation_id`; verificar con pruebas de pipeline y actualizar las de contrato existentes.
- [x] 2.2 Declarar `sqlalchemy[asyncio]`, `asyncpg` y `aiosqlite` (dev); actualizar `uv.lock`; añadir `database_url` a `Settings` y `.env.example`.
- [x] 2.3 Crear `app/services/history.py` (`EstimationHistory`: modelo `estimations`, `save`, `list_recent`, `get`, desactivado sin URL, tolerante a fallos); verificar con SQLite en memoria (guardado, orden, límite, extracto, inexistente, desactivado, base de datos caída).
- [x] 2.4 Crear `app/routers/history.py` y registrarlo en `main.py`; guardar en `/estimate` y `/estimate/stream`; verificar con pruebas de API (200, 404, 422, 503, `estimation_id`, rechazos que no se guardan).
- [x] 2.5 Añadir una prueba de integración con PostgreSQL real activada por `TEST_DATABASE_URL`.

## 3. Streamlit

- [x] 3.1 Adoptar el límite y el mensaje de 80 000, la carga `.txt` y el tiempo transcurrido en `streamlit_app.py`; verificar con `tests/test_streamlit_app.py`.

## 4. Aplicación web Rails

- [x] 4.1 Generar `estimator-web/` con Rails (sin Active Record, Action Mailer ni Active Storage), añadir `faraday` y `webmock`, Dockerfile no-root y ruta `/up`.
- [x] 4.2 Implementar `EstimatorApi` (Faraday) con traducción saneada de errores; verificar con pruebas unitarias (200, 400, 404, 422, 5xx, conexión, tiempo agotado, cuerpo no JSON).
- [x] 4.3 Implementar el formulario y su validación (`ActiveModel`, carga `.txt`), el historial y la vista del resultado con temporizador e indicador de carga; verificar con pruebas de integración (envío, redirección, archivo inválido, longitud, no estimable, historial vacío, API caída).

## 5. Compose raíz y CI

- [x] 5.1 Crear `docker-compose.yml` raíz (API, web, Redis Stack, PostgreSQL, red `estimator-net`, volúmenes, healthchecks); verificar con `docker compose config` y arrancando el stack hasta `healthy`.
- [x] 5.2 Ampliar `test_project_structure.py` con las rutas nuevas y la CI (`estimator-web`, Compose raíz); documentar en los README.

## 6. Barra lateral, métricas y chat en el Compose raíz

- [x] 6.1 Añadir `CallMetrics` y `PipelineOutcome.metrics()`; `metrics` en `EstimationResponse`, en el historial (columna JSON nulable) y en `EstimationDetail`; verificar con pruebas de suma de tokens, API e historial sin métricas.
- [x] 6.2 Crear `GET /api/v1/prompts/estimation` (`app/routers/prompts.py`) y mover `few_shot_examples` a `app/prompts/loader.py`; verificar con pruebas de versión, opciones y 422.
- [x] 6.3 Barra lateral en `estimator-web` (`_sidebar`, `EstimatorApi#prompt_preview`, botón de ocultar); verificar con pruebas de integración (formulario, resultado con métricas, caché y sin tarifa, registro sin métricas, prompt no disponible, error de validación) y en un navegador contra el stack.
- [x] 6.4 Añadir `estimador-cag-chat` (puerto 8501) al Compose raíz y a su prueba de estructura; verificar con el arranque real.

## 7. Verificación

- [x] 7.1 Ejecutar la suite Python completa y la de Rails en Docker; levantar el stack raíz, comprobar `/health`, `/up`, historial vacío vía la web y persistencia contra PostgreSQL real; registrar la evidencia en `verification.md`.
- [x] 7.2 `openspec validate estimador-historial-web-transcripciones-largas --strict`.
