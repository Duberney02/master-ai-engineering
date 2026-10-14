# Tasks

Todas las verificaciones se ejecutan en contenedores Docker (`docker compose -f docker-compose.verify.yml ...`).

## 1. Resolución de audiencia

- [x] 1.1 Crear `app/services/audience.py` (perfiles, reglas ordenadas, `resolve_audience`) reutilizando el patrón legal del detector de anclas; verificar con `tests/test_audience.py` (cada regla, orden de prioridad, `tier` explícito).
- [x] 1.2 Añadir `audience` y `audience_rule` a `Session` y actualizarlos solo al confirmar el turno; verificar con `tests/test_audience.py` y `tests/test_sessions_api.py`.

## 2. Prompt v4

- [x] 2.1 Crear `prompts/estimation/v4/{system,user,examples}.j2` con la sección de audiencia y el parámetro `audience` en `render_system_prompt`; verificar con `tests/prompts/test_estimation_v4.py` (enfoque por perfil, contrato, `v1`–`v3` sin cambios).
- [x] 2.2 Añadir `CONVERSATION_PROMPT_VERSION` a `config.py` y `.env.example`; verificar con `tests/test_config.py`.

## 3. API

- [x] 3.1 Añadir `tier`, `audience` y `audience_rule` a `POST /sessions/{id}/estimate`, el esquema `SessionState` y `GET /sessions/{id}`; verificar con `tests/test_session_state_api.py` (valores, 404, 422 por `tier`, versión por defecto).

## 4. Cierre

- [x] 4.1 Actualizar README; ejecutar `ruff`, `pytest` y `openspec validate --all --strict` en contenedores y registrar el resultado en `verification.md`.
