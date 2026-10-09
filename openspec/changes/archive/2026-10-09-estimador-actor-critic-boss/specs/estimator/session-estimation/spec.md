# Spec Delta

## Purpose

Exponer la estimación revisada por el crítico sin alterar el endpoint conversacional.

## ADDED Requirements

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
