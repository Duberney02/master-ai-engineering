# estimator/session-estimation Specification

## Purpose
Exponer por HTTP la creación de sesiones y las estimaciones con memoria conversacional y adjuntos, manteniendo el contrato de resultado ya existente.

## Requirements

### Requirement: Creación de sesiones
`POST /api/v1/sessions` SHALL crear una sesión vacía y devolver `{"session_id": "<UUID v4>"}` con estado 201.

#### Scenario: Crear sesión
- **WHEN** se hace `POST /api/v1/sessions`
- **THEN** la respuesta contiene un `session_id` con formato UUID v4 y dos creaciones devuelven identificadores distintos.

### Requirement: Estimación dentro de una sesión
`POST /api/v1/sessions/{session_id}/estimate` SHALL aceptar `multipart/form-data` con `transcript` y `attachments` opcionales, los parámetros tipados `project_type`, `detail_level`, `output_format` y `reference_projects` (JSON), y `prompt_version` (por defecto la versión por defecto). SHALL aplicar los guardrails de entrada al texto combinado, enviar al LLM los mensajes de la sesión con su ventana, validar la respuesta con el esquema y las reglas de negocio existentes, con la misma corrección automática, y devolver el resultado validado junto con los `project_metadata` actualizados y el número de turnos. Tras una estimación válida SHALL añadir el turno al historial y actualizar los metadatos; una estimación fallida SHALL NOT modificar la sesión. Las peticiones concurrentes de una misma sesión SHALL procesarse una tras otra. El texto combinado SHALL respetar los límites de la solicitud estructurada.

#### Scenario: Estimación válida
- **WHEN** se envía una transcripción a una sesión existente
- **THEN** la respuesta incluye `result` conforme al esquema de estimación, `prompt_version`, `project_metadata` y `turn_count` igual a 1.

#### Scenario: Adjunto que influye
- **WHEN** se adjunta un PDF cuyo contenido se menciona en la estimación
- **THEN** el mensaje enviado al LLM contiene el texto del PDF tras su separador y el resultado refleja ese contenido.

#### Scenario: Sesión inexistente
- **WHEN** el identificador no corresponde a una sesión
- **THEN** la respuesta es 404.

#### Scenario: Fallo del LLM
- **WHEN** el modelo no devuelve una estimación válida tras los intentos configurados
- **THEN** la respuesta es 502 y el historial y los metadatos de la sesión no cambian.

#### Scenario: Entrada rechazada
- **WHEN** el texto combinado incumple un guardrail
- **THEN** la respuesta es 400 con `reason` y `message` y la sesión no cambia.

#### Scenario: Texto demasiado corto o sin contenido
- **WHEN** el texto combinado tiene menos de 20 caracteres
- **THEN** la respuesta es 422.

#### Scenario: Ocho turnos
- **WHEN** se realizan ocho estimaciones en la misma sesión
- **THEN** en cada llamada al LLM los mensajes enviados respetan la ventana de turnos configurada.
