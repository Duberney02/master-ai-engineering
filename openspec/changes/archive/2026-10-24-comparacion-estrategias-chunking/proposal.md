# Proposal

## Why

El pipeline de embeddings solo tiene un chunking (estructural: un chunk por componente) y no hay forma de saber si es el adecuado. La referencia (`ai-engineering`, `session_07_live`) compara ocho estrategias con estadísticas de corpus, top-k por similitud coseno y coste, expuestas por HTTP y por CLI. Sin ese framework, la elección del chunking de la Sesión 8 sería una apuesta; con él se decide con números.

## What Changes

- **Interfaz común `Chunker`** (async) con conteo de tokens homogéneo (`cl100k_base`), coste y llamadas extra reportados (`last_extra_cost_usd`, `last_extra_api_calls`) y un evento de log uniforme `chunking_done`.
- **Siete estrategias además de la estructural**: `fixed_size`, `recursive`, `sentence_window` (frases con NLTK Punkt), `semantic` (cortes por salto de embedding), `propositional` (LLM), `contextual_retrieval` (Anthropic con prompt caching) y `hierarchical` (padre-hijo). Las dos con LLM usan modelos configurables (`propositional_chunker_model`, `contextual_chunker_model`).
- **Embedder asíncrono con dimensión configurable** (`embedding_dimensions`, truncado Matryoshka); `embed_texts` y `embed_many` por lotes con reintentos.
- **Framework de comparación** (`generation/rag/analysis/`): estadísticas por estrategia (chunks; mín/p50/p95/máx de tokens; huérfanos y obesos; coste; llamadas extra; tiempo), top-k por coseno y chunking memoizado.
- **`POST /embeddings/compare`** (aditivo, sin persistencia): presupuestos, consultas, estrategias y `top_k`; errores diferenciados (400 estrategia desconocida, 503 clave ausente, 500 fallo de cómputo).
- **Corpus y consultas**: `data/test_queries.json` y `data/budgets_stress_cases.json` (tres casos límite) junto a los 15 presupuestos existentes.
- **CLI `scripts/compare_chunkers.py`**: filtros por estrategia y consulta, estadísticas, top-k y coste, informe Markdown, comparación de dimensiones y resolución de padres.
- `nltk` como dependencia; los datos de Punkt se descargan al construir la imagen.

**No incluido**: vector store y retriever (Sesión 8), métricas formales de recuperación (Sesión 11), persistencia de resultados, cambios en `POST /embeddings/ingest` (misma ruta y misma forma JSON).

## Capabilities

### New Capabilities
- `estimator/chunking-strategies`: interfaz común y las ocho estrategias.
- `estimator/chunking-comparison`: estadísticas, top-k, memoización y endpoint de comparación.
- `estimator/chunking-compare-cli`: CLI de comparación e informe.

### Modified Capabilities
- `estimator/embedding-ingest`: el embedder es asíncrono y admite dimensión configurable.

## Impact

- Código: `app/generation/rag/{chunking,embedding,analysis}`, `app/api/embeddings.py`, `app/dependencies.py`, `app/config.py`, `app/logging_config.py` (campos permitidos), `scripts/compare.py` y `scripts/compare_chunkers.py`, `Dockerfile` (datos de Punkt), `pyproject.toml`/`uv.lock` (`nltk`).
- Datos: `data/test_queries.json`, `data/budgets_stress_cases.json`.
- Las estrategias de pago nunca se ejecutan por defecto. Las pruebas usan embedder y clientes de LLM falsos; no requieren claves reales.
