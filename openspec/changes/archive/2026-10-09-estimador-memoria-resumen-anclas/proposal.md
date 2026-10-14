# Proposal

## Why

La memoria conversacional actual descarta sin más los turnos que salen de la ventana (6 por defecto): un presupuesto acordado, un contrato o una restricción legal mencionados en el turno 1 desaparecen en el turno 8 y el modelo vuelve a estimar sin ellos. Además todas las llamadas auxiliares (estimador, metadatos) comparten el mismo modelo y las estimaciones guardadas en PostgreSQL no se relacionan con la conversación que las produjo.

## What Changes

- **Resumen acumulativo**: los turnos que salen de la ventana reciente se combinan con el resumen anterior mediante una llamada auxiliar al LLM. Si el resumidor falla, se conserva el resumen anterior.
- **Anclas de memoria**: los pares usuario/asistente con compromisos relevantes (contratos, alcance cerrado, presupuestos acordados, fechas límite, restricciones legales o regulatorias) se conservan literalmente fuera de la ventana.
- **Separación de responsabilidades**: estructura del historial (`ConversationHistory`), detector de anclas (`AnchorDetector`: heurístico o LLM) y política de compresión (`CompressionPolicy`), que se ejecuta tras completar cada turno y registra las reglas que identificaron cada ancla.
- **Composición del contexto**: los mensajes del estimador se construyen con el prompt de sistema actualizado, el resumen acumulativo, las anclas, los turnos recientes y el mensaje actual.
- **Configuración por tarea**: `ESTIMATOR_MODEL`, `METADATA_MODEL`, `SUMMARY_MODEL` y `CRITIC_MODEL` (este último lo consume el cambio `estimador-actor-critic-boss`), `ANCHOR_DETECTION_MODE`.
- **Plantillas auxiliares versionadas** (Jinja2, `StrictUndefined`, mismo loader) para resumen y detección de anclas con LLM.
- **Asociación conversación–estimaciones**: cada estimación de una sesión se guarda con su `conversation_id` y el último snapshot de metadatos, y puede consultarse la última estimación de una conversación.

**No incluido**: persistir o restaurar la memoria del proceso (la sesión sigue siendo volátil), búsqueda semántica sobre el historial, resumen por tokens (se resume por turnos), cambios en los clientes web.

## Capabilities

### New Capabilities
- `estimator/conversation-memory`: resumen acumulativo, anclas, política de compresión y composición del contexto.
- `estimator/task-model-configuration`: modelo por tarea y modo de detección de anclas.

### Modified Capabilities
- `estimator/estimation-history`: asociación con la conversación y snapshot de metadatos.
- `estimator/prompt-templates`: plantillas auxiliares versionadas.

## Impact

- Código: `app/services/{sessions,anchors,compression,summarizer,context}.py` (nuevos salvo `sessions`), `session_estimation.py`, `llm_service.py` (parámetro `model`), `history.py`, `config.py`, `prompts/loader.py` y `prompts/auxiliary/`, `routers/sessions.py`.
- Base de datos: dos columnas nulas nuevas en `estimations` (`conversation_id`, `metadata_snapshot`), añadidas de forma idempotente al arrancar.
- API: aditiva. Los contratos públicos, guardrails, validaciones, métricas, fallback y límites de sesiones y adjuntos no cambian.
- Pruebas con dobles de los proveedores; verificación en contenedores Docker.
