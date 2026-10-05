# Design

## Context

`/api/v1/estimate` renderiza plantillas Jinja2 y llama a `generate_from_prompts`, que delega en `LLMWrapper` (caché de completions, reintentos, fallback, costes). El router contiene la orquestación. `EstimationCache` usa Redis estándar con claves exactas. Los SDK son asíncronos y las pruebas los parchean en `app.services.llm_service`.

## Goals / Non-Goals

**Goals:**
- Resultado tipado y verificable por reglas de negocio, con corrección automática.
- Guardrails baratos y deterministas antes de gastar caché, embeddings o tokens.
- Caché semántica segura: nunca mezcla versión de prompt, tipo, detalle ni formato.
- Un único servicio de pipeline, sustituible en pruebas con `dependency_overrides`.

**Non-Goals:**
- Cambiar el flujo `/api/v1/transcription/*`.
- Streaming token a token del resultado estructurado.
- Moderación local o entrenada: se usa el endpoint de moderación del proveedor y heurísticas.

## Decisions

1. **Corrección automática propia en lugar de la librería Instructor.** Instructor se acopla al cliente del SDK y esquivaría `LLMWrapper` (caché, fallback, costes y errores saneados). Un bucle propio (generar → extraer JSON → validar con Pydantic y reglas de negocio → reintentar con el error en el mensaje de usuario) es el mecanismo equivalente que admite el requisito, reutiliza el wrapper sin tocar los adaptadores y se prueba con los dobles existentes. Se registra el número de intentos y se suman tokens y costes. Alternativa descartada: Instructor, por duplicar la política de proveedor.
2. **Modelos en `app/schemas/project_estimation.py`.** `Phase` y `EstimationResult` con restricciones de campo (`ge=0`, `gt=0`, `confidence_pct` 0–100). Las reglas de negocio (suma de costes con tolerancia de 0,01 EUR; confianza < 30 → `Out of scope:`) viven en `app/services/validation.py`, no en el modelo, para producir mensajes de corrección y poder revalidar resultados leídos de caché. `out_of_scope` es un campo calculado (`confidence_pct < 30`).
3. **Fuera de alcance.** Tras validar, si `out_of_scope`, el resultado se normaliza: una sola fase placeholder (`name="No estimable"`, `cost_eur=0`, `duration_weeks=1`), `total_cost_eur=0`, `total_duration_weeks=1`; `summary` conserva el prefijo `Out of scope:`. Así el resultado sigue siendo válido (suma 0 = 0). El filtro es una función pura.
4. **Guardrails (`app/services/guardrails.py`).** Orden: PII → prompt injection → moderación (lo más barato primero; la moderación es la única con red). Se evalúan `description` y `name`/`description` de `reference_projects`. Correo y teléfono por regex; IBAN por regex más comprobación mod-97 para evitar falsos positivos. Inyección por patrones en español e inglés sobre texto normalizado. Moderación con `omni-moderation-latest` de OpenAI: sin `OPENAI_API_KEY` se omite con un aviso; un fallo de red falla en abierto salvo `MODERATION_FAIL_OPEN=false`. `GuardrailViolation(reason, message)` se traduce en `main.py` a 400 con `{reason, message}`; el mensaje nunca contiene el valor detectado. Razones: `moderation`, `prompt_injection`, `pii_email`, `pii_phone`, `pii_iban`.
5. **Embeddings (`app/services/embeddings.py`).** `OpenAIEmbedder` con `AsyncOpenAI.embeddings.create` (`text-embedding-3-small`, 1536 dimensiones por defecto). Anthropic no ofrece embeddings, así que la caché semántica requiere `OPENAI_API_KEY`; sin ella queda desactivada con un aviso. Texto embebido: descripción más proyectos de referencia, para no devolver una respuesta calibrada con otras referencias.
6. **Caché semántica (`app/services/semantic_cache.py`).** `redisvl` `SemanticCache` con campos filtrables de tipo tag (`prompt_version`, `project_type`, `detail_level`, `output_format`) y filtro obligatorio en cada consulta. El nombre del índice incluye modelo y dimensiones de embedding para que no se mezclen vectores incompatibles. El umbral se expresa como similitud coseno (`SEMANTIC_CACHE_THRESHOLD`, 0,92) y se convierte a distancia (`1 − similitud`) para `redisvl`. `SEMANTIC_CACHE_TTL` por defecto 86400. Con `SEMANTIC_CACHE_MODE=log_only` se consulta y se registra el acierto potencial con su distancia, pero se devuelve miss; el almacenamiento sigue activo. Cualquier error de Redis o de embeddings falla en abierto con un aviso.
7. **Caché exacta.** Se reutiliza `EstimationCache` con clave `estimation:v2:` (versión de prompt y campos de la solicitud) y valor = resultado validado serializado. Va antes de la semántica y evita el embedding. Un acierto (exacto o semántico) devuelve `cached=true`; el resultado cacheado se revalida con las reglas de negocio y, si no pasa, cuenta como miss.
8. **Pipeline (`app/services/pipeline.py`).** `EstimationPipeline.run(request, prompt_version)` devuelve `PipelineOutcome(result, prompt_version, cached, uso y costes)`. Etapas: guardrails → exacta → semántica → render → generar/validar (≤ `VALIDATION_MAX_ATTEMPTS`, por defecto 3) → filtro de fuera de alcance → almacenar en ambas cachés. `get_pipeline` es la dependencia de FastAPI (`Depends`) y construye el servicio con `get_settings()`. Las pruebas la sustituyen con `app.dependency_overrides`.
9. **Prompt v3.** Plantillas nuevas con el esquema JSON explícito, la regla de suma, la regla de `Out of scope:` y respuesta solo JSON. `output_format` y `detail_level` modulan `summary` y las descripciones de fase. `v1` y `v2` se conservan; el pipeline añade el contrato JSON al prompt de sistema cuando la versión no es `v3`, de modo que cualquier versión produzca JSON. `DEFAULT_PROMPT_VERSION` pasa a `v3`.
10. **Streaming.** El stream estructurado ejecuta guardrails y validación de entrada antes de abrir la respuesta (400/422 reales), ejecuta el pipeline y emite `result`, `metadata` y `done`; un fallo emite `error` saneado sin `done`.
11. **Redis Stack.** `docker-compose.yml` usa `redis/redis-stack-server`, sin la política `allkeys-lru` (podría expulsar el índice) y con `REDIS_URL` compartido. Sin Redis, ambas cachés se desactivan.

## Risks / Trade-offs

- [Falsos positivos de PII o inyección bloquean descripciones legítimas] → heurísticas conservadoras, IBAN con mod-97 y mensaje que indica qué reformular.
- [Un umbral bajo devuelve estimaciones de proyectos distintos] → umbral alto por defecto, filtros por tag y modo `log_only` para calibrarlo sin riesgo.
- [El reintento de validación multiplica el coste] → máximo de intentos acotado y tokens/costes sumados en `metadata`.
- [Cambio incompatible de `/estimate`] → documentarlo en README, Postman y cliente.
- [El entorno de desarrollo actual no puede ejecutar Python por una política de control de aplicaciones de Windows] → la verificación se hace tras desbloquearlo o en CI; se registra en `verification.md`.

## Migration Plan

Actualizar consumidores a `result` y `cached`; levantar Redis Stack con `docker compose up`; añadir las variables nuevas a `.env` (todas tienen valor por defecto). Rollback: revertir la rama; las claves de caché usan prefijos nuevos y no colisionan.

## Open Questions

Ninguna bloqueante. Supuestos registrados: moderación y embeddings con OpenAI, tolerancia de suma 0,01 EUR, umbral de similitud 0,92.
