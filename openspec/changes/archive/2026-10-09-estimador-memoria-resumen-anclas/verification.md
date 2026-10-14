# Verification

Todas las comprobaciones se ejecutaron en contenedores Docker (nada en el host). Fecha: 2026-10-09. Los servicios están en `docker-compose.verify.yml`.

## Resultados

| Comprobación | Comando (contenedor) | Resultado |
|---|---|---|
| Línea base antes del cambio | `docker compose -f docker-compose.verify.yml run --rm api-test` | 612 passed, 7 skipped |
| Pruebas de la API | `docker compose -f docker-compose.verify.yml run --rm api-test` | 673 passed, 7 skipped (PostgreSQL real: requiere `TEST_DATABASE_URL`) |
| Lint | `docker compose -f docker-compose.verify.yml run --rm api-lint` | All checks passed |
| OpenSpec | `docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict` | todos válidos |

## Trazabilidad

| Requisito | Pruebas |
|---|---|
| Resumen acumulativo (primer desbordamiento, acumulado, fallo) | `tests/test_compression.py`, `tests/test_memory_api.py::test_turns_leaving_the_window_are_summarized_and_the_summary_reaches_the_next_estimate`, `::test_summarizer_failure_does_not_fail_the_estimate_and_keeps_the_previous_summary` |
| Anclas de memoria (presupuesto, contrato, alcance, plazo, legal; límite) | `tests/test_anchors.py`, `tests/test_compression.py`, `tests/test_memory_api.py::test_commitment_turn_is_kept_as_an_anchor_after_leaving_the_window` |
| Separación estructura / detector / política; reglas registradas | `tests/test_compression.py::test_anchor_detection_is_logged_with_rule_names_and_not_the_text`, `tests/test_anchors.py` (detector LLM y respaldo heurístico) |
| Composición del contexto | `tests/test_context.py` |
| Modelo por tarea y modo de anclas | `tests/test_config.py`, `tests/test_anchors.py::test_llm_detector_returns_the_rules_chosen_by_the_model`, `tests/test_compression.py::test_llm_summarizer_uses_its_template_model_and_normalizes_the_result` |
| Plantillas auxiliares versionadas | `tests/prompts/test_auxiliary.py` |
| Asociación con la conversación y migración aditiva | `tests/test_history_conversation.py`, `tests/test_memory_api.py::test_estimations_are_stored_with_their_conversation_and_metadata_snapshot` |

## Limitaciones y observaciones

- La memoria (resumen, anclas) vive en el proceso, como el resto de la sesión: no se persiste ni se restaura tras un reinicio. Solo se persisten las estimaciones y su snapshot de metadatos.
- Los turnos retirados cuyo resumen falla no se reintentan; los compromisos quedan protegidos por las anclas.
- El detector heurístico solo evalúa el mensaje del usuario; el modo `llm` evalúa ambos mensajes del par.
- La consulta de la última estimación de una conversación está disponible en `EstimationHistory.latest_for_conversation`; no se expone un endpoint nuevo.
