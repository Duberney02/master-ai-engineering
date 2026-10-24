# Spec Delta

## Purpose

Vectorizar chunks con OpenAI de forma asíncrona, con modelo y dimensión configurables.

## MODIFIED Requirements

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
