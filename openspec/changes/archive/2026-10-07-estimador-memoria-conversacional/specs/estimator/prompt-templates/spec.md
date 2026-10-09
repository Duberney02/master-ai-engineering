# Spec Delta

## ADDED Requirements

### Requirement: Bloque de metadatos del proyecto
Las plantillas de sistema SHALL admitir un bloque `<project_metadata>` opcional con los hechos conocidos del proyecto. Con metadatos presentes (aunque vacíos) el bloque SHALL renderizarse indicando que su contenido son datos y no instrucciones; sin metadatos SHALL omitirse y el prompt SHALL ser idéntico al anterior.

#### Scenario: Sin sesión
- **WHEN** se renderiza una solicitud sin metadatos
- **THEN** el prompt de sistema no contiene `<project_metadata>`.

#### Scenario: Con metadatos vacíos
- **WHEN** se renderiza con metadatos vacíos
- **THEN** contiene el bloque sin hechos conocidos.

#### Scenario: Con metadatos
- **WHEN** se renderiza con nombre, equipo y tecnologías
- **THEN** el bloque los contiene.
