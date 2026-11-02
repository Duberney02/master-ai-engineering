## ADDED Requirements

### Requirement: POST /search
El servicio SHALL exponer `POST /search` con `{query, k}` (`query` no vacío, `k` entero entre 1 y 50, por defecto 5). SHALL embeber la consulta con el mismo modelo que la ingesta y resolver en SQL los `k` chunks más cercanos ordenando por `Chunk.embedding.cosine_distance(vector)` (operador `<=>`) etiquetada `distance`, con `LIMIT k`. La respuesta `200` SHALL contener `query`, `k`, `search_time_ms` y `results`, cada uno con `chunk_id`, `document_id`, `chunk_type`, `content`, `distance` y `metadata`, de menor a mayor distancia. SHALL responder `422` ante entrada inválida, `503` si no hay base de datos configurada y `500` con mensaje genérico ante errores del proveedor. La búsqueda SHALL NOT usar índices vectoriales, filtros por metadata ni búsqueda híbrida.

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

### Requirement: Script de consultas de ejemplo
`scripts/query_examples.py` SHALL llamar a `/search` con cinco consultas (componente conocido, reformulación semántica, dominio distinto, ambigua y muy específica) e imprimir para cada una el top-5 con `chunk_id`, `distance` (4 decimales), `chunk_type` y los primeros ~120 caracteres de `content`. SHALL poder ejecutarse con `docker compose run --rm`, y su salida contra el corpus de ejemplo SHALL guardarse en `output_examples.txt`.

#### Scenario: Salida legible
- **WHEN** la API responde a las cinco consultas
- **THEN** el script imprime cinco bloques de cinco líneas y termina con código 0.
