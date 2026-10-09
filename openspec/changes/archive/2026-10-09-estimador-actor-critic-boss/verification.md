# Verification

Todas las comprobaciones se ejecutaron en contenedores Docker (nada en el host). Fecha: 2026-10-09.

## Resultados

| Comprobación | Comando (contenedor) | Resultado |
|---|---|---|
| Pruebas de la API | `docker compose -f docker-compose.verify.yml run --rm api-test` | 810 passed, 7 skipped (PostgreSQL real: requiere `TEST_DATABASE_URL`); antes del cambio: 731 passed |
| Refactor `draft`/`commit` sin regresión | misma suite, incluidas `tests/test_sessions_api.py`, `tests/test_memory_api.py` y `tests/test_session_state_api.py` | pasan sin cambios en su comportamiento |
| Lint | `docker compose -f docker-compose.verify.yml run --rm api-lint` | All checks passed |
| OpenSpec | `docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict` | todos válidos |

## Trazabilidad

| Requisito | Pruebas |
|---|---|
| Contrato del crítico (enums, `needs_iteration`, `reject`, confianza, normalización) | `tests/test_critic_contract.py` |
| Servicio crítico (entradas, modelo, reintento, error, sin sesión) | `tests/test_critic_service.py` |
| Plantillas del crítico y del feedback | `tests/test_critic_service.py` (prompt en español, datos delimitados, mensaje de feedback, variables obligatorias) |
| Decisiones del Boss en código | `tests/test_boss.py` |
| Orquestación, límite de iteraciones, crítico caído, fallo del actor | `tests/test_acb.py` |
| Feedback en la regeneración y único turno final | `tests/test_acb.py::test_regenerates_with_the_feedback_and_accepts_the_second_draft`, `::test_only_the_final_result_is_stored_as_a_single_turn` |
| Traza de auditoría | `tests/test_acb.py`, `tests/test_acb_api.py::test_accepted_estimate_has_the_normal_contract_plus_the_audit_trace` |
| Endpoint `estimate-acb` (contrato, errores, adjuntos, historial único, endpoint normal intacto) | `tests/test_acb_api.py` |
| `BOSS_MAX_ITERATIONS` | `tests/test_config.py`, `tests/test_acb.py::test_default_max_iterations_comes_from_the_settings` |

## Limitaciones y observaciones

- El flujo ACB no tiene versión en streaming y no se ha integrado en los clientes web.
- Cada estimación ACB cuesta como mínimo una llamada de revisión adicional; las completions de borradores previos y de revisiones se suman a las métricas del turno.
- Si el crítico no puede revisar, se devuelve el borrador con reservas (`critic_error` en la traza) en lugar de fallar.
- Un crítico con el mismo modelo que el actor comparte sus sesgos; `CRITIC_MODEL` permite separarlos.
