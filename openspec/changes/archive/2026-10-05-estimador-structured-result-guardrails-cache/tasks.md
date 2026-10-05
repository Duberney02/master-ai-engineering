# Tasks

## 1. Base y configuración

- [x] 1.1 Declarar `redisvl` en pyproject y actualizar uv.lock; añadir a `Settings` las variables de moderación, embeddings, caché semántica y validación (con valores por defecto) y documentarlas en `.env.example`; verificar con `tests/test_config.py` (valores por defecto, rangos y modo inválido).
- [x] 1.2 Sustituir Redis por `redis/redis-stack-server` en `docker-compose.yml`; verificar con `docker compose config`.

## 2. Contrato y validación

- [x] 2.1 Crear `Phase`, `EstimationResult`, `out_of_scope` y la nueva `EstimationResponse` (`result`, `prompt_version`, `cached`) y reexportarlos en `app.schemas`; verificar con pruebas de rangos y de campo calculado.
- [x] 2.2 Crear `app/services/validation.py` con extracción de JSON, reglas de negocio, filtro de fuera de alcance y mensaje de corrección; verificar con pruebas de suma, prefijo `Out of scope:`, JSON con vallas de código, normalización a placeholder y tolerancia de 0,01 EUR.
- [x] 2.3 Escribir las plantillas `v3` y el bloque de contrato JSON para `v1`/`v2`, y pasar `DEFAULT_PROMPT_VERSION` a `v3`; verificar con `tests/prompts/test_estimation_v3.py` y ajustar las pruebas de `v1`/`v2` y del loader.

## 3. Guardrails

- [x] 3.1 Crear `app/services/guardrails.py` con PII (correo, teléfono, IBAN mod-97), prompt injection y moderación asíncrona, y `GuardrailViolation`; verificar con pruebas por razón, falsos positivos, mensajes sin el valor detectado y moderación simulada (marcada, caída, sin clave).
- [x] 3.2 Registrar el manejador de `GuardrailViolation` en `main.py` (400 con `reason` y `message`); verificar con una prueba de API.

## 4. Caché semántica

- [x] 4.1 Crear `app/services/embeddings.py` (`OpenAIEmbedder`) y `app/services/semantic_cache.py` sobre `redisvl` con filtros por atributos, conversión de umbral, TTL, `log_only` y tolerancia a fallos; verificar con dobles de `redisvl` y del embedder (acierto, umbral, atributo distinto, `log_only`, error, desactivada).
- [x] 4.2 Añadir la caché exacta de resultados (`estimation:v2:`) a `app/services/cache.py`; verificar con pruebas de clave estable y de payload inválido.

## 5. Pipeline y endpoints

- [x] 5.1 Crear `app/services/pipeline.py` con `EstimationPipeline`, `PipelineOutcome` y `get_pipeline`, y el bucle de generación tipada con reintentos y suma de uso; verificar con pruebas de orden de etapas, aciertos de cada caché, resultado cacheado inválido, corrección en el segundo intento y agotamiento (502).
- [x] 5.2 Reescribir `app/routers/project_estimations.py` para delegar en el pipeline con `Depends`, incluido `/estimate/stream` con eventos `result`, `metadata` y `done`; verificar con `tests/test_project_estimations.py` actualizado (200, 400, 422, stream, `dependency_overrides`).

## 6. Cliente y documentación

- [x] 6.1 Actualizar `streamlit_client.py` y `streamlit_app.py` para el evento `result`, la presentación «No estimable» y los errores 400; verificar con AppTest y pruebas del cliente.
- [x] 6.2 Actualizar README, `docs/`, Postman y `curls.md` al nuevo contrato y a Redis Stack; verificar con búsqueda de referencias a `text` y a `redis:7-alpine`.

## 7. Integración

- [x] 7.1 Ejecutar la suite completa, `compileall`, `git diff --check` y `openspec validate --all --strict`, y registrar resultados y límites en `verification.md`.
