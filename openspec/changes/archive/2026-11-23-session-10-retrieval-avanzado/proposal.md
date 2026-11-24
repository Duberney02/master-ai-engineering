# Proposal

## Why

Tras la Sesión 09 la recuperación sigue siendo solo vectorial, sobre una única colección y con la consulta tal cual.
`estimator/` ataca en la Sesión 10 los fallos que quedan del diagnóstico (consultas multi-tema, identificadores léxicos
diluidos por el embedding, la colección dominante inundando el top-k, precedentes obsoletos) y añade la estimación de
horas por tarea. Este cambio porta **solo** esas mejoras. Depende de `session-09-rag-estimacion-fundamentada`.

## What Changes

- Búsqueda **híbrida**: rama léxica (columna `tsvector` generada + índice GIN) fusionada con la vectorial mediante RRF.
- **Reranking** con cross-encoder multilingüe (recall amplio → top-N), opcional.
- `POST /v1/retrieval/search` acepta `search_mode` (`vector|hybrid`) y `rerank` opcionales (aditivo).
- **Multi-índice**: tres colecciones (presupuestos, transcripciones, documentación técnica) con esquema de metadatos propio.
- Nuevo `POST /v1/retrieval/advanced-search`: *routing* en cascada (explícito → reglas → clasificador LLM → todas),
  transformación de consulta (directa / expansión / descomposición, máx. 4 subconsultas), filtros duros
  (tecnologías, sectores, fecha mínima, versión del documento), fusión por técnica (RRF o *round-robin*), *decay*
  temporal tras el *rerank* y diagnóstico (nivel y motivo del *routing*, técnica, subconsultas, cardinalidad por colección).
- Nuevo `GET/PUT /api/v1/config/retrieval`: *toggles* de recuperación en tiempo de ejecución (persistidos en Redis).
- Nuevo `POST /v1/estimate/stages/structure` (estructura módulos → tareas sin horas) y `POST /v1/estimate/tasks/hours`
  (horas por tarea por consenso ponderado de vecinos históricos, con fiabilidad y `has_match=false` sin vecino).
- Evaluación de recuperación: *golden set* anotado y script de precision@k y latencia por configuración nombrada.

## Capabilities

### New Capabilities
- `estimator/hybrid-retrieval`: modos vector/híbrido con RRF y *reranking* recall-then-rerank.
- `estimator/multi-index-retrieval`: colecciones separadas y `/v1/retrieval/advanced-search` con *routing*,
  transformación de consulta, filtros duros, fusión y *decay* temporal.
- `estimator/runtime-retrieval-config`: API de lectura/escritura de los *toggles* de recuperación.
- `estimator/task-hours-estimation`: estructura sin horas y horas por tarea desde el corpus histórico.
- `estimator/retrieval-evaluation`: *golden set* de recuperación y medición precision@k por configuración.

### Modified Capabilities
- `estimator/vector-persistence`: se añaden la columna léxica y las tablas de transcripciones y documentación técnica.

## Impact

- Código: `app/generation/rag/retrieval/` (pipeline, fusión, *reranker*, colecciones, *router*, transformación de
  consulta, *decay*), `generation/rag/task_hours.py`, `foundation/llm/runtime_config.py`, `app/api/`.
- Migraciones Alembic nuevas (FTS y multi-índice). Datos: corpus de transcripciones y documentación técnica.
- Dependencias: `sentence-transformers` (arrastra `torch`; imagen mayor).
- Configuración nueva: modo de búsqueda, *reranker* (modelo, `recall_top_k`, `rerank_top_n`), `rrf_k`, *routing*,
  transformación de consulta, *decay* (vida media), modelos de *router* y transformación, parámetros de horas por tarea.
- Contratos existentes: aditivos.
