## Contexto

`chunks.embedding` es `vector(1536)` (full precision) sin índice vectorial. pgvector limita HNSW sobre `vector` a 2000
dimensiones y un índice `halfvec` ocupa ≈50 % del de `vector`, con recall prácticamente igual.

## Decisiones

1. **Columna en full precision, índice en halfvec.** Se indexa la *expresión* `embedding::halfvec(1536)`: no hay que
   migrar datos ni cambiar el contrato de ingesta, y el almacenamiento de la tabla no cambia.
2. **Se mantienen dos índices.** `chunks_embedding_halfvec_idx` sirve a producción; `chunks_embedding_idx` (`vector`)
   se conserva para comparar en el benchmark. Coste: aproximadamente el doble de espacio de índice y más trabajo en
   cada escritura; el planner solo usa el halfvec porque `/search` lo consulta por expresión. Si el coste molesta, se
   elimina con `DROP INDEX CONCURRENTLY chunks_embedding_idx` sin afectar a `/search`.
3. **Alineación expresión/operador.** El `ORDER BY` debe ser `CAST(embedding AS HALFVEC(1536)) <=> :q` con
   `halfvec_cosine_ops`; si no, Postgres ignora el índice sin avisar. La dimensión sale de una constante compartida
   (`EMBEDDING_DIMENSIONS`) usada por modelo, migración y consulta.
4. **`CREATE INDEX CONCURRENTLY`** dentro de `autocommit_block()` para no bloquear escrituras; `downgrade` simétrico con
   `DROP INDEX CONCURRENTLY IF EXISTS`. Los índices se declaran solo en la migración (expresión funcional + operator
   class): `alembic check` debe seguir sin diferencias; si no, se registra `HALFVEC` o se excluyen con
   `include_object` en `env.py`.
5. **`hnsw.ef_search` por transacción.** `SET LOCAL hnsw.ef_search = <n>` en la transacción de la búsqueda (el valor
   es un `int` validado 1–1000, interpolado; `SET` no admite parámetros enlazados). Setting `HNSW_EF_SEARCH`; su valor
   por defecto se fija tras el barrido y queda documentado en `docs/session-08-ef-search.md`.
6. **Tuning de Postgres** conservador (shared_buffers 512MB, effective_cache_size 1536MB, work_mem 64MB,
   maintenance_work_mem 512MB, 2 workers de mantenimiento, `shm_size: 1gb`); en producción escalan con la RAM
   (shared_buffers ≈25 %, effective_cache_size ≈75 %).
7. **Scripts** hablan con la BD por la sesión async del proyecto (`app.foundation.persistence.database`), sin motores
   paralelos, y con el embedder existente. La utilería común vive en `scripts/s08_common.py`, sin `rich`/`tabulate`.
8. **Reversión en vivo (`99_revert_live_session.sql`)** deshace lo manual de la demo; los índices de la migración `0003`
   solo se retiran con `alembic downgrade 0002`, y el script lo documenta.

## Riesgos

- Un `ORDER BY` desalineado cae a *seq scan* sin error → test de integración con `EXPLAIN`.
- `CREATE INDEX CONCURRENTLY` fallido deja un índice `INVALID`; `downgrade`/`REINDEX` lo limpian.
