## Context

El repo ya tiene PostgreSQL (`postgres:17-alpine`, base `estimator`, historial + ingesta de la Sesión 6), Alembic con
plantilla asíncrona (`alembic/env.py` lee la URL de `Settings.database_url`, migración `0001_session6_initial`) y
SQLAlchemy asíncrono con `get_session`. El enunciado del ejercicio asume un proyecto vacío (`ai_service`, pg16,
`alembic init`); estas son las adaptaciones y decisiones sobre la base real.

## Decisiones

- **Imagen `pgvector/pgvector:pg17`, no pg16.** El volumen existente es de pg17 y pg16 no puede leerlo; se conserva el
  servicio `postgres`, la contraseña (`POSTGRES_PASSWORD`, por defecto `estimator-dev`) y el volumen `postgres_data`.
  Se publica `5432:5432` como pide el ejercicio (acceso local con `psql`).
- **Alembic ya existe**: no se ejecuta `alembic init`. Se añade la migración `0002_pgvector_documents_chunks` (la `0001`
  está ocupada). En `env.py` se registra `ischema_names["vector"]` para que `alembic check` reconozca la columna.
- **Modelos en `foundation/persistence/models.py`**, misma `Base` que descubre Alembic (una sola fuente de verdad del
  esquema). El atributo ORM se llama `metadata_` (mapeado a la columna `metadata`) porque `metadata` está reservado por
  SQLAlchemy.
- **Servicio en `generation/rag/store/`** (el hueco reservado en la arquitectura): `DocumentStore` recibe la sesión, el
  chunker estructural y el embedder y ofrece `ingest(...)` y `search(...)`. Los routers (`api/embeddings.py`,
  `api/search.py`) son finos y las fábricas viven en `app/dependencies.py`.
- **Transacción única en la ingesta**: comprobar duplicado → `INSERT documents` (+`flush` para el id) → chunker →
  `embed_many` → `add_all(chunks)` → `commit`. Si el embedder falla se hace *rollback* y no queda ningún `document`
  huérfano. Coste asumido: la transacción permanece abierta durante la llamada al proveedor (el ejercicio lo exige).
- **Duplicados**: se comprueba `source_path` antes de insertar y, además, el índice `ix_documents_source_path` es
  `UNIQUE` para que dos ingestas concurrentes no creen dos documentos; el `IntegrityError` se traduce también en `409`.
- **Lotes**: `embed_many` ya agrupa en lotes de 100 con una llamada `embeddings.create` por lote; un presupuesto cabe en
  un único lote.
- **Dimensión fija 1536**: la columna es `vector(1536)` (`text-embedding-3-small`). Si `embedding_dimensions` difiere,
  la ingesta falla con un error saneado en vez de insertar un vector de otra dimensión.
- **Búsqueda**: `Chunk.embedding.cosine_distance(vector)` etiquetada `distance`, `ORDER BY distance`, `LIMIT k`;
  `k` entre 1 y 50 (por defecto 5). Sin índice vectorial: *sequential scan*. Los chunks con `embedding NULL` quedan
  fuera de los resultados (la distancia es `NULL` y se excluye explícitamente).
- **Errores saneados**: fallos del proveedor → `500` genérico; sin `DATABASE_URL` → `503` (comportamiento de
  `get_session`).
- **Pruebas**: `docker-compose.verify.yml` añade una base `api-db` (pgvector efímera) y `api-test` recibe
  `TEST_DATABASE_URL`, de modo que las pruebas de integración dejan de omitirse. Las nuevas usan un embedder falso
  determinista de 1536 dimensiones.
- **Corpus**: `data/budgets_sample.json` es una lista de 15 presupuestos; `scripts/ingest_corpus.py` los envía uno a uno
  a `POST /embeddings/ingest` con `source_path = "data/budgets_sample.json#<budget_id>"`.

## Riesgos / compromisos

- Cambio incompatible en `/embeddings/ingest`: verificado que web Go, React y Streamlit solo usan `/embeddings/compare`.
- El servidor publica el puerto 5432 en el host: solo para desarrollo local.
