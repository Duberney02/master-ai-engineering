## MODIFIED Requirements

### Requirement: POST /embeddings/ingest
El servicio SHALL exponer `POST /embeddings/ingest` (prefijo `/embeddings` aplicado una sola vez en `main.py`) que reciba `{source_path, document_type, content}`, donde `content` es el JSON completo de un presupuesto, lo persista como un `document` con sus `chunks` vectorizados (ver `vector-persistence`) y responda `200` con `document_id`, `chunks_created`, `embedding_dimension` e `ingestion_time_ms`. SHALL responder `409` con `{"detail": "Document already ingested", "document_id": <id>}` si ya existe un documento con ese `source_path`, `422` ante entrada inválida (FastAPI/Pydantic), `503` si no hay base de datos configurada y `500` con un mensaje genérico ante errores del proveedor o de la base, registrando el detalle sin exponerlo. El endpoint SHALL aparecer en `/docs`.

#### Scenario: Ingesta correcta
- **WHEN** se envía un presupuesto válido con tres componentes
- **THEN** la respuesta es `200`, `chunks_created` es 3, `embedding_dimension` es 1536 y existen una fila en `documents` y tres en `chunks`.

#### Scenario: Duplicado
- **WHEN** se envía otra vez el mismo `source_path`
- **THEN** la respuesta es `409` con el `document_id` original y no se crean filas nuevas.

#### Scenario: Entrada inválida
- **WHEN** falta `source_path` o `content` no es un presupuesto válido
- **THEN** la respuesta es `422`.

#### Scenario: Fallo del proveedor
- **WHEN** el embedder lanza una excepción
- **THEN** la respuesta es `500` con un mensaje genérico que no contiene el texto del error original y no queda ningún `document` huérfano.
