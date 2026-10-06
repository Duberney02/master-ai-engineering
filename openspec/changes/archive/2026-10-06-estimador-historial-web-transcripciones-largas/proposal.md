# Proposal

## Why

El estimador solo acepta descripciones de hasta 2000 caracteres, por lo que no puede estimar a partir de la transcripción completa de una reunión. Además, cada estimación se pierde al cerrar el cliente (solo hay cachés con TTL), la única interfaz es un chat de Streamlit y levantar el sistema completo exige coordinar varios Compose. Este cambio habilita transcripciones largas, conserva un historial consultable y ofrece una aplicación web y un arranque único desde la raíz.

## What Changes

- Ampliar `description` de `POST /api/v1/estimate[/stream]` de 2000 a **80 000** caracteres (mínimo 20 sin cambios), con mensajes de validación actualizados en los clientes. Los guardrails evalúan el texto completo y la moderación lo envía por tramos. La caché semántica se omite por encima de un umbral configurable de caracteres (los embeddings tienen un límite de tokens); la caché exacta sigue funcionando.
- Historial persistente en PostgreSQL: cada estimación completada guarda descripción, opciones, resultado JSON, versión de prompt, procedencia de caché (`none`, `exact`, `semantic`) y fechas. Nuevos endpoints `GET /api/v1/estimations` (últimas N) y `GET /api/v1/estimations/{id}`. Sin `DATABASE_URL` el historial queda desactivado (503 en los endpoints de lectura) y las estimaciones siguen funcionando; un fallo de escritura nunca rompe la estimación.
- Respuesta de `/estimate` y metadatos del stream ganan, de forma aditiva, `cache_source` y `estimation_id`; `/estimate` añade `metrics` (modelo, tokens, latencia, coste y caché de la llamada), que el historial también guarda. Nuevo `GET /api/v1/prompts/estimation` con el prompt de sistema renderizado y los ejemplos few-shot de una versión y unas opciones.
- Nueva aplicación **`estimator-web`** (Rails + Faraday): formulario con carga de archivos `.txt`, indicador de carga y temporizador, historial de las últimas estimaciones, vista del resultado con duración, coste, confianza y tabla de fases, y una **barra lateral izquierda** equivalente a la de Streamlit (prompt de sistema, ejemplos few-shot y métricas de la última llamada). Errores de la API traducidos a mensajes saneados.
- El cliente Streamlit adopta el nuevo límite y mensaje, la carga de `.txt` y muestra el tiempo transcurrido (equivalencia funcional).
- Nuevo `docker-compose.yml` en la raíz del repositorio con API, chat Streamlit (puerto 8501), `estimator-web` (3000), Redis Stack y PostgreSQL en una red compartida, con volúmenes y healthchecks.
- Pruebas: validadores y rechazos de entrada, baja confianza, aislamiento/umbral/`log_only` de la caché semántica, persistencia y manejo de errores del cliente web.

## Capabilities

### New Capabilities

- `estimator/estimation-history`: persistencia en PostgreSQL (incluidas las métricas de la llamada), listado y consulta individual.
- `estimator/prompt-preview`: prompt de sistema renderizado y ejemplos few-shot por HTTP.
- `estimator/web-client`: aplicación Rails `estimator-web` (formulario, carga `.txt`, barra lateral de contexto, historial, resultado, errores).
- `estimator/deployment-stack`: Compose raíz con red compartida, volúmenes y healthchecks.

### Modified Capabilities

- `estimator/structured-estimation`: límite de 80 000 caracteres, campos aditivos `cache_source`/`estimation_id`/`metrics` y cliente Streamlit con `.txt` y temporizador.
- `estimator/estimation-pipeline`: el resultado informa la procedencia de caché y las métricas de la llamada.
- `estimator/input-guardrails`: comportamiento con textos largos.
- `estimator/semantic-cache`: omisión por longitud.

## Impact

- Código: `app/schemas/project_estimation.py`, `app/config.py`, `app/main.py`, `app/services/{pipeline,guardrails,semantic_cache,history}.py`, `app/routers/{project_estimations,history,prompts}.py`, `app/prompts/loader.py` (`few_shot_examples`), `app/schemas/history.py`, `app/streamlit_client.py`, `streamlit_app.py`, nuevo `estimator-web/`, `docker-compose.yml` raíz, `.env.example`, `pyproject.toml`/`uv.lock` (`sqlalchemy[asyncio]`, `asyncpg`; dev: `aiosqlite`), CI y READMEs.
- Compatibilidad: contratos aditivos; el límite superior solo se relaja. El flujo `/api/v1/transcription/*` no cambia.
- Sin claves reales en pruebas: PostgreSQL se sustituye por SQLite en memoria y la API por dobles HTTP; una prueba de integración opcional usa PostgreSQL real vía `TEST_DATABASE_URL`.
