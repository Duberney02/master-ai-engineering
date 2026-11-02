-- 99 · Reversión idempotente de lo que se hizo "en vivo" en la Sesión 08.
--
--   docker compose exec -T postgres psql -U estimator -d estimator -v keep_synthetic=0 \
--       < estimador-cag/scripts/sql_s08/99_revert_live_session.sql
--
-- Variables de psql (-v):
--   keep_synthetic=N   chunks sintéticos que se conservan (por defecto 0 = todos fuera, y también su documento).
--   drop_indexes=1     además elimina los dos índices HNSW (por defecto NO se tocan, ver abajo).
--
-- QUÉ REVIERTE:
--   · Los chunks sintéticos de `insert_synthetic_chunks_s08.py` por encima de `keep_synthetic`.
--   · El override `ALTER DATABASE estimator SET hnsw.ef_search` (si se aplicó en la demo).
--   · Las estadísticas (`pg_stat_reset()` + `ANALYZE`), para repetir las mediciones desde cero.
--   · Con `drop_indexes=1`, los índices creados a mano en 01/03 (`DROP INDEX CONCURRENTLY IF EXISTS`).
--
-- QUÉ NO REVIERTE: los índices HNSW son también los de la migración `0003`. Por defecto se CONSERVAN para que la base
-- siga coherente con `alembic_version`. Si los eliminas con drop_indexes=1, restáuralos con
-- `docker compose run --rm estimador-cag alembic downgrade 0002 && ... alembic upgrade head`; para deshacer también la
-- migración usa `alembic downgrade 0002`.

\if :{?keep_synthetic}
\else
\set keep_synthetic 0
\endif
\if :{?drop_indexes}
\else
\set drop_indexes 0
\endif

-- 1) Chunks sintéticos extra: se conservan los `keep_synthetic` primeros (por id).
DELETE FROM chunks
WHERE id IN (
    SELECT id FROM chunks WHERE chunk_type = 'synthetic' ORDER BY id OFFSET :keep_synthetic
);

-- 2) Si no queda ninguno, también el documento sintético (el borrado en cascada eliminaría sus chunks restantes).
DELETE FROM documents d
WHERE d.document_type = 'synthetic_test'
  AND NOT EXISTS (SELECT 1 FROM chunks c WHERE c.document_id = d.id);

-- 3) Override de ef_search a nivel de base de datos (RESET es idempotente: no falla si no existía).
ALTER DATABASE estimator RESET hnsw.ef_search;

-- 4) Índices manuales (solo con -v drop_indexes=1). CONCURRENTLY no admite transacción: psql ejecuta cada sentencia sola.
SELECT :drop_indexes::int = 1 AS borrar_indices \gset
\if :borrar_indices
DROP INDEX CONCURRENTLY IF EXISTS chunks_embedding_halfvec_idx;
DROP INDEX CONCURRENTLY IF EXISTS chunks_embedding_idx;
\endif

-- 5) Estadísticas limpias y planner al día.
SELECT pg_stat_reset();
ANALYZE chunks;

SELECT (SELECT count(*) FROM chunks) AS chunks,
       (SELECT count(*) FROM chunks WHERE chunk_type = 'synthetic') AS sinteticos,
       (SELECT count(*) FROM pg_indexes WHERE tablename = 'chunks' AND indexname LIKE 'chunks_embedding%') AS indices_hnsw;
