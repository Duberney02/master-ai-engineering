## Why

El pipeline de la Sesión 7 (chunking estructural + embeddings) es efímero: `POST /embeddings/ingest` devuelve los
vectores y los descarta, así que no se puede consultar el corpus histórico. La Sesión 8 persiste los presupuestos en
PostgreSQL + pgvector y expone búsqueda semántica sobre ellos, dejando el *sequential scan* como línea base para medir
después los índices vectoriales.

## What Changes

- El servicio `postgres` del Compose raíz pasa a `pgvector/pgvector:pg17` (misma versión mayor que la actual, para
  conservar el volumen `postgres_data` y las credenciales). El Compose de verificación y el CI también usan pgvector.
- Nueva migración Alembic `0002` (`CREATE EXTENSION vector` + tablas `documents` y `chunks` + índices no vectoriales) y
  modelos ORM `Document`/`Chunk` en la misma base declarativa que ya gestiona Alembic.
- Dependencia `pgvector>=0.3` (SQLAlchemy, asyncpg y Alembic ya están declarados).
- **BREAKING**: `POST /embeddings/ingest` cambia de contrato: recibe un presupuesto (`source_path`, `document_type`,
  `content`), lo persiste como `document` + `chunks` con embedding en una sola transacción y responde `200` con
  `document_id`/`chunks_created`, o `409` si el `source_path` ya existe. El contrato anterior (`{budgets}` →
  vectores) desaparece; ningún cliente lo consume (el Chunking Lab usa `/embeddings/compare`, que no cambia).
- Nuevo `POST /search`: embebe la consulta con el mismo modelo y devuelve los `k` chunks más cercanos por distancia
  coseno (`<=>`).
- Nuevos scripts `ingest_corpus.py` (carga el corpus de ejemplo vía API) y `query_examples.py` (sustituye a
  `scripts/compare.py`), con la salida guardada en `output_examples.txt`.
- Sección nueva del README con las justificaciones de diseño.

### Fuera de alcance (explícito)

Índices vectoriales (HNSW/IVFFlat), filtros por metadata en la búsqueda, búsqueda híbrida y ajuste de parámetros de
Postgres. El *sequential scan* es el baseline.

## Capabilities

### New Capabilities
- `vector-persistence`: Postgres con pgvector, esquema `documents`/`chunks` bajo Alembic y persistencia transaccional.
- `semantic-search`: `POST /search` por distancia coseno y script de consultas de ejemplo.

### Modified Capabilities
- `embedding-ingest`: `POST /embeddings/ingest` deja de ser stateless y pasa a persistir con manejo de duplicados.

## Impact

- Código: `estimador-cag/app/{api,foundation/persistence,generation/rag}`, `app/dependencies.py`, `app/main.py`,
  `alembic/versions/`, `scripts/`, `pyproject.toml` + `uv.lock`.
- Infra: `docker-compose.yml`, `docker-compose.verify.yml`, `.github/workflows/estimador-cag-ci.yml`.
- Tests: se retira la prueba del contrato antiguo; las pruebas con PostgreSQL pasan a ejecutarse en `api-test`.
- Docs: `estimador-cag/README.md`, `ARCHITECTURE.md`, specs.
