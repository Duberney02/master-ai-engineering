# Spec Delta

## Purpose

Exponer la audiencia en las estimaciones de sesión y permitir consultar el estado de una sesión.

## ADDED Requirements

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
