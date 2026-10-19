# Proposal

## Why

La sesión 6 del curso (referencia `session_06_live`, commit `aa1fcf46f20de86aaf9b3b55fffd4f1befbcb8a1`, directorio `estimator/`) añade a `estimator` un subsistema de ingesta de datos: decisión CAG/RAG, catálogo auditable de fuentes, parsers a un modelo documental común, limpieza y validación de presupuestos, seudonimización consistente de PII, persistencia con migraciones y una API de seguimiento. `estimador-cag` ya cubre estimaciones, caché, sesiones, memoria, Actor–Critic–Boss, evaluaciones y clientes web, pero no estas capacidades, y su extracción de adjuntos carece de cuatro comportamientos de la referencia. Este cambio traslada **solo** esas diferencias verificadas.

## What Changes

Clasificación de las capacidades de la referencia frente a `estimador-cag/` (rama `feature/session_6_refined`, partiendo de `master` en `42b503e`):

| Capacidad (archivo de referencia) | Estado en el destino | Decisión |
|---|---|---|
| Viabilidad CAG y recomendación (`app/ingestion/architecture.py`) | ausente | implementar |
| Catálogo: modelos, loader, inspector, `catalog.yaml` | ausente | implementar |
| `Document`, `FileSystemLoader`, protocolo y registro de parsers, parsers JSON y TXT | ausente | implementar |
| Limpieza pandas y política Pandera (`cleaning/*`) | ausente | implementar |
| Presidio, reconocedores, seudonimizador y stores (`pii/*`) | ausente | implementar |
| Tablas `ingestion_jobs` y `pseudonym_mappings`, repositorios, Alembic | parcial: existe PostgreSQL asíncrono (`asyncpg`) con la tabla `estimations` creada por `create_all` | añadir tablas y Alembic; **reutilizar** el motor asíncrono, sin sustituir el historial |
| Orquestador `ingest_source` y endpoints `POST /ingestion/runs`, `GET /ingestion/jobs/{id}` | ausente | implementar |
| Ajustes `CATALOG_PATH`, `INGESTION_DATA_ROOT`, `PRESIDIO_SPACY_MODEL`, `PSEUDONYM_FAKER_LOCALE`, `PSEUDONYM_HASH_SALT`; corpus; demos y preflight | ausente | implementar |
| Extracción PDF/DOCX | existente (`app/services/attachments.py`, más completa que la referencia: firma de contenido, límites de tamaño/páginas/zip, saneo de nombre) | **no reimplementar**; solo añadir `MAX_ATTACHMENT_CHARS` con recorte, tolerancia a páginas ilegibles, omisión de adjuntos sin texto y delimitador `--- end attachment ---` |
| Sesiones, memoria, audiencia, Actor–Critic–Boss, cachés, generación estructurada, fallback, métricas, evaluaciones, historial, clientes | existentes | **excluidas por equivalencia** |

Cambios concretos:

- Paquete `app/ingestion/` (`architecture`, `catalog/`, `documents/`, `loaders/`, `parsers/`, `cleaning/`, `pii/`, `orchestrator`) y paquete `app/persistence/` (motor asíncrono, modelos, repositorios).
- Router `app/routers/ingestion.py` y esquemas `app/schemas/ingestion.py`, registrados en `main.py`; dependencias de catálogo, cargador y registro en `app/dependencies.py`.
- Alembic (`alembic.ini`, `alembic/`) con la migración inicial de las dos tablas, aplicada al arrancar el contenedor de la API cuando hay `DATABASE_URL`.
- Dependencias: `pandas`, `pandera`, `pyyaml`, `alembic`, `presidio-analyzer`, `spacy`, `es-core-news-md`, `faker`; regeneración de `uv.lock` en Docker.
- Corpus de ejemplo (6 presupuestos JSON, 3 transcripciones TXT, XLSX de tarifas) y catálogo con las tres fuentes de la referencia.
- Scripts `demo_cleaning_s06.py`, `demo_pii_s06.py` y `preflight_s06.py` adaptados.
- Adjuntos: `MAX_ATTACHMENT_CHARS` (60 000 por defecto), páginas PDF ilegibles toleradas, adjuntos sin texto omitidos, cierre `--- end attachment ---`.
- Pruebas adaptadas de la referencia y documentación de los comandos Docker.

**Fuera de alcance** (tal como en la referencia): recuperación RAG, embeddings o índice de los documentos ingeridos, pgvector activo, parsers XLSX/DOCX/PDF de ingesta, OCR, colas externas, nuevos endpoints o interfaces, conexión automática entre limpieza, seudonimización, ingesta y el pipeline de estimación, desseudonimización y endpoints de borrado.

## Capabilities

### New Capabilities
- `estimator/cag-viability-assessment`: perfiles de corpus y modelo, cuatro restricciones CAG, recomendación `CAG`/`Hybrid`/`RAG` y CLI.
- `estimator/source-catalog`: catálogo YAML validado con Pydantic, decisiones auditables, CLI de validación e inspector de carpetas.
- `estimator/document-ingestion`: modelo `Document`, cargador de sistema de archivos, protocolo y registro de parsers, parsers de presupuestos JSON y transcripciones TXT.
- `estimator/budget-cleaning`: limpieza con pandas y partición válidos/cuarentena/descartados con Pandera.
- `estimator/pii-pseudonymization`: analizador Presidio en español, reconocedores del dominio, seudonimizador consistente con HMAC y stores en memoria/PostgreSQL.
- `estimator/ingestion-persistence`: tablas `ingestion_jobs` y `pseudonym_mappings`, repositorios y migraciones Alembic.
- `estimator/ingestion-orchestration`: orquestador de ingesta y API de seguimiento.
- `estimator/ingestion-tooling`: configuración, corpus de ejemplo, demos y preflight.

### Modified Capabilities
- `estimator/attachment-extraction`: límite de caracteres, páginas ilegibles, adjuntos sin texto y delimitador de cierre.
- `estimator/deployment-stack`: migraciones y datos de ingesta disponibles en el contenedor de la API.

## Impact

- Código: `estimador-cag/app/` (nuevos paquetes, `config.py`, `dependencies.py`, `main.py`, `services/attachments.py`, `routers/sessions.py`), `Dockerfile`, `pyproject.toml`, `uv.lock`, `.env.example`, `README.md`, `tests/`.
- Compose raíz: la API conserva `postgres:17-alpine` y sus volúmenes; la imagen pgvector de la referencia no se adopta porque la extensión sigue inactiva y cambiar de versión mayor de PostgreSQL invalidaría el volumen existente.
- El contrato HTTP existente no cambia salvo el comportamiento de adjuntos sin texto, que pasa de 422 a omitirse.
