-- 05 · Ciclo de mantenimiento: ANALYZE → VACUUM → REINDEX CONCURRENTLY.
--
--   docker compose exec -T postgres psql -U estimator -d estimator < estimador-cag/scripts/sql_s08/05_maintenance_cycle.sql
--
-- IMPORTANTE: VACUUM y REINDEX ... CONCURRENTLY no pueden ejecutarse dentro de una transacción. psql con -f o stdin
-- ejecuta cada sentencia en modo autocommit, así que NO envuelvas este script en BEGIN/COMMIT.

\timing on

-- 1) ANALYZE: estadísticas frescas para el planner (necesario tras cargas masivas, p. ej. los chunks sintéticos).
ANALYZE chunks;

-- 2) VACUUM: libera filas muertas y limpia las entradas del grafo HNSW. Tras muchos DELETE/UPDATE mejora recall y tamaño.
VACUUM (VERBOSE, ANALYZE) chunks;

-- 3) REINDEX CONCURRENTLY: reconstruye el índice sin bloquear lecturas/escrituras (necesita ~2× espacio temporal).
--    Úsalo si el grafo se degradó (muchos borrados), tras cambiar m/ef_construction o para reparar un índice INVALID.
REINDEX INDEX CONCURRENTLY chunks_embedding_halfvec_idx;

-- 4) Comprobación: ambos índices válidos y con su tamaño.
SELECT c.relname AS indice, i.indisvalid AS valido, pg_size_pretty(pg_relation_size(c.oid)) AS tamano
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
WHERE i.indrelid = 'chunks'::regclass AND c.relname LIKE 'chunks_embedding%';
