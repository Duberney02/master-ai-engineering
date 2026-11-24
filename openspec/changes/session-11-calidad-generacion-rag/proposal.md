# Proposal

## Why

Una cita a un chunk real no garantiza que la cifra esté respaldada, un promedio de vecinos que se contradicen oculta
la incertidumbre y el corpus no puede crecer sin volver a ingestar. `estimator/` resuelve esto en la Sesión 11 con
citas verificables por línea, un *gate* semántico de alucinaciones, aumentación del contexto, síntesis de rangos,
expansión incremental del corpus con HNSW en todas las colecciones y una evaluación RAGAS con *gate* de regresión.
Este cambio porta **solo** esas mejoras. Depende de `session-09-rag-estimacion-fundamentada` y `session-10-retrieval-avanzado`.

## What Changes

- **Citas por línea**: cada tarea lleva `grounded` y `sources` (`chunk_id`, `document_id`, `evidence` literal); una línea
  no fundamentada no lleva fuentes ni horas. Informe de citas por línea (`grounded`/`dangling`/`insufficient`) integrado
  en el orquestador y en la etapa `generate`.
- **Gate de alucinaciones**: ancla numérica determinista (horas históricas de los chunks citados) + juez LLM estricto en
  una sola llamada; una línea que sobreestima su evidencia más allá de la tolerancia o que el juez no respalda queda
  `degraded` y rebaja la confianza a `low`. Nueva etapa `POST /v1/estimate/stages/verify`.
- **Aumentación del contexto**: compresión extractiva (líneas con cifras o ids) y reordenación de bordes contra
  *lost-in-the-middle*, conmutables.
- **Síntesis de rangos**: cuando la dispersión de los vecinos supera un umbral, la tarea añade un rango de horas con un
  motivo, sin cambiar la cifra puntual.
- **Expansión incremental del corpus**: `POST /embeddings/index/runs` (202 + `job_id`), `GET /embeddings/index/jobs/{id}`
  y `GET /embeddings/index/stats`; HNSW halfvec en las tablas de transcripciones y documentación técnica.
- **Evaluación de generación**: *golden set* con `ground_truth`, línea base RAGAS (faithfulness, answer relevancy,
  context precision, context recall), modo *gate* (sale con error si alguna métrica cae más de 0,05 o aparece una cita
  colgante) y modo monitor sin referencia.

## Capabilities

### New Capabilities
- `estimator/citation-verification`: contrato de citas por línea e informe de verificación.
- `estimator/hallucination-gate`: ancla numérica + juez y etapa `verify`.
- `estimator/context-augmentation`: compresión y reordenación del contexto recuperado.
- `estimator/hours-range-synthesis`: rango de horas ante vecinos contradictorios.
- `estimator/corpus-expansion`: ampliación asíncrona del corpus y estadísticas del índice.
- `estimator/generation-evaluation`: RAGAS con línea base, *gate* de regresión y monitor.

### Modified Capabilities
- `estimator/vector-persistence`: índices HNSW halfvec en las tablas de transcripciones y documentación técnica.

## Impact

- Código: `generation/rag/quality/` (aumentación, alucinaciones, síntesis), `validation.py`, servicio de expansión,
  `prompt_builder`, routers de etapas e índice, `task_hours`.
- Migración Alembic nueva (HNSW multi-índice). Jobs: reutiliza la tabla de jobs de la ingesta.
- Dependencias de desarrollo: `ragas`, `datasets` (solo scripts; las pruebas no los usan con claves reales).
- Configuración nueva: *gate* (habilitado, modelo juez, tolerancia), aumentación (habilitada, compresión, reordenación,
  modelo), síntesis (habilitada, umbral de contradicción).
- Contrato de la estimación: aditivo (campos nuevos por línea; `sources` por línea pasa de ids a objetos de cita).
