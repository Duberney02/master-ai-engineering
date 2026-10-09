# Tasks

Todas las verificaciones se ejecutan en contenedores Docker (`docker compose -f docker-compose.verify.yml ...`).

## 1. Configuración y plantillas

- [x] 1.1 Añadir `estimator_model`, `metadata_model`, `summary_model`, `critic_model`, `anchor_detection_mode` y `Settings.model_for(task)` en `config.py`, y documentarlos en `.env.example`; verificar con `tests/test_config.py`.
- [x] 1.2 Añadir el parámetro `model` a `generate_from_messages` y usarlo en la extracción de metadatos; verificar con `tests/test_llm_messages.py`.
- [x] 1.3 Crear `prompts/auxiliary/{summary,anchors}/v1` y `render_auxiliary_prompt` en el loader; verificar con `tests/prompts/test_auxiliary.py`.

## 2. Memoria

- [x] 2.1 Extender `ConversationHistory` (resumen, anclas, cola `retired`) y `Session`; verificar con `tests/test_sessions.py`.
- [x] 2.2 Crear `structured.py`, `anchors.py` (reglas heurísticas, detector LLM) y `summarizer.py`; verificar con `tests/test_anchors.py` y `tests/test_summarizer.py`.
- [x] 2.3 Crear `compression.py` y `context.py` (política tras cada turno, composición del contexto); verificar con `tests/test_compression.py` y `tests/test_context.py` (conserva el resumen ante fallos, anclas fuera de la ventana, orden de mensajes).
- [x] 2.4 Integrar política y composición en `SessionEstimationService`; verificar con `tests/test_sessions_api.py` y la suite completa.

## 3. Persistencia

- [x] 3.1 Añadir `conversation_id`, `metadata_snapshot`, migración idempotente y `latest_for_conversation`; guardar desde el router de sesiones; verificar con `tests/test_history.py`.

## 4. Cierre

- [x] 4.1 Actualizar README y `.env.example`; ejecutar `ruff`, `pytest` y `openspec validate --all --strict` en contenedores y registrar el resultado en `verification.md`.
