-- 03 · Índice HNSW halfvec (el que usa /search): media precisión solo en el índice.
--
--   docker compose exec -T postgres psql -U estimator -d estimator < estimador-cag/scripts/sql_s08/03_create_halfvec.sql
--
-- La columna `embedding` sigue siendo vector(1536) (full precision); el índice guarda la EXPRESIÓN
-- `embedding::halfvec(1536)` en float16: ≈50 % de tamaño con un recall casi idéntico. Como el índice es sobre una
-- expresión, el ORDER BY de la consulta debe repetirla EXACTAMENTE (mismo cast, mismo operador `<=>`).
-- La migración 0003 ya lo crea; con IF NOT EXISTS el script es repetible.

\timing on

-- Build paralelo (necesita shm_size y maintenance_work_mem del compose).
SET max_parallel_maintenance_workers = 2;

CREATE INDEX CONCURRENTLY IF NOT EXISTS chunks_embedding_halfvec_idx
    ON chunks USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 128);

-- Comparación de tamaños: halfvec / vector ≈ 50 %.
SELECT i.indexname,
       pg_relation_size(i.indexname::regclass) AS bytes,
       pg_size_pretty(pg_relation_size(i.indexname::regclass)) AS tamano
FROM pg_indexes i
WHERE i.indexname IN ('chunks_embedding_idx', 'chunks_embedding_halfvec_idx')
ORDER BY bytes DESC;

SELECT round(100.0 * pg_relation_size('chunks_embedding_halfvec_idx') / pg_relation_size('chunks_embedding_idx'), 1)
       AS pct_halfvec_sobre_vector;

-- EXPLAIN con la expresión casteada: debe aparecer "Index Scan using chunks_embedding_halfvec_idx".
BEGIN;
SET LOCAL enable_seqscan = off;  -- con pocas filas el planner preferiría el seq scan
EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF)
SELECT id FROM chunks
ORDER BY (embedding::halfvec(1536)) <=> (SELECT embedding::halfvec(1536) FROM chunks WHERE embedding IS NOT NULL ORDER BY id LIMIT 1)
LIMIT 5;
ROLLBACK;

-- Opcional (solo en la demo): sube ef_search para toda la base. Se revierte con 99_revert_live_session.sql.
-- ALTER DATABASE estimator SET hnsw.ef_search = 80;
