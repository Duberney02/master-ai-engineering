# Design

## Context

Parte del estado que deja `session-09-rag-estimacion-fundamentada` (recuperación filtrada sobre `chunks`). En
`estimator/` la Sesión 10 se implementó con las migraciones `0003_session10_fts`, `0004_session10_multi_index` (que
**renombra** `chunks` → `budget_chunks`) y los módulos `generation/rag/retrieval/*`. Aquí se porta el comportamiento
respetando los contratos de `estimador-cag` (`POST /search` y su índice `chunks_embedding_halfvec_idx`).

## Goals / Non-Goals

**Goals:**
- Recuperación híbrida, *reranking*, multi-índice y búsqueda avanzada con diagnóstico, como en `estimator/`.
- Horas por tarea por consenso de vecinos y evaluación precision@k.

**Non-Goals:**
- Síntesis de rangos ante vecinos contradictorios y HNSW en las nuevas tablas (cambio de la Sesión 11).
- Cambios en los clientes web (pestaña de ajustes, asistente por etapas).

## Decisions

1. **No renombrar `chunks`.** `estimator/` renombra a `budget_chunks`; aquí `chunks` sigue siendo la colección
   `budget` para no romper `/search`, su spec ni el índice HNSW de la migración `0003_hnsw_indexes`. Las nuevas
   migraciones son `0004` (FTS) y `0005` (multi-índice) y se omiten fuera de PostgreSQL, como las existentes.
2. **Registro de colecciones único.** Un registro en `generation/rag/retrieval/` conoce por colección el modelo ORM,
   el `chunk_type`, la clave del id trazable, la fecha para el *decay* y los patrones de reglas del *router*; el resto
   del pipeline es agnóstico. Mismo diseño que `estimator/`.
3. **Fusión.** RRF (`rrf_k=60`) para híbrido y expansión; *round-robin* para descomposición (cobertura por tema).
4. **Reranker.** `sentence-transformers` con `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, carga diferida y
   protegida por *lock*, ejecutado con `asyncio.to_thread` para no bloquear el event loop. En pruebas se inyecta un
   *reranker* falso desde `app/dependencies.py`; ningún test descarga pesos.
5. **Clasificador y transformación con la generación estructurada propia** (`generate_structured`), modelos
   `router_model` y `query_transform_model` resolubles en runtime; ante error degradan a `fallback`/`direct`.
6. **Runtime de recuperación.** Se extiende `foundation/llm/runtime_config.py` con un hash Redis separado para los
   *toggles* de recuperación, con la misma semántica `effective/default/overridden` y el mismo mapeo a `503`.
7. **Horas por tarea** como función pura de consenso (peso = 1/max(distancia, ε)) más fiabilidad = cercanía × acuerdo
   (dispersión relativa); reutiliza la recuperación filtrada por `chunk_type="historical_task"`.
8. **Corpus multi-índice.** Se portan `data/transcripts_sample.json`, `data/technical_docs_sample.json` y
   `scripts/build_multi_index_corpus.py` (idempotente por `source_path`).

## Risks / Trade-offs

- [`torch` agranda mucho la imagen y el tiempo de build] → se instala en la imagen, pero el modelo solo se descarga al
  primer *rerank*; con `reranker_enabled=false` no se carga nunca.
- [Configuración de texto `english` vs corpus en español] → `estimator/` usa `english` porque el corpus de ejemplo está
  en inglés; se replica y se documenta que cambiarla toca la migración y la consulta.
- [Sin HNSW en las tablas nuevas, scan secuencial] → aceptable a escala de curso; lo resuelve la Sesión 11.

## Migration Plan

`alembic upgrade head` aplica `0004` y `0005`; ambas reversibles. *Rollback*: `alembic downgrade 0003_hnsw_indexes`.
