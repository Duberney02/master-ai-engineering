-- 04 · Consultas de monitorización de índices vectoriales.
--
--   docker compose exec -T postgres psql -U estimator -d estimator < estimador-cag/scripts/sql_s08/04_monitoring_queries.sql

-- (1) Consulta canónica: tamaño y uso de cada índice. `idx_scan = 0` en un índice vectorial ⇒ operador o expresión
--     desalineados con el ORDER BY (ver 02_test_antipatron.sql). `last_idx_scan` es el último uso (PostgreSQL ≥ 16).
SELECT schemaname, relname AS tabla, indexrelname AS indice,
       idx_scan, last_idx_scan,
       idx_tup_read, idx_tup_fetch,
       pg_size_pretty(pg_relation_size(indexrelid)) AS tamano
FROM pg_stat_user_indexes
WHERE relname = 'chunks'
ORDER BY pg_relation_size(indexrelid) DESC;

-- (2) Salud de la tabla: filas vivas/muertas y cuándo se analizó/vació por última vez. Muchas filas muertas o un
--     `last_analyze` antiguo degradan al planner y al recall (el grafo HNSW arrastra las filas borradas hasta un VACUUM).
SELECT relname, n_live_tup, n_dead_tup,
       last_analyze, last_autoanalyze, last_vacuum, last_autovacuum
FROM pg_stat_user_tables
WHERE relname IN ('chunks', 'documents');

-- (3) Operator class y parámetros de cada índice vectorial: debe coincidir con el operador del ORDER BY.
SELECT c.relname AS indice,
       am.amname AS metodo,
       oc.opcname AS operator_class,
       i.indisvalid AS valido,
       pg_get_expr(i.indexprs, i.indrelid) AS expresion,
       c.reloptions AS opciones
FROM pg_index i
JOIN pg_class c ON c.oid = i.indexrelid
JOIN pg_am am ON am.oid = c.relam
JOIN pg_opclass oc ON oc.oid = i.indclass[0]
WHERE i.indrelid = 'chunks'::regclass AND am.amname = 'hnsw';

-- (4) Valor efectivo de ef_search y de los parámetros de tuning.
SHOW hnsw.ef_search;
SELECT name, setting, unit FROM pg_settings
WHERE name IN ('shared_buffers', 'effective_cache_size', 'work_mem', 'maintenance_work_mem', 'max_parallel_maintenance_workers');
