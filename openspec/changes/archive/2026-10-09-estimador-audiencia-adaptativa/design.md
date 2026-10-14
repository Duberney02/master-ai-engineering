# Design

## Context

`render_system_prompt` recibe la solicitud, la versión y los metadatos. `SessionEstimationService.estimate` construye los mensajes con `Session.to_messages_list`. La sesión guarda historial, resumen, anclas y metadatos.

## Goals / Non-Goals

**Goals:** adaptar el enfoque del prompt a la audiencia de forma determinista y explicable; permitir forzarla; exponer el estado de la sesión.

**Non-Goals:** clasificación con LLM de la audiencia, audiencias definidas por el cliente.

## Decisions

**Reglas ordenadas y deterministas** (`audience.py`). Cada `AudienceRule` tiene nombre, audiencia y un predicado sobre un `AudienceContext(transcript, metadata)`. Se evalúan en orden y gana la primera que coincide: (1) `confidentiality_or_regulatory` → `executive`, reutilizando el patrón `legal_regulatory` del detector de anclas para no duplicar vocabulario; (2) `technical_terms` → `developer`, con al menos 3 términos técnicos distintos entre la transcripción y las tecnologías de los metadatos (`TECH_TERMS_THRESHOLD`); (3) `small_team` → `pm`, con `assumed_team_size <= 5`; si ninguna coincide, `no_match` → `default`. El orden refleja la prioridad pedida: un contexto confidencial o regulatorio manda sobre el perfil técnico. Se descartó clasificar con un LLM: añadiría una llamada por turno y un resultado no reproducible.

**Transcripción para las reglas.** Es el texto del turno actual más lo que la sesión recuerda (resumen, anclas y turnos recientes del usuario): una restricción regulatoria del turno 1 sigue influyendo cuando el turno 9 ya no la repite.

**`tier` explícito prevalece.** Si llega, la resolución es `(tier, "explicit")` sin evaluar reglas. `default` también puede forzarse. Un valor desconocido responde 422 antes de llamar al LLM. La sesión solo actualiza `audience` y `audience_rule` cuando el turno se completa (como historial y metadatos), de modo que un fallo no la deja a medias.

**Prompt `v4`.** Copia de `v3` más una sección «Audiencia» condicionada a la variable `audience` (`StrictUndefined`: el cargador siempre la proporciona, con `default` si no hay sesión). Los tres perfiles solo cambian el enfoque pedido, no el contrato JSON, que sigue incluido desde `output_contract.j2`. `v1`–`v3` no se modifican y el cargador sigue produciendo exactamente el mismo texto para ellas.

**Versión por defecto de las sesiones.** `CONVERSATION_PROMPT_VERSION` (por defecto `v4`) se aplica cuando la solicitud no trae `prompt_version`; el campo del formulario pasa a ser opcional. `POST /estimate` (sin sesión) conserva `v3` por defecto.

**`GET /sessions/{id}`.** Devuelve `SessionState`: mensajes recientes (`2 × turnos`), `max_turns`, metadatos, mensajes anclados (`2 × anclas`), `summary_length`, `last_audience` y `last_audience_rule` (nulos antes del primer turno). Usa `SessionStore.get`, así que renueva la caducidad como cualquier acceso.

## Risks / Trade-offs

- Las listas de términos son heurísticas: pueden clasificar mal un texto atípico; `tier` permite corregirlo y el nombre de la regla hace la decisión auditable.
- Cambiar el prompt por defecto de las sesiones altera el texto enviado al modelo; se puede revertir con una variable de entorno.
