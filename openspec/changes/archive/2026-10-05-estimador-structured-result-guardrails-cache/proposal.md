# Proposal

## Why

`POST /api/v1/estimate` devuelve hoy texto libre (`{text, prompt_version}`): no se puede comprobar que las cifras sean coherentes, ni presentar una estimación inviable de forma distinta, ni reutilizar respuestas parecidas. Además, la descripción del usuario llega al modelo sin ningún filtro (moderación, inyección de prompt, datos personales) y la lógica está repartida en el router. Esta sesión convierte el endpoint en un pipeline tipado, validado, protegido y con caché semántica.

## What Changes

- **BREAKING** `POST /api/v1/estimate` responde `{result, prompt_version, cached}`, donde `result` es un `EstimationResult` (`summary`, `confidence_pct`, `phases`, `total_duration_weeks`, `total_cost_eur`) con fases `Phase` (`name`, `description`, `duration_weeks`, `cost_eur`).
- Validación de negocio con corrección automática: la suma de costes de las fases coincide con el total y una confianza inferior al 30 % exige un `summary` que empiece por `Out of scope:`. Si la validación falla, se vuelve a pedir al modelo con el error concreto (máximo configurable de intentos); si se agotan, 502 saneado.
- Estimaciones fuera de alcance: filtro de baja confianza que normaliza el resultado con una fase placeholder (coste 0, una semana), expone `out_of_scope` y una presentación «no estimable» en el cliente.
- Guardrails de entrada previos a cualquier caché: moderación, heurística de prompt injection y detección de correos, teléfonos e IBAN. Un rechazo es HTTP 400 con `{reason, message}`.
- Caché semántica con `redisvl` y embeddings: búsqueda por similitud coseno, entradas separadas por versión de prompt, tipo de proyecto, detalle y formato; umbral, TTL y modo `log_only` configurables.
- Redis Stack (RediSearch) sustituye a Redis estándar en Compose; nuevas dependencias y variables de configuración.
- Nuevo `EstimationPipeline` inyectable con `Depends` que coordina guardrails → caché exacta → caché semántica → render → generación tipada → validación → almacenamiento.
- `POST /api/v1/estimate/stream` pasa a emitir el resultado validado (`result`, `metadata`, `done`) porque un JSON no es válido hasta estar completo; el cliente Streamlit lo presenta, incluido «no estimable».
- Nueva versión de prompt `v3` (por defecto) diseñada para salida estructurada; `v1` y `v2` siguen disponibles.

## Capabilities

### New Capabilities

- `estimator/input-guardrails`: moderación, prompt injection y datos personales antes de las cachés.
- `estimator/output-validation`: reglas de negocio, reintento con corrección y tratamiento de fuera de alcance.
- `estimator/semantic-cache`: embeddings y búsqueda coseno con `redisvl`, aislamiento por versión/tipo/detalle/formato, TTL y `log_only`.
- `estimator/estimation-pipeline`: servicio central inyectable que coordina todas las etapas.

### Modified Capabilities

- `estimator/structured-estimation`: la respuesta pasa a ser `{result, prompt_version, cached}`, los guardrails rechazan con 400, el stream emite el resultado validado (`result`, `metadata`, `done`) y el cliente presenta «no estimable».

## Impact

- Código: `app/schemas/project_estimation.py`, nuevos `app/services/{guardrails,embeddings,semantic_cache,validation,pipeline}.py`, `app/routers/project_estimations.py`, `app/config.py`, `app/main.py`, `app/prompts/estimation/v3/`, `app/streamlit_client.py`, `streamlit_app.py`.
- Infraestructura: `docker-compose.yml` (imagen `redis/redis-stack-server`), `.env.example`, `pyproject.toml` (`redisvl`), `uv.lock`.
- Los consumidores de `/api/v1/estimate` deben leer `result` en lugar de `text`. El flujo `/api/v1/transcription/*` no cambia.
- Sin claves reales en pruebas: moderación, embeddings, Redis y proveedor se simulan.
