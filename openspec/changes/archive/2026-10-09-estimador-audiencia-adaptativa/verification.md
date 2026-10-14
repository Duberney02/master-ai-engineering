# Verification

Todas las comprobaciones se ejecutaron en contenedores Docker (nada en el host). Fecha: 2026-10-09.

## Resultados

| Comprobación | Comando (contenedor) | Resultado |
|---|---|---|
| Pruebas de la API | `docker compose -f docker-compose.verify.yml run --rm api-test` | 731 passed, 7 skipped (PostgreSQL real: requiere `TEST_DATABASE_URL`); antes del cambio: 673 passed |
| Lint | `docker compose -f docker-compose.verify.yml run --rm api-lint` | All checks passed |
| OpenSpec | `docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict` | todos válidos |

## Trazabilidad

| Requisito | Pruebas |
|---|---|
| Perfiles y reglas ordenadas (prioridad, umbrales) | `tests/test_audience.py` |
| Audiencia explícita (`tier`) y valor inválido (422) | `tests/test_audience.py`, `tests/test_session_state_api.py::test_explicit_tier_prevails_and_is_kept_as_the_last_audience`, `::test_invalid_tier_is_a_422_and_does_not_touch_the_session` |
| Última audiencia/regla en la sesión (y no se modifica si falla) | `tests/test_session_state_api.py::test_failed_turn_keeps_the_previous_audience`, `::test_state_reflects_turns_metadata_and_last_audience` |
| Prompt v4 por audiencia y v1–v3 sin cambios | `tests/prompts/test_estimation_v4.py` |
| Versión del prompt conversacional | `tests/test_config.py`, `tests/test_session_state_api.py::test_prompt_version_defaults_to_the_configured_one_and_can_be_overridden` |
| `GET /sessions/{id}` | `tests/test_session_state_api.py` (sesión nueva, con actividad, anclas/resumen, 404, sin llamadas al LLM) |

## Limitaciones y observaciones

- Cambio de comportamiento documentado: el prompt por defecto de las sesiones pasa de `v3` a `v4`; `CONVERSATION_PROMPT_VERSION=v3` o `prompt_version=v3` lo conservan. `POST /estimate` sin sesión sigue en `v3`.
- `audience` y `audience_rule` son opcionales en el esquema de respuesta para que el cliente Streamlit (que valida con la misma clase) acepte servidores anteriores; el servidor siempre los rellena.
- Las listas de términos técnicos y regulatorios son heurísticas; `tier` permite corregir una clasificación errónea.
- Los clientes web (Rails, React) no exponen `tier` todavía.
