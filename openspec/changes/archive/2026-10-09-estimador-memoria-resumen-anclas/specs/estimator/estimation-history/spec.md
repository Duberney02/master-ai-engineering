# Spec Delta

## Purpose

Asociar las estimaciones almacenadas con la conversación que las produjo.

## ADDED Requirements

### Requirement: Asociación con la conversación
Cada estimación realizada dentro de una sesión SHALL guardarse con el identificador de la conversación y un snapshot de los metadatos del proyecto vigentes tras el turno. El historial SHALL permitir consultar la última estimación asociada a una conversación. Las estimaciones sin sesión SHALL conservar ambos campos vacíos. Una base de datos creada antes de este cambio SHALL actualizarse añadiendo las columnas que falten sin perder datos. Esta asociación no persiste ni restaura la memoria del proceso.

#### Scenario: Estimación de sesión guardada
- **WHEN** se completa una estimación en una sesión con el historial habilitado
- **THEN** el registro contiene el `conversation_id` y los metadatos tras ese turno.

#### Scenario: Última estimación de una conversación
- **WHEN** una conversación tiene varias estimaciones guardadas
- **THEN** la consulta devuelve la más reciente con su snapshot de metadatos y devuelve nada para una conversación desconocida.

#### Scenario: Esquema anterior
- **WHEN** la tabla `estimations` existe sin las columnas nuevas
- **THEN** al iniciar se añaden y las filas previas siguen legibles con valores vacíos.
