## 1. Infraestructura (Postgres con pgvector)

- [x] 1.1 `docker-compose.yml`: servicio `postgres` con `pgvector/pgvector:pg17`, puerto 5432, healthcheck 5 s/5 s/10; checkpoint con `psql SELECT version()`
- [x] 1.2 `docker-compose.verify.yml` y CI: base pgvector efímera y `TEST_DATABASE_URL` en `api-test`
- [x] 1.3 Dependencia `pgvector>=0.3` en `pyproject.toml` y regenerar `uv.lock`; reconstruir la imagen de pruebas

## 2. Esquema y migraciones

- [ ] 2.1 `alembic/env.py`: registrar `ischema_names["vector"]` en la ejecución de migraciones
- [ ] 2.2 Modelos ORM `Document` y `Chunk` en `foundation/persistence/models.py`
- [ ] 2.3 Migración `0002_pgvector_documents_chunks` (extensión, tablas, índices no vectoriales)
- [ ] 2.4 `alembic upgrade head` y `alembic check` limpios en Docker; ajustar la prueba que fija la revisión `0001`

## 3. Ingesta persistente

- [ ] 3.1 Contratos `IngestRequest`/`IngestResponse` nuevos y `SearchRequest`/`SearchResponse`
- [ ] 3.2 `DocumentStore.ingest` (transacción única, duplicados, dimensión) en `generation/rag/store/`
- [ ] 3.3 Refactor de `POST /embeddings/ingest` (200/409/422/503/500) y fábrica en `dependencies.py`
- [ ] 3.4 Pruebas: ingesta OK, 409, rollback si falla el embedder, dimensión incompatible; retirar la prueba del contrato antiguo

## 4. Búsqueda semántica

- [ ] 4.1 `DocumentStore.search` con `cosine_distance`
- [ ] 4.2 `POST /search` y registro del router en `main.py`
- [ ] 4.3 Pruebas de `/search`: top-k ordenado, k fuera de rango, base vacía, fallo del proveedor

## 5. Scripts y corpus

- [ ] 5.1 `scripts/ingest_corpus.py` e ingesta del corpus de ejemplo contra el stack
- [ ] 5.2 `scripts/query_examples.py` (reemplaza `scripts/compare.py`) y `output_examples.txt`

## 6. Documentación y verificación

- [ ] 6.1 Sección del README con las justificaciones; actualizar `ARCHITECTURE.md` y comandos obsoletos
- [ ] 6.2 `api-test`, `api-lint` y `openspec validate --all --strict` en verde; revisión de que nada queda fuera de alcance
