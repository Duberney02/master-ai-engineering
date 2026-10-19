# Spec Delta

## Purpose

Persistir el seguimiento de trabajos de ingesta y los mappings de seudónimos en el PostgreSQL existente, con migraciones versionadas, sin alterar el historial de estimaciones.

## ADDED Requirements

### Requirement: Tablas de ingesta
El sistema SHALL definir las tablas `ingestion_jobs` (`job_id` UUID, `source_name`, `status`, `documents_count`, `error_message` hasta 2048 caracteres, `started_at`, `finished_at`; índice `idx_jobs_status`) y `pseudonym_mappings` (`id`, `entity_type`, `original_hash`, `pseudonym`, `created_at`; restricción única `uq_mappings_entity_hash` sobre `(entity_type, original_hash)` e índice `idx_mappings_lookup`) con una base declarativa propia, distinta de la del historial. (Referencia: `app/persistence/models.py`.)

#### Scenario: Restricción única
- **WHEN** se inserta un segundo mapping con el mismo `(entity_type, original_hash)`
- **THEN** la base de datos lo rechaza.

#### Scenario: Historial intacto
- **WHEN** se aplican las migraciones sobre una base con la tabla `estimations`
- **THEN** `estimations` y sus datos no cambian.

### Requirement: Repositorios asíncronos
El sistema SHALL ofrecer `JobsRepository` (`create`, `get`, `mark_running`, `mark_completed`, `mark_failed`) y `MappingsRepository` (`lookup`, `lookup_or_create`, `forget`) sobre `AsyncSession`, sin exponer tipos del ORM. `lookup_or_create` SHALL insertar con resolución de conflicto sobre la restricción única y releer la fila ganadora cuando otro escritor se adelanta. `mark_failed` SHALL truncar el mensaje a 2048 caracteres. (Referencia: `app/persistence/repositories/jobs.py`, `mappings.py`.)

#### Scenario: Ciclo de vida del trabajo
- **WHEN** se crea un trabajo y se marca en ejecución y completado
- **THEN** su estado pasa de `pending` a `running` y `completed` con `documents_count` y `finished_at`.

#### Scenario: Inserciones concurrentes
- **WHEN** dos llamadas simultáneas piden el mismo `(entity_type, original_hash)`
- **THEN** ambas devuelven el mismo seudónimo y solo existe una fila.

### Requirement: Migraciones Alembic
El sistema SHALL incluir `alembic.ini`, `alembic/env.py` y la migración `0001_session6_initial` que crea ambas tablas con sus restricciones e índices y permite revertirlas. La URL SHALL leerse de la configuración (`DATABASE_URL`) y el entorno SHALL funcionar con el driver asíncrono. (Referencia: `alembic/`, `alembic.ini`.)

#### Scenario: Subida y bajada
- **WHEN** se ejecuta `alembic upgrade head` y después `alembic downgrade base`
- **THEN** las tablas se crean y se eliminan sin errores.

#### Scenario: Repetición
- **WHEN** se ejecuta `alembic upgrade head` dos veces
- **THEN** la segunda no cambia nada.
