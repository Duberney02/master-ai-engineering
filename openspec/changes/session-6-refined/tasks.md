# Tasks

Todo se ejecuta en contenedores Docker (`docker-compose.verify.yml`; PostgreSQL del Compose raíz para las pruebas de integración), nunca en el host. Rutas de referencia relativas a `estimator/` del commit `aa1fcf4`.

## 1. Dependencias, configuración y datos

- [x] 1.1 Añadir a `estimador-cag/pyproject.toml` `pandas`, `pandera`, `pyyaml`, `alembic`, `presidio-analyzer`, `spacy`, `faker` y la rueda `es-core-news-md`; regenerar `uv.lock` con `docker compose -f docker-compose.verify.yml run --rm api-uv lock`; verificar que `docker build --target test` termina sin errores.
- [x] 1.2 Añadir `catalog_path`, `ingestion_data_root`, `presidio_spacy_model`, `pseudonym_faker_locale`, `pseudonym_hash_salt` y `max_attachment_chars` a `app/config.py` y documentarlas en `.env.example` (ref. `app/config.py`, `.env.example`); verificar con `tests/test_config.py`.
- [x] 1.3 Copiar el catálogo (`data/catalog/catalog.yaml`) y el corpus (`data/seed/`: 6 JSON, 3 TXT, XLSX) de la referencia; verificar el recuento de archivos y la validación del catálogo.

## 2. Núcleo de ingesta

- [x] 2.1 Portar `app/ingestion/architecture.py` (ref. `architecture.py`); verificar con `tests/test_architecture.py` y el CLI `python -m app.ingestion.architecture`.
- [x] 2.2 Portar `app/ingestion/catalog/` (`models`, `loader`, `inspect`) (ref. `catalog/*`); verificar con `tests/test_catalog_loader.py` y los dos CLI.
- [x] 2.3 Portar `documents/`, `loaders/filesystem.py` y `parsers/` con registro JSON/TXT (ref. `documents/models.py`, `loaders/filesystem.py`, `parsers/*`); verificar con `tests/test_parsers_json.py`, `tests/test_parsers_txt.py` y las pruebas del cargador y del registro.
- [x] 2.4 Portar `cleaning/` (ref. `cleaning/*`) sin añadir reglas ausentes; verificar con `tests/test_cleaning_budgets.py` y `tests/test_validation_policy.py`.
- [x] 2.5 Portar `pii/` (analizador, reconocedores, seudonimizador, stores asíncronos) (ref. `pii/*`); verificar con `tests/test_pii_recognizers.py`, `tests/test_pii_pseudonymizer.py` y una prueba con el modelo `es_core_news_md` real.

## 3. Persistencia, migraciones y API

- [x] 3.1 Crear `app/persistence/` (motor asíncrono, modelos con base propia, `JobsRepository`, `MappingsRepository`) (ref. `app/persistence/*`); verificar con pruebas sobre SQLite en memoria y contra PostgreSQL real (`TEST_DATABASE_URL`), incluida la concurrencia de `lookup_or_create`.
- [x] 3.2 Añadir `alembic.ini`, `alembic/env.py` asíncrono, la migración `0001_session6_initial` y `python -m app.persistence.migrate` (ref. `alembic/*`); verificar subida/bajada/repetición y que `estimations` no cambia.
- [x] 3.3 Crear `app/ingestion/orchestrator.py`, `app/schemas/ingestion.py`, `app/routers/ingestion.py`, las dependencias de `app/dependencies.py` y el registro en `main.py` (ref. `orchestrator.py`, `routers/ingestion.py`, `schemas/ingestion.py`); verificar con `tests/test_ingestion_endpoint.py` (202, 404, 400, estados) y una ingesta real contra PostgreSQL.

## 4. Adjuntos

- [x] 4.1 Añadir `max_attachment_chars`, recorte, lectura de PDF por página con tolerancia a fallos, omisión de adjuntos sin texto y `--- end attachment ---` en `app/services/attachments.py` y `app/routers/sessions.py` (ref. `attachments/extractor.py`); adaptar `tests/test_attachments.py` y `tests/test_sessions_api.py`; verificar que los demás tests de adjuntos y del stress siguen pasando.

## 5. Utilidades, Docker y documentación

- [x] 5.1 Adaptar `scripts/demo_cleaning_s06.py`, `scripts/demo_pii_s06.py` y `scripts/preflight_s06.py` (ref. `scripts/*`); ejecutar las tres dentro de Docker.
- [x] 5.2 Actualizar `Dockerfile` (copiar `data/`, `alembic/`, `alembic.ini`; migrar antes de `uvicorn`), `docker-compose.verify.yml` si procede y el Compose raíz; verificar que la imagen arranca sin base de datos y con ella aplica la migración.
- [x] 5.3 Actualizar `estimador-cag/README.md`, el workflow de CI y `openspec/README.md` con los comandos Docker de levantar, desarrollar, migrar y verificar.

## 6. Verificación y cierre

- [x] 6.1 Ejecutar la suite completa (`api-test`, con `TEST_DATABASE_URL` contra el PostgreSQL del Compose), `api-lint`, las demos, el preflight y los endpoints sobre el stack levantado; registrar los resultados en `verification.md`.
- [x] 6.2 Ejecutar `openspec validate --all --strict`; si todo está implementado y verificado, archivar el cambio y sincronizar las especificaciones.
