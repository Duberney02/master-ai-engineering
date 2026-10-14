# Design

## Context

`ConversationHistory` guarda pares usuario/asistente y descarta los más antiguos al superar `max_turns`. `SessionEstimationService.estimate` genera con corrección automática, actualiza metadatos con una llamada adicional (que nunca falla la estimación) y confirma el turno con `Session.record_turn`. `LLMWrapper` aporta caché, reintentos, fallback y costes; `generate_from_messages` es el único punto de entrada multi-turno.

## Goals / Non-Goals

**Goals:** no perder compromisos relevantes ni el hilo de turnos antiguos; separar estructura, detección y política; mantener el LLM auxiliar opcional y degradable; reutilizar wrapper, loader y persistencia.

**Non-Goals:** persistir la memoria, resumir por tokens, restaurar sesiones tras un reinicio.

## Decisions

**Tres piezas separadas.** `ConversationHistory` (en `sessions.py`) solo conoce la estructura: turnos recientes, `summary`, `anchors` y una cola `retired` con los turnos que la ventana acaba de expulsar (acotada). `AnchorDetector` (`anchors.py`) decide si un par es ancla y devuelve los nombres de las reglas que coincidieron. `CompressionPolicy` (`compression.py`) orquesta: drena `retired`, separa anclas y no anclas, actualiza el resumen. Así la ventana no depende de ningún LLM y la política se prueba con dobles.

**Cuándo se detecta.** La política se ejecuta tras confirmar cada turno (`await policy.apply(session.history)`), pero detecta solo sobre los turnos que acaban de salir de la ventana: el coste de un detector LLM se paga una vez por turno retirado, no por cada mensaje. Un par ancla pasa a `history.anchors` (acotado a `MAX_ANCHORS = 8`, descartando la más antigua; sin duplicados); el resto se resume.

**Detector heurístico y LLM.** `HeuristicAnchorDetector` aplica reglas con nombre (`contract`, `closed_scope`, `agreed_budget`, `deadline`, `legal_regulatory`) con expresiones regulares sobre ambos mensajes del par, insensibles a mayúsculas y acentos. `LLMAnchorDetector` usa una plantilla auxiliar y una primitiva de generación estructurada (`generate_structured`: respuesta JSON validada con un modelo Pydantic y un reintento con mensaje de corrección); ante cualquier fallo recurre al heurístico, de modo que una caída del proveedor no pierde compromisos. `ANCHOR_DETECTION_MODE=heuristic|llm` (por defecto `heuristic`, sin coste). El registro (`anchor_detected`) incluye las reglas, nunca el texto.

**Resumidor.** `LLMSummarizer` renderiza la plantilla `summary` con `previous_summary` y los turnos retirados y devuelve un texto de como mucho `SUMMARY_MAX_CHARS` (2000) caracteres. El resumen se normaliza (sin `<`, `>` ni acentos graves, sin caracteres de control) porque se reinyecta en el prompt de sistema y procede de texto del usuario. Si falla o devuelve vacío, `CompressionPolicy` conserva el resumen anterior; los turnos retirados no vuelven a la ventana (se registra `summary_failed`). Alternativa descartada: reintentarlos en el turno siguiente; añade estado y crecimiento sin un beneficio claro frente a las anclas, que ya protegen lo crítico.

**Composición del contexto.** `compose_messages` (`context.py`) devuelve `[system + bloque de memoria] + pares ancla + turnos recientes + mensaje actual`. El resumen va dentro del mensaje de sistema, en un bloque `<conversation_summary>` declarado como datos (no instrucciones), igual que `<project_metadata>`; las anclas son pares reales usuario/asistente delante de la ventana (mantienen la alternancia de roles que exigen ambos proveedores). Las anclas no cuentan para `max_turns`: la ventana reciente sigue respetándolo. Sin resumen ni anclas la lista es idéntica a la actual, de modo que cachés y pruebas previas no cambian.

**Modelo por tarea.** `Settings.model_for(task)` devuelve el modelo de la tarea (`estimator`, `metadata`, `summary`, `critic`) o `effective_model()`; `generate_from_messages(..., model=)` lo propaga a `LLMWrapper`, cuya clave de caché ya incluye el modelo. El fallback conserva su propio modelo.

**Plantillas auxiliares versionadas.** `app/prompts/auxiliary/<tarea>/<vN>/{system,user}.j2` con el mismo estilo de `Environment` (`StrictUndefined`) y validación de nombres; `render_auxiliary_prompt(task, context, version="v1")`. Las plantillas de metadatos existentes no se mueven.

**Asociación en PostgreSQL.** `estimations` gana `conversation_id` (nulo, indexado) y `metadata_snapshot` (JSON nulo). `create_all` no altera tablas existentes, así que `_ensure_schema` añade las columnas que falten con `ALTER TABLE ... ADD COLUMN` tras inspeccionar la tabla (idempotente, válido en PostgreSQL y SQLite). `EstimationHistory.save(..., conversation_id=, metadata_snapshot=)` y `latest_for_conversation(id)` devuelven la última estimación asociada. Es la persistencia existente; la memoria del proceso sigue sin persistirse.

## Risks / Trade-offs

- Una llamada LLM extra por turno retirado (resumen) y, en modo `llm`, otra de detección: solo ocurren cuando la ventana se desborda y usan `SUMMARY_MODEL`, que puede ser un modelo barato.
- El resumen puede perder detalle: por eso los compromisos viven en anclas literales.
- Las heurísticas tienen falsos positivos/negativos; el modo `llm` los reduce a cambio de coste y latencia.
