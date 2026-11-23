# Proposal

## Why

El diagnóstico de la Sesión 09 (`arquitectura-actual.md`) dejó cinco fallos en el RAG de `estimador-cag`: la transcripción
se embebe entera, no hay filtros ni umbral de relevancia y el flujo termina en una lista de chunks sin generar ninguna
estimación. El proyecto de referencia `estimator/` ya cierra ese ciclo (Sesión 09): reformulación → recuperación
filtrada → ensamblado → generación con citas, con endpoints protegidos. Este cambio porta **solo** lo que `estimator/` ya
implementa.

## What Changes

- Nuevo `POST /v1/retrieval/search`: recuperación semántica con umbral de distancia, filtros por metadatos (sector,
  año del proyecto, tipo de chunk) y *soft-fail* (`low_confidence=true`, `200`) cuando nada supera el umbral.
- Nuevo `POST /v1/estimate/from-transcript`: transcripción cruda → estimación fundamentada en jornadas-ingeniero
  (módulos → tareas), con fuentes citadas, supuestos, nivel de confianza (`high|medium|low|insufficient`),
  reintento correctivo ante ids de fuente inventados, regla de coherencia para `insufficient` e idempotencia por
  `idempotency_key` (Redis, con *fallback* en memoria).
- Nuevos endpoints por etapa `POST /v1/estimate/stages/{reformulate,retrieve,assemble,generate}`: sin estado, reutilizan
  las mismas funciones del orquestador.
- Endurecimiento de la API RAG: dos claves independientes (`X-API-Key`; `retrieval_api_key` y `estimate_api_key`)
  comparadas en tiempo constante, *rate limiting* por clave (120/min recuperación, 10/min estimación, 30/min etapas,
  `429` con `Retry-After`) y middleware `X-Request-ID` que correlaciona los logs por etapa.
- `POST /search` (Sesión 08) se mantiene sin cambios por compatibilidad (Chunking Lab, demos).

## Capabilities

### New Capabilities
- `estimator/rag-api-security`: autenticación por clave de API, *rate limiting* por clave e id de correlación por petición.
- `estimator/rag-retrieval`: recuperación filtrada con umbral y *soft-fail* (`/v1/retrieval/search`).
- `estimator/grounded-estimation`: estimación fundamentada desde transcripción, con citas, coherencia e idempotencia.
- `estimator/estimation-stages`: endpoints sin estado que exponen cada etapa del pipeline RAG.

### Modified Capabilities
- `estimator/layered-architecture`: se elimina el requisito «Hueco de la Sesión 8» (el retriever deja de ser un placeholder).

## Impact

- Código: `app/generation/rag/` (reformulador, retriever, ensamblador de contexto, *prompt builder*, orquestador,
  idempotencia, observabilidad, errores), `app/api/` (routers, seguridad, *rate limiting*, deps), `app/main.py`,
  `app/config.py`, `app/dependencies.py`.
- Dependencias: `slowapi`.
- Configuración nueva: `reformulation_model`, `generation_model`, `retrieval_top_k`, `retrieval_distance_threshold`,
  `max_context_tokens`, `idempotency_ttl`, `retrieval_api_key`, `estimate_api_key`.
- Datos: corpus de tareas históricas (`scripts/build_task_corpus.py`) para fundamentar tareas finas.
- Contratos existentes: sin cambios (aditivo). Clientes web (Go, React, Streamlit) fuera de alcance.
