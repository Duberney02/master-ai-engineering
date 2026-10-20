# Design

## Context

`estimador-cag` es una API FastAPI asíncrona (SQLAlchemy `asyncio` + `asyncpg`, SDK asíncronos, errores saneados) con configuración en minúsculas (`pydantic-settings`, `case_sensitive=False`). La referencia usa SQLAlchemy **síncrono** con `psycopg`, configuración en mayúsculas y rutas bajo `app/routers`. Ver `proposal.md` para la clasificación de capacidades.

## Goals / Non-Goals

**Goals:** trasladar las diferencias verificadas conservando reglas y umbrales de la referencia; reutilizar la infraestructura PostgreSQL/Docker/Compose existente; mantener cada módulo independiente tal como en la referencia.

**Non-Goals:** RAG, embeddings, índice, pgvector, parsers adicionales, desseudonimización, nuevos endpoints, conectar limpieza o seudonimización al orquestador o al pipeline de estimación.

## Decisions

**Persistencia asíncrona sobre el driver existente.** Se adapta la referencia a `AsyncSession` + `asyncpg` en lugar de añadir `psycopg` y un segundo motor síncrono. `app/persistence/database.py` crea un motor perezoso a partir de `database_url` (el mismo ajuste que usa el historial). Los modelos usan una `Base` **propia** (no la del historial): así `create_all` del historial no crea las tablas de ingesta y Alembic no intenta gestionar `estimations`. Alternativa descartada: motor síncrono con `psycopg`, que duplicaría la capa de persistencia y mezclaría dos drivers en el mismo proceso.

**Repositorios y stores asíncronos.** `JobsRepository` y `MappingsRepository` exponen métodos `async`; `MappingStore.lookup_or_create` y `forget` también (`InMemoryMappingStore` y `PostgresMappingStore`), y `ConsistentPseudonymizer.pseudonymize` es `async`. El analizador de Presidio es CPU síncrono y se invoca con `asyncio.to_thread`. El comportamiento ante concurrencia se conserva: `INSERT … ON CONFLICT DO NOTHING RETURNING` sobre la restricción única `(entity_type, original_hash)` y relectura si otro escritor gana.

**Orquestador.** La referencia expone la función `ingest_source`, no una clase. Se conserva como `async def ingest_source(...)` en `app/ingestion/orchestrator.py` (mismo contrato y excepción `IngestionRejected`); la lectura de archivos y el parseo, síncronos, se ejecutan con `asyncio.to_thread` para no bloquear el bucle. La API valida la fuente, registra el trabajo, programa la ejecución con `BackgroundTasks` y responde 202; la tarea abre **su propia** sesión de base de datos.

**Rutas y estructura.** Mismos nombres de módulo que la referencia (`app.ingestion.*`, `app.persistence.*`, `app.routers.ingestion`, `app.schemas.ingestion`). El router lleva el prefijo `/ingestion` y se registra en `main.py` con `/api/v1`, como el resto de routers del destino, de modo que las rutas finales son las de la referencia. La clase de cargador conserva el nombre de la referencia, `FileSystemLoader` (el enunciado la llama `FilesystemLoader`; es la misma capacidad).

**Configuración.** Se añaden `catalog_path`, `ingestion_data_root`, `presidio_spacy_model`, `pseudonym_faker_locale`, `pseudonym_hash_salt` y `max_attachment_chars` a `Settings` (variables `CATALOG_PATH`, etc.). Las rutas relativas se resuelven desde el directorio de trabajo (`/app` en el contenedor), igual que en la referencia. `DATABASE_URL` sigue siendo el de `asyncpg`.

**Migraciones.** Alembic con `env.py` asíncrono (`async_engine_from_config` + `run_sync`) y la URL tomada de `Settings`. La migración `0001_session6_initial` crea ambas tablas con las mismas columnas, restricción única e índices que la referencia, usando `sa.Uuid` (UUID nativo en PostgreSQL). `python -m app.persistence.migrate` aplica `upgrade head` y no hace nada si no hay `DATABASE_URL`, de modo que la imagen sigue arrancando sin base de datos (como exige el CI). El `CMD` de la imagen lo ejecuta antes de `uvicorn`. `alembic_version` convive con la tabla `estimations` sin tocarla.

**Dependencias.** Solo las que ejecuta el código portado: `pandas`, `pandera`, `pyyaml`, `alembic`, `presidio-analyzer`, `spacy`, `faker` y el modelo `es-core-news-md` (rueda oficial fijada por URL, versión compatible con spaCy 3.8). No se añaden `psycopg`, `presidio-anonymizer`, `unstructured` ni `openpyxl`, que la referencia declara pero su código de este alcance no usa.

**Datos en la imagen.** El `Dockerfile` copia `data/`, `alembic/` y `alembic.ini` a la imagen runtime; en desarrollo el Compose de verificación monta todo el directorio.

**Adjuntos (modificación mínima).** `extract_attachments` recibe el tope de caracteres de `Settings.max_attachment_chars`. El PDF se lee página a página: un fallo de página se registra y se conservan las legibles; un PDF que no puede abrirse sigue siendo 422. Un adjunto que se abre pero no produce texto se omite (se registra) en lugar de devolver 422; si el resto de la solicitud no alcanza el mínimo, ya existente, de caracteres la solicitud sigue siendo 422. El bloque de cada adjunto termina con `--- end attachment ---`. Los demás controles (415/413, cifrado, páginas, zip) no cambian.

## Inconsistencias de la referencia y ajustes mínimos

- `cleaning/schemas.py` documenta una validación `sum(phases.amount) == total_amount` que no implementa; no se añade. Se elimina el decorador `@pa.check_input` sobre una función vacía (no tiene efecto funcional).
- Los comentarios de `pii/` y `persistence/models.py` hablan de mapeo «reversible» y «Art. 17»; el código no ofrece desseudonimización: la documentación local lo describe como seudonimización consistente, y `forget` solo elimina el mapping.
- `architecture.py` y `catalog/inspect.py` se declaran «CLI»; ambos se conservan como `python -m …`.
- `dependencies.get_parser_registry` y el README de la referencia mencionan parsers XLSX/DOCX/PDF de ingesta que no existen; no se implementan.
- `transcript_txt` identifica los documentos por el índice de línea (`turn-{idx}`), no por orden de turno; se conserva.
- El catálogo menciona «promover a include»; no hay operación que lo haga.

## Risks / Trade-offs

- El tamaño de la imagen crece (pandas, spaCy y el modelo). Se acepta: es necesario para el alcance.
- `Settings` exige hoy la clave del proveedor; las demos que importan `get_settings` heredan esa exigencia (se ejecutan con las claves ficticias del entorno de verificación o con `.env`).
- `PSEUDONYM_HASH_SALT` tiene el valor por defecto de la referencia (`change-me-in-prod`); debe cambiarse fuera de desarrollo (documentado en `.env.example`).
- Las pruebas de PostgreSQL real se omiten sin `TEST_DATABASE_URL`, como el resto del proyecto; la verificación las ejecuta contra el servicio `postgres` del Compose.
