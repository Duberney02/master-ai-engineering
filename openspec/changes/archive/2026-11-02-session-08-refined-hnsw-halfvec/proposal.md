## Why

La Sesión 8 dejó `/search` como *sequential scan* (línea base). Con el corpus creciendo, la latencia crece lineal con
el número de chunks. Esta iteración añade índices vectoriales HNSW versionados con Alembic, alinea la consulta con el
índice, ajusta Postgres para construirlos y entrega las herramientas (scripts y SQL) para medir, comparar y operar.

## What Changes

- `postgres` (Compose raíz): `shm_size: 1gb` y flags de tuning conservadores para builds HNSW (pg17 se mantiene).
- Migración Alembic `0003`: `chunks_embedding_halfvec_idx` (HNSW sobre `embedding::halfvec(1536)`, `halfvec_cosine_ops`,
  m=16, ef_construction=128) y `chunks_embedding_idx` (HNSW `vector_cosine_ops`, para el benchmark), creados con
  `CREATE INDEX CONCURRENTLY`.
- `DocumentStore.search` ordena y mide `distance` con `CAST(embedding AS HALFVEC(1536)) <=> :q` (la expresión exacta del
  índice) y aplica `SET LOCAL hnsw.ef_search` con el nuevo setting `HNSW_EF_SEARCH`.
- `scripts/s08_common.py`, cinco scripts `*_s08.py` y `scripts/sql_s08/` (01–05, 99).
- Tests unitarios e integración; documentación (README, ARCHITECTURE, `docs/session-08-ef-search.md`).
- El contrato HTTP de `/search` y de `/embeddings/ingest` **no cambia**.

### Fuera de alcance

Filtros por metadata en `/search`, búsqueda híbrida, reformulación de queries, threshold y retriever RAG.

## Capabilities

### Modified Capabilities
- `vector-persistence`: tuning de Postgres e índices HNSW gestionados por migración.
- `semantic-search`: búsqueda alineada con el índice halfvec, `ef_search` configurable y scripts de operación.

## Impact

- Código: `app/config.py`, `app/foundation/persistence/models.py`, `app/generation/rag/store/documents.py`,
  `alembic/env.py`, `alembic/versions/0003_*`, `scripts/`, `tests/`.
- Infra: `docker-compose.yml`. Docs: README, ARCHITECTURE, `docs/session-08-ef-search.md`.
