-- 02 · Antipatrón: operador desalineado con el operator class del índice.
--
--   docker compose exec -T postgres psql -U estimator -d estimator < estimador-cag/scripts/sql_s08/02_test_antipatron.sql
--
-- El índice `chunks_embedding_idx` es `vector_cosine_ops`: solo sirve al operador de distancia coseno `<=>`.
-- Con `<->` (distancia L2) Postgres no puede usarlo y cae a Seq Scan SIN ERROR NI AVISO: la consulta "funciona", solo
-- que lenta. Se usa el embedding de un chunk real como vector de consulta.

\timing on

-- Estadísticas de partida del índice (idx_scan = veces que el planner lo ha usado).
SELECT indexrelname, idx_scan FROM pg_stat_user_indexes WHERE indexrelname = 'chunks_embedding_idx';

BEGIN;
-- Con pocas filas el planner prefiere el seq scan aunque haya índice; esto fuerza a usarlo si PUEDE usarlo.
SET LOCAL enable_seqscan = off;

-- (a) Correcto: `<=>` coincide con vector_cosine_ops → debe aparecer "Index Scan using chunks_embedding_idx".
EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF)
SELECT id FROM chunks
ORDER BY embedding <=> (SELECT embedding FROM chunks WHERE embedding IS NOT NULL ORDER BY id LIMIT 1)
LIMIT 5;

-- (b) Antipatrón: `<->` (L2) no coincide → "Seq Scan" (aunque enable_seqscan = off, es la única opción).
EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF)
SELECT id FROM chunks
ORDER BY embedding <-> (SELECT embedding FROM chunks WHERE embedding IS NOT NULL ORDER BY id LIMIT 1)
LIMIT 5;
ROLLBACK;

-- Lo que lo delata en producción: el índice existe pero `idx_scan` no sube. Tras (a) debe haber subido; (b) no suma.
SELECT pg_stat_force_next_flush();
SELECT indexrelname, idx_scan FROM pg_stat_user_indexes WHERE indexrelname = 'chunks_embedding_idx';
