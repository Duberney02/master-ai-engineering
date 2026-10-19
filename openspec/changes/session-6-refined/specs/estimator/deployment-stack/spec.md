# Spec Delta

## ADDED Requirements

### Requirement: Migraciones y datos de ingesta en la API
La imagen de la API SHALL incluir el catálogo y el corpus de ejemplo (`data/`) y las migraciones Alembic (`alembic/`, `alembic.ini`), y su comando de arranque SHALL aplicar `alembic upgrade head` antes de iniciar el servidor cuando `DATABASE_URL` está definida; sin `DATABASE_URL` SHALL arrancar igualmente sin aplicar migraciones. El Compose raíz SHALL conservar la imagen de PostgreSQL y los volúmenes con nombre existentes, sin servicios adicionales para la ingesta.

#### Scenario: Arranque con base de datos
- **WHEN** arranca el servicio `estimador-cag` con PostgreSQL saludable
- **THEN** las tablas `ingestion_jobs` y `pseudonym_mappings` existen antes de que la API acepte solicitudes.

#### Scenario: Arranque sin base de datos
- **WHEN** se ejecuta la imagen sin `DATABASE_URL`
- **THEN** el contenedor llega a `healthy` sin aplicar migraciones.

#### Scenario: Datos preservados
- **WHEN** se reinicia el stack sin eliminar volúmenes
- **THEN** el historial de estimaciones y los trabajos de ingesta siguen disponibles.
