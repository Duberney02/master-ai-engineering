-- 01 · Crear el índice HNSW sobre la columna `vector` (vector_cosine_ops).
--
--   docker compose exec -T postgres psql -U estimator -d estimator < estimador-cag/scripts/sql_s08/01_create_hnsw.sql
--
-- NOTA: la migración 0003 ya crea este índice (`chunks_embedding_idx`). Con `IF NOT EXISTS` el script es seguro de
-- repetir; para ver el build en vivo desde cero, bórralo antes: `DROP INDEX CONCURRENTLY chunks_embedding_idx;`
-- (o `alembic downgrade 0002`, que quita los dos índices HNSW).

\timing on

-- 1) Estado previo: índices actuales de `chunks` con su tamaño.
SELECT indexname, pg_size_pretty(pg_relation_size(indexname::regclass)) AS tamano
FROM pg_indexes
WHERE tablename = 'chunks'
ORDER BY indexname;

SELECT count(*) AS filas, pg_size_pretty(pg_table_size('chunks')) AS tabla FROM chunks;

-- 2) Parámetros del build: ya vienen del `command:` de docker-compose (maintenance_work_mem, workers paralelos).
SHOW maintenance_work_mem;
SHOW max_parallel_maintenance_workers;

-- 3) Creación. `m` = vecinos por nodo; `ef_construction` = candidatos al construir el grafo (más = mejor recall, build más lento).
--    CONCURRENTLY no bloquea las escrituras y no puede ir dentro de una transacción (psql ejecuta cada sentencia sola).
CREATE INDEX CONCURRENTLY IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 128);

-- 4) Tamaños tras el build: el índice HNSW sobre `vector` suele pesar tanto o más que la propia tabla.
SELECT indexname, pg_size_pretty(pg_relation_size(indexname::regclass)) AS tamano
FROM pg_indexes
WHERE tablename = 'chunks'
ORDER BY pg_relation_size(indexname::regclass) DESC;
