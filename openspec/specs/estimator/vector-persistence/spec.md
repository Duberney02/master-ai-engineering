# estimator/vector-persistence Specification

## Purpose
PostgreSQL con pgvector, esquema `documents`/`chunks` bajo Alembic y persistencia transaccional de presupuestos vectorizados.

## Requirements

### Requirement: PostgreSQL con pgvector
El Compose raíz SHALL declarar el servicio `postgres` con la imagen `pgvector/pgvector:pg17`, `POSTGRES_DB`/`POSTGRES_USER` `estimator`, puerto `5432:5432`, volumen `postgres_data` y *healthcheck* `pg_isready -U estimator -d estimator` (intervalo 5 s, timeout 5 s, 10 reintentos). El servicio SHALL declarar `shm_size: 1gb` y arrancar con `shared_buffers=512MB`, `effective_cache_size=1536MB`, `work_mem=64MB`, `maintenance_work_mem=512MB` y `max_parallel_maintenance_workers=2`, con un comentario que los identifique como valores conservadores de desarrollo que escalan con la RAM en producción. El servicio de la API SHALL depender de `postgres` con `condition: service_healthy` y recibir `DATABASE_URL` con el driver `asyncpg`. El Compose de verificación y el CI SHALL ofrecer una base con pgvector para las pruebas de integración.

#### Scenario: Extensión disponible
- **WHEN** se levanta `postgres` y se ejecutan las migraciones
- **THEN** `SELECT extname FROM pg_extension` incluye `vector`.

#### Scenario: Tuning aplicado
- **WHEN** se levanta `postgres` con el Compose raíz
- **THEN** `SHOW shared_buffers` devuelve `512MB`.

### Requirement: Esquema documents y chunks bajo Alembic
Una migración Alembic SHALL ejecutar `CREATE EXTENSION IF NOT EXISTS vector` y crear `documents` (`id` bigint PK, `source_path` text no nulo, `document_type` varchar(50) no nulo, `ingested_at` timestamptz por defecto `now()` no nulo, `metadata` JSONB por defecto `{}` no nulo, índice único `ix_documents_source_path`) y `chunks` (`id` bigint PK, `document_id` bigint FK a `documents.id` con `ON DELETE CASCADE` no nulo, `chunk_type` varchar(50) no nulo, `content` text no nulo, `embedding` `vector(1536)` nulable, `metadata` JSONB por defecto `{}` no nulo, `created_at` timestamptz por defecto `now()` no nulo) con los índices `ix_chunks_document_id`, `ix_chunks_chunk_type` y `ix_chunks_metadata_gin` (GIN sobre `metadata`). La migración `0002` SHALL NOT crear ningún índice vectorial; los índices vectoriales los crea la migración `0003`. Los modelos ORM `Document` y `Chunk` SHALL ser coherentes con la migración: `alembic check` no detecta diferencias.

#### Scenario: Migración limpia
- **WHEN** se ejecuta `alembic upgrade head` sobre una base vacía y luego `alembic check`
- **THEN** ambas terminan con éxito y `alembic check` no informa de cambios pendientes.

#### Scenario: Sin índice vectorial
- **WHEN** solo se ha aplicado la migración `0002` y se listan los índices de `chunks`
- **THEN** ninguno usa `hnsw` ni `ivfflat`.

#### Scenario: Borrado en cascada
- **WHEN** se elimina un `document`
- **THEN** se eliminan sus `chunks`.

### Requirement: Persistencia atómica de un presupuesto
La ingesta SHALL ejecutarse en una única sesión y transacción asíncrona: comprobar que no existe un `document` con ese `source_path`, crear el `document`, trocear el contenido con el chunker estructural, generar los embeddings por lotes, añadir todos los `chunks` y confirmar. Cada chunk SHALL guardar `chunk_type` `budget_component`, su texto en `content`, su vector y sus metadatos. Un fallo del embedder o de la base SHALL deshacer la transacción sin dejar `documents` huérfanos. Si el vector no tiene 1536 dimensiones la ingesta SHALL fallar sin persistir nada.

#### Scenario: Fallo del embedder
- **WHEN** el embedder lanza una excepción durante la ingesta
- **THEN** no existe ningún `document` ni `chunk` para ese `source_path`.

#### Scenario: Dimensión incompatible
- **WHEN** el embedder devuelve vectores de 768 dimensiones
- **THEN** la ingesta responde `500` genérico y no se persiste nada.

### Requirement: Índices HNSW versionados
Una migración Alembic `0003` SHALL crear con `CREATE INDEX CONCURRENTLY` (dentro de `autocommit_block()`) `chunks_embedding_halfvec_idx` (`USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops) WITH (m = 16, ef_construction = 128)`) y `chunks_embedding_idx` (`USING hnsw (embedding vector_cosine_ops)` con los mismos parámetros, para comparar). La columna `embedding` SHALL seguir siendo `vector(1536)`. `downgrade` SHALL eliminarlos con `DROP INDEX CONCURRENTLY IF EXISTS`. La dimensión SHALL salir de una constante compartida con el modelo ORM.

#### Scenario: Índices con la operator class correcta
- **WHEN** se ejecuta `alembic upgrade head`
- **THEN** `pg_indexes` contiene ambos índices `hnsw`, el halfvec con `halfvec_cosine_ops` y el otro con `vector_cosine_ops`.

#### Scenario: Migración reversible
- **WHEN** se ejecuta `alembic downgrade 0002` y luego `alembic upgrade head`
- **THEN** ambos terminan sin error y `alembic check` no detecta diferencias.
