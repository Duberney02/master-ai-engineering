## 1. Infraestructura
- [x] 1.1 `docker-compose.yml`: `shm_size` y flags de tuning en `postgres`; verificar `SHOW shared_buffers`

## 2. Migración e índices
- [x] 2.1 Setting `hnsw_ef_search` en `Settings`
- [x] 2.2 Migración `0003` con ambos índices HNSW (`CONCURRENTLY`) y downgrade simétrico
- [x] 2.3 `alembic upgrade head`, `alembic check`, `downgrade 0002` → `upgrade head` en Docker

## 3. Búsqueda
- [x] 3.1 `DocumentStore.search` con halfvec + `SET LOCAL hnsw.ef_search`
- [x] 3.2 Tests unitarios (SQL compilado, ef_search, validación del setting)

## 4. Scripts y SQL
- [x] 4.1 `scripts/s08_common.py` (+ tests de `format_table`, recall, `recommendation_labels`)
- [x] 4.2 `measure_baseline_s08.py`, `sweep_ef_search_s08.py`, `compare_indexes_s08.py`
- [x] 4.3 `report_index_sizes_s08.py`, `insert_synthetic_chunks_s08.py`
- [x] 4.4 `scripts/sql_s08/01..05` y `99`

## 5. Tests de integración
- [x] 5.1 Índices HNSW con operator class correcta y `EXPLAIN` con `Index Scan using chunks_embedding_halfvec_idx`
- [x] 5.2 `test_layer_dependencies.py` y `test_architecture.py` en verde

## 6. Medición y documentación
- [x] 6.1 Medición real: baseline antes/después, barrido, comparación, tamaños; fijar `HNSW_EF_SEARCH`
- [x] 6.2 Regenerar `output_examples.txt` y comprobar equivalencia
- [x] 6.3 README (sección Sesión 08 en vivo + justificaciones), ARCHITECTURE, `docs/session-08-ef-search.md`

## 7. Cierre
- [x] 7.1 Suite completa + lint en Docker; `openspec validate --all --strict`
- [x] 7.2 Archivar el change y sincronizar specs; commits atómicos, push y PR a `master`
