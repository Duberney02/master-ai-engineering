# Proposal

## Why

Una misma estimación se redacta igual para una directiva que quiere riesgos y síntesis, para quien gestiona el proyecto y necesita hitos y dependencias, o para ingeniería, que busca tecnologías e integraciones. Hoy el prompt de sistema no distingue la audiencia y el cliente no puede ver ni controlar cómo se ha decidido el enfoque. Tampoco hay forma de consultar el estado de una sesión sin lanzar otra estimación.

## What Changes

- **Perfiles de audiencia** `executive`, `pm`, `developer` y `default`, resueltos con reglas ordenadas sobre la transcripción y los metadatos: confidencialidad o contexto regulatorio → `executive`; varios términos técnicos → `developer`; equipo pequeño en los metadatos → `pm`; sin coincidencias → `default`.
- **Audiencia explícita**: `tier` opcional en `POST /api/v1/sessions/{id}/estimate`; prevalece sobre las reglas. La sesión conserva la última audiencia resuelta y el nombre de la regla (`explicit`, `confidentiality_or_regulatory`, `technical_terms`, `small_team` o `no_match`), que también se devuelven en la respuesta.
- **Prompt `v4`**: nueva versión de la plantilla de estimación que ajusta el enfoque a la audiencia (dirección: riesgos, síntesis y lenguaje accesible; gestión: hitos, entregables y dependencias; ingeniería: tecnologías, integraciones y supuestos técnicos), en español y con el mismo contrato estructurado.
- **Versión del prompt conversacional configurable**: `CONVERSATION_PROMPT_VERSION` (por defecto `v4`) se usa cuando la solicitud no envía `prompt_version`.
- **Consulta del estado**: `GET /api/v1/sessions/{id}` devuelve identificador, mensajes recientes, máximo de turnos, metadatos, mensajes anclados, longitud del resumen y última audiencia/regla.

**No incluido**: cambiar `v1`–`v3`, audiencias personalizadas por el cliente, persistir la audiencia, cambios en los clientes web.

## Capabilities

### New Capabilities
- `estimator/audience-resolution`: perfiles, reglas ordenadas, selección explícita y estado de la sesión.

### Modified Capabilities
- `estimator/prompt-templates`: versión `v4` adaptada a la audiencia.
- `estimator/session-estimation`: parámetro `tier`, audiencia en la respuesta y `GET /sessions/{id}`.
- `estimator/task-model-configuration`: versión del prompt conversacional.

## Impact

- Código: `app/services/audience.py` (nuevo), `session_estimation.py`, `sessions.py`, `prompts/loader.py`, `prompts/estimation/v4/`, `schemas/sessions.py`, `routers/sessions.py`, `config.py`.
- API aditiva: `tier` opcional, campos `audience` y `audience_rule` nuevos en la respuesta y un endpoint GET nuevo. El prompt por defecto de las sesiones pasa de `v3` a `v4`; se puede fijar `CONVERSATION_PROMPT_VERSION=v3` o enviar `prompt_version=v3` para conservar el anterior.
- Pruebas con dobles de los proveedores; verificación en contenedores Docker.
