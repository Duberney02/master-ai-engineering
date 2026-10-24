# estimator/embedding-ingest Specification

## Purpose
Vectorizar chunks con OpenAI y exponerlos por HTTP con estadísticas, sin persistencia.

## Requirements

### Requirement: OpenAIEmbedder
`OpenAIEmbedder` SHALL ser asíncrono y ofrecer `embed_one(text)`, `embed_texts(texts)` y `embed_many(chunks) -> list[EmbeddedChunk]` con el modelo `Settings.embedding_model` (`text-embedding-3-small` por defecto) y la dimensión `Settings.embedding_dimensions` (1536 por defecto), ambos sustituibles al construirlo; la dimensión se envía al proveedor (truncado Matryoshka). `embed_many` SHALL procesar los chunks en lotes de 100 con una única llamada a `embeddings.create` por lote, SHALL conservar la correspondencia entre cada chunk y su vector y SHALL devolver el mismo orden de entrada.

#### Scenario: Lotes y correspondencia
- **WHEN** se vectorizan 250 chunks
- **THEN** se realizan 3 llamadas (100, 100 y 50) y cada `EmbeddedChunk` conserva el `chunk_id`, el texto y el vector de su entrada.

#### Scenario: Dimensión configurada
- **WHEN** se construye el embedder con `dimensions=256`
- **THEN** cada llamada a `embeddings.create` incluye `dimensions=256`.

#### Scenario: Dimensión por defecto
- **WHEN** `EMBEDDING_DIMENSIONS` vale 768 y se construye sin dimensión explícita
- **THEN** las llamadas usan 768.

### Requirement: Reintentos ante límite de tasa
Ante `RateLimitError` el embedder SHALL reintentar hasta tres veces con esperas de 1, 2 y 4 segundos; superados los reintentos SHALL propagar el error. Cualquier otro error SHALL propagarse sin reintento.

#### Scenario: Recuperación tras dos límites
- **WHEN** las dos primeras llamadas lanzan `RateLimitError` y la tercera tiene éxito
- **THEN** se esperan 1 s y 2 s y el lote se devuelve correctamente.

#### Scenario: Error distinto
- **WHEN** el proveedor lanza un error de autenticación
- **THEN** la excepción se propaga sin reintentos.

### Requirement: Registro y coste
Por cada lote el embedder SHALL registrar con structlog la cantidad de chunks, los tokens totales y la latencia. El coste estimado SHALL calcularse como `total_tokens / 1_000_000 * PRICE_PER_MILLION_TOKENS_USD`, siendo la constante de módulo `0.02` y estando identificada como variable en el tiempo.

#### Scenario: Coste de un millón de tokens
- **WHEN** el total de tokens es 1 000 000
- **THEN** el coste estimado es 0.02 USD.

### Requirement: POST /embeddings/ingest
El servicio SHALL exponer `POST /embeddings/ingest` (prefijo `/embeddings` aplicado una sola vez en `main.py`) que reciba un `IngestRequest` y devuelva un `IngestResponse` con `chunks` vectorizados y `stats` con `total_budgets`, `total_chunks`, `total_tokens` y `estimated_cost_usd`. SHALL responder `200` si la ejecución es correcta, `422` ante entrada inválida (FastAPI/Pydantic) y `500` con un mensaje genérico ante errores del proveedor, registrando el detalle sin exponerlo. El endpoint SHALL aparecer en `/docs`.

#### Scenario: Ingesta correcta
- **WHEN** se envían los 15 presupuestos de ejemplo
- **THEN** la respuesta es `200`, `stats.total_budgets` es 15, `stats.total_chunks` es igual al número de componentes y cada vector tiene 1536 dimensiones.

#### Scenario: Entrada inválida
- **WHEN** el cuerpo no contiene `budgets` o un presupuesto no es válido
- **THEN** la respuesta es `422`.

#### Scenario: Fallo del proveedor
- **WHEN** el embedder lanza una excepción
- **THEN** la respuesta es `500` con un mensaje genérico que no contiene el texto del error original.
