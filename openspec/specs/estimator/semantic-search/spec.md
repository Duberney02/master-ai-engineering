# estimator/semantic-search Specification

## Purpose
Búsqueda semántica sobre los presupuestos persistidos: `POST /search` por distancia coseno (sequential scan) y consultas de ejemplo.

## Requirements

### Requirement: POST /search
El servicio SHALL exponer `POST /search` con `{query, k}` (`query` no vacío, `k` entero entre 1 y 50, por defecto 5). SHALL embeber la consulta con el mismo modelo que la ingesta y resolver en SQL los `k` chunks más cercanos ordenando por `CAST(Chunk.embedding AS HALFVEC(1536)).cosine_distance(vector)` (operador `<=>`) etiquetada `distance`, con `LIMIT k`: la expresión SHALL coincidir exactamente con la del índice `chunks_embedding_halfvec_idx` para que Postgres lo use. La búsqueda SHALL ejecutar `SET LOCAL hnsw.ef_search` con el valor del setting `HNSW_EF_SEARCH` dentro de su transacción. La respuesta `200` SHALL contener `query`, `k`, `search_time_ms` y `results`, cada uno con `chunk_id`, `document_id`, `chunk_type`, `content`, `distance` y `metadata`, de menor a mayor distancia. SHALL responder `422` ante entrada inválida, `503` si no hay base de datos configurada y `500` con mensaje genérico ante errores del proveedor. La búsqueda SHALL NOT usar filtros por metadata ni búsqueda híbrida. El contrato HTTP SHALL NOT cambiar.

#### Scenario: Top-k ordenado
- **WHEN** hay 6 chunks ingestados y se busca con `k=3`
- **THEN** la respuesta tiene 3 resultados con `distance` no decreciente y el primero es el más parecido a la consulta.

#### Scenario: k fuera de rango
- **WHEN** `k` vale 0 o 51
- **THEN** la respuesta es `422`.

#### Scenario: Base vacía
- **WHEN** no hay chunks
- **THEN** `results` es una lista vacía.

#### Scenario: Fallo del proveedor
- **WHEN** el embedder lanza una excepción
- **THEN** la respuesta es `500` con un mensaje genérico sin el texto del error original.

#### Scenario: Expresión halfvec
- **WHEN** se compila el statement de búsqueda
- **THEN** contiene `CAST(chunks.embedding AS HALFVEC(1536)) <=>`.

#### Scenario: Uso del índice
- **WHEN** se ejecuta `EXPLAIN` de la consulta de `/search` con el índice creado
- **THEN** el plan muestra `Index Scan using chunks_embedding_halfvec_idx`.

#### Scenario: ef_search configurable
- **WHEN** `HNSW_EF_SEARCH` vale 80
- **THEN** la búsqueda ejecuta `SET LOCAL hnsw.ef_search` con 80, y un valor fuera de 1–1000 se rechaza al cargar los settings.

### Requirement: Script de consultas de ejemplo
`scripts/query_examples.py` SHALL llamar a `/search` con cinco consultas (componente conocido, reformulación semántica, dominio distinto, ambigua y muy específica) e imprimir para cada una el top-5 con `chunk_id`, `distance` (4 decimales), `chunk_type` y los primeros ~120 caracteres de `content`. SHALL poder ejecutarse con `docker compose run --rm`, y su salida contra el corpus de ejemplo SHALL guardarse en `output_examples.txt`.

#### Scenario: Salida legible
- **WHEN** la API responde a las cinco consultas
- **THEN** el script imprime cinco bloques de cinco líneas y termina con código 0.

### Requirement: Scripts de medición y operación de la Sesión 08
`scripts/` SHALL ofrecer `s08_common.py` (embedder exigido, `QUERIES` embebidas una vez fuera de los tiempos, `vector_literal`, `format_table`, `truncate`, `Stopwatch`, `latency_summary`) y los scripts `measure_baseline_s08.py`, `sweep_ef_search_s08.py` (recall@5 frente a la verdad de fondo con `enable_indexscan = off`, ★ en el menor `ef_search` con recall a ≤0.005 del mejor), `compare_indexes_s08.py` (índice `vector` frente a `halfvec`, verificado con `EXPLAIN`; falla con mensaje claro si falta un índice), `report_index_sizes_s08.py` e `insert_synthetic_chunks_s08.py` (idempotente, `document_type='synthetic_test'`). Los scripts SHALL usar la sesión async del proyecto y SHALL NOT añadir dependencias (`rich`, `tabulate`). `scripts/sql_s08/` SHALL contener los snippets `01`–`05` y `99_revert_live_session.sql`, comentados en español.

#### Scenario: Barrido de ef_search
- **WHEN** se ejecuta `sweep_ef_search_s08.py`
- **THEN** imprime una tabla por valor de `ef_search` con latencia y recall@5, y marca con ★ el menor valor con recall ≥ mejor − 0.005.

#### Scenario: Falta un índice
- **WHEN** se ejecuta `compare_indexes_s08.py` sin alguno de los dos índices
- **THEN** termina con código distinto de 0 y un mensaje que nombra el índice ausente.
