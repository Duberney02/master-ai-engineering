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

### Requirement: Audiencia en la estimación de sesión
`POST /api/v1/sessions/{session_id}/estimate` SHALL aceptar el campo opcional `tier` y SHALL incluir en la respuesta la audiencia aplicada y el nombre de la regla (`audience`, `audience_rule`). El campo `prompt_version` SHALL ser opcional y, si falta, SHALL usarse `CONVERSATION_PROMPT_VERSION` (por defecto `v4`). Los demás campos del contrato SHALL conservarse.

#### Scenario: Audiencia en la respuesta
- **WHEN** se completa una estimación
- **THEN** la respuesta incluye `audience` y `audience_rule` y el prompt de sistema enviado al LLM contiene el enfoque de esa audiencia.

#### Scenario: Prompt por defecto configurable
- **WHEN** no se envía `prompt_version` y `CONVERSATION_PROMPT_VERSION=v3`
- **THEN** la respuesta indica `prompt_version` igual a `v3`.

### Requirement: Consulta del estado de la sesión
`GET /api/v1/sessions/{session_id}` SHALL devolver el identificador, la cantidad de mensajes recientes, el máximo de turnos, los metadatos del proyecto, la cantidad de mensajes anclados, la longitud del resumen y la última audiencia y regla, sin ejecutar ninguna estimación ni llamar al LLM. Una sesión desconocida o caducada SHALL responder 404.

#### Scenario: Sesión nueva
- **WHEN** se consulta una sesión sin turnos
- **THEN** la respuesta indica cero mensajes recientes y anclados, resumen de longitud cero y audiencia y regla nulas.

#### Scenario: Sesión con actividad
- **WHEN** se consulta una sesión tras dos turnos
- **THEN** indica cuatro mensajes recientes, los metadatos vigentes y la última audiencia y regla.

#### Scenario: Sesión inexistente
- **WHEN** el identificador no corresponde a una sesión
- **THEN** la respuesta es 404.

### Requirement: Endpoint de estimación revisada
`POST /api/v1/sessions/{session_id}/estimate-acb` SHALL aceptar el mismo contrato `multipart/form-data` que `POST /sessions/{session_id}/estimate`, incluido el `tier` opcional, y SHALL ejecutar el flujo Actor–Critic–Boss. Su respuesta SHALL contener los mismos campos que la del endpoint conversacional más la traza de auditoría (`audit_trace`). SHALL aplicar los mismos guardrails, validaciones, límites de adjuntos y errores (404, 400, 413, 415, 422, 502), guardar en el historial únicamente el resultado final y registrar un solo turno en la sesión. El endpoint conversacional SHALL conservar su contrato y comportamiento.

#### Scenario: Estimación revisada
- **WHEN** se envía una transcripción válida a una sesión existente
- **THEN** la respuesta incluye `result`, `project_metadata`, `turn_count` igual a 1 y `audit_trace` con al menos una iteración.

#### Scenario: Mismos errores que el endpoint normal
- **WHEN** la sesión no existe, el `tier` es inválido o el texto incumple un guardrail
- **THEN** las respuestas son 404, 422 y 400, respectivamente, sin llamar al LLM.

#### Scenario: Endpoint normal intacto
- **WHEN** se usa `POST /sessions/{id}/estimate`
- **THEN** la respuesta no incluye `audit_trace` y no se realizan llamadas del crítico.

#### Scenario: Historial
- **WHEN** el flujo regenera dos veces
- **THEN** se guarda una única estimación en el historial con el resultado final.
