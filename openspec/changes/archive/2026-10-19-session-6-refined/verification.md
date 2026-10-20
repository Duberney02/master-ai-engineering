# Verification

Todas las comprobaciones se ejecutaron en contenedores Docker (nada en el host). Fecha: 2026-10-19. Rama `feature/session_6_refined`, desde `master` en `42b503e`. Referencia: `session_06_live` en `aa1fcf46f20de86aaf9b3b55fffd4f1befbcb8a1`, directorio `estimator/`.

## Resultados

| Comprobación | Comando (contenedor) | Resultado |
|---|---|---|
| Suite completa con PostgreSQL real | `docker run --network estimator_estimator-net -v <repo>:/repo -e TEST_DATABASE_URL=…/estimator_test estimador-cag:test pytest -q` (base `estimator_test` creada aparte en el servicio `postgres` del Compose raíz; el historial real no se toca) | 1118 passed, 0 skipped |
| Suite sin PostgreSQL ni Compose raíz (como en `api-test`) | `docker compose -f docker-compose.verify.yml run --rm api-test` | 1111 passed, 6 skipped (5 de `test_project_structure.py` que requieren el Compose raíz, 1 que requiere `estimator-web`; pasan al montar el repositorio completo) |
| Pruebas de la ingesta contra PostgreSQL | `tests/test_ingestion_postgres.py` + `tests/test_history_postgres.py` | 7 passed (migraciones, UUID nativo, concurrencia de `lookup_or_create` con 8 llamadas simultáneas, restricción única, `forget`, seudonimizador con el store de PostgreSQL, ingesta real) |
| Lint | `docker compose -f docker-compose.verify.yml run --rm api-lint` | All checks passed |
| OpenSpec | `docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict` | 32 passed, 0 failed |
| Imagen runtime | `docker compose build estimador-cag` | se construye con spaCy y el modelo `es_core_news_md` |
| Imagen sin base de datos (como el job `docker` del CI) | `docker run -e OPENAI_API_KEY=… estimador-cag:latest` | `healthy`; «DATABASE_URL no definida: se omiten las migraciones» |
| Migración al arrancar | `docker compose up -d estimador-cag` (stack real, `postgres_data` existente) | `Running upgrade -> 0001_session6_initial`; `estimations` conserva sus 880 filas; relanzar es idempotente |
| API en el stack | `curl` a `POST /api/v1/ingestion/runs` y `GET …/jobs/{id}` | 202 → `completed` con 6 documentos; 400 (`review`, `exclude`); 404 (fuente y trabajo desconocidos); `/health` y `/api/v1/estimations` siguen respondiendo 200 |
| Logs estructurados | `docker compose logs estimador-cag` | `ingestion.started/completed` con `job_id`, `source_name`, `format`, `documents_count` |
| Preflight | `docker compose exec estimador-cag python scripts/preflight_s06.py` | 7/7 comprobaciones superadas (paquetes, modelo español, corpus, catálogo, `/health`, tablas) |
| Demos y CLI | `scripts/demo_cleaning_s06.py`, `scripts/demo_pii_s06.py`, `python -m app.ingestion.architecture`, `…catalog.loader`, `…catalog.inspect` | se ejecutan; véanse las observaciones |

## Trazabilidad

| Requisito (spec) | Referencia | Código | Pruebas |
|---|---|---|---|
| cag-viability-assessment | `app/ingestion/architecture.py` | `app/ingestion/architecture.py` | `tests/test_architecture.py`, `tests/test_ingestion_core.py::test_architecture_cli_prints_the_reference_scenario` |
| source-catalog | `catalog/{models,loader,inspect}.py`, `data/catalog/catalog.yaml` | `app/ingestion/catalog/`, `data/catalog/catalog.yaml` | `tests/test_catalog_loader.py`, `tests/test_ingestion_core.py` (catálogo de ejemplo, CLI, inspector) |
| document-ingestion | `documents/models.py`, `loaders/filesystem.py`, `parsers/*` | `app/ingestion/{documents,loaders,parsers}/` | `tests/test_parsers_json.py`, `tests/test_parsers_txt.py`, `tests/test_ingestion_core.py` (cargador, registro, modelos) |
| budget-cleaning | `cleaning/*` | `app/ingestion/cleaning/` | `tests/test_cleaning_budgets.py`, `tests/test_validation_policy.py`, `test_ingestion_does_not_run_cleaning_or_pseudonymization` |
| pii-pseudonymization | `pii/*` | `app/ingestion/pii/` | `tests/test_pii_recognizers.py`, `tests/test_pii_pseudonymizer.py`, `tests/test_pii_spanish_model.py` (modelo real), `tests/test_ingestion_postgres.py` |
| ingestion-persistence | `app/persistence/*`, `alembic/*` | `app/persistence/`, `alembic/`, `alembic.ini` | `tests/test_ingestion_persistence.py`, `tests/test_ingestion_postgres.py` |
| ingestion-orchestration | `orchestrator.py`, `routers/ingestion.py`, `schemas/ingestion.py` | `app/ingestion/orchestrator.py`, `app/routers/ingestion.py`, `app/schemas/ingestion.py`, `app/dependencies.py` | `tests/test_ingestion_endpoint.py`, `tests/test_ingestion_core.py` (orquestador y logs) |
| ingestion-tooling | `app/config.py`, `.env.example`, `data/`, `scripts/*` | `app/config.py`, `.env.example`, `data/`, `scripts/` | `tests/test_ingestion_core.py` (ajustes y corpus); demos y preflight ejecutados |
| attachment-extraction (modificado) | `attachments/extractor.py` | `app/services/attachments.py`, `app/config.py` | `tests/test_attachments.py`, `tests/test_sessions_api.py` |
| deployment-stack (añadido) | `docker-compose.yml`, `alembic.ini` | `Dockerfile`, `app/persistence/migrate.py` | migración real en el stack; imagen sin base de datos `healthy` |

## Capacidades omitidas por equivalencia

Sesiones, metadatos, memoria con resumen y anclas, audiencia, Actor–Critic–Boss, cachés exacta y semántica, generación estructurada, fallback, métricas, evaluaciones, historial (`app/services/history.py`, sobre el mismo PostgreSQL), extracción PDF/DOCX (`app/services/attachments.py`), clientes Streamlit/React/Rails.

## Inconsistencias de la referencia y ajustes mínimos

- **Nombres**: la referencia usa la función `ingest_source` (no una clase `IngestionOrchestrator`) y `FileSystemLoader` (no `FilesystemLoader`); se conservaron.
- **Persistencia síncrona**: la referencia usa SQLAlchemy síncrono con `psycopg`; el destino ya usa SQLAlchemy asíncrono con `asyncpg`, por lo que repositorios, stores, `pseudonymize` y el orquestador son `async` (mismo contrato). `UUID` de PostgreSQL → `sa.Uuid`.
- **Comentarios que sugieren comportamientos no implementados**: `cleaning/schemas.py` describe una suma de importes de fases que no existe (no se añadió) y decora una función vacía con `@pa.check_input` (se eliminó, sin efecto funcional); `pii/` y `persistence/models.py` hablan de mapeo «reversible» (no hay desseudonimización; se reescribió el texto y no se añadió ningún endpoint de borrado); el registro y el preflight aluden a parsers y a `unstructured` que no existen (no se instalaron `unstructured`, `psycopg`, `presidio-anonymizer` ni `openpyxl`).
- **Comportamientos de la referencia conservados que conviene conocer**: (1) con `strict=True` en Pandera, las columnas adicionales del registro cuentan como fallo `column_in_schema` y `total_amount` entero provoca un fallo `dtype('float64')` que mueve una fila válida a cuarentena (la demo muestra 3 válidas, 1 en cuarentena y 1 descartada, mientras el docstring de la referencia anuncia «el resto pasa»); (2) las entidades solapadas que devuelve Presidio no se resuelven y el reemplazo de derecha a izquierda puede mezclar un `CLIENT_CODE` con un `PERSON` (visible en `demo_pii_s06.py`); (3) `python -m app.ingestion.catalog.loader` emite un `RuntimeWarning` de `runpy` porque el paquete importa el módulo; (4) `pd.to_datetime(..., dayfirst=True)` avisa con fechas ISO.
- **Compose de la referencia**: usa `pgvector/pgvector:pg16` sin activar la extensión; no se adoptó (cambiar de PostgreSQL 17 a 16 invalidaría el volumen `postgres_data`).
- **Registro de logs**: el destino filtra los campos de log con una lista permitida (`SAFE_FIELDS`); se añadieron solo identificadores operativos de la ingesta y los mensajes de error en bruto no se registran (el error se guarda en el trabajo, como en la referencia).

## Limitaciones y observaciones

- Cambio de comportamiento deliberado y requerido: un adjunto que se abre pero no tiene texto ya no devuelve 422 (se omite); un PDF con todas las páginas ilegibles sigue siendo 422 (interpretación de «distinguir ilegible de sin texto»).
- El tope `MAX_ATTACHMENT_CHARS` (60 000 por defecto) también recorta los adjuntos grandes del stress test (`--attachment-sizes` hasta 100 KB); las pruebas del stress siguen pasando, pero una nueva medición podría diferir de `evals/stress/results.csv`.
- `PSEUDONYM_HASH_SALT` conserva el valor por defecto de la referencia (`change-me-in-prod`); hay que cambiarlo fuera de desarrollo.
- El mensaje de error de un trabajo fallido (p. ej., una ubicación del catálogo inexistente) se devuelve en `GET /ingestion/jobs/{id}` y puede incluir una ruta del servidor, como en la referencia.
- La API de ingesta responde 503 si no hay `DATABASE_URL` (adaptación del destino, donde la base de datos es opcional).
- Los docstrings portados de la referencia siguen en inglés; el código nuevo del destino, en español.
- No se ejecutó ninguna llamada a un proveedor LLM real. Las webs Rails y React no se tocaron ni se re-ejecutaron sus pruebas.
- Los servicios `estimador-cag-chat`, `estimator-web` y `estimator-web-react` del Compose raíz no estaban levantados y no se reconstruyeron; la comprobación del stack cubrió `estimador-cag`, `postgres` y `redis`.
- La otra carpeta de cambio abierta, `estimador-stress-test-cag`, no pertenece a este alcance y se dejó sin archivar.
