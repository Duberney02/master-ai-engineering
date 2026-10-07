# Proposal

## Why

Cada estimación es hoy independiente: el servicio no recuerda lo hablado en turnos anteriores ni los hechos del proyecto (nombre, equipo, tecnologías, alcance), y las transcripciones solo se admiten como texto pegado. En una conversación real con el cliente la información llega por partes y en documentos (PDF, Word); sin memoria conversacional cada petición obliga a repetir el contexto y los resultados no son coherentes entre sí.

## What Changes

- Nuevo módulo de sesiones en memoria del proceso: historial con ventana deslizante (`MAX_TURNS = 6` por defecto, configurable), metadatos del proyecto (`ProjectMetadata`) y almacén por `session_id` (UUID v4). La volatilidad (se pierde al reiniciar, no se comparte entre procesos) se acepta y se documenta.
- `POST /api/v1/sessions` crea una sesión vacía y `POST /api/v1/sessions/{session_id}/estimate` (multipart: `transcript`, `attachments`, parámetros tipados) devuelve una estimación validada con el esquema existente y actualiza historial y metadatos.
- Los adjuntos PDF y Word se procesan con extracción local (pypdf y python-docx) y se incorporan al texto con separadores `--- attachment: <nombre> ---`.
- Los prompts de sistema incluyen un bloque `<project_metadata>` con los hechos conocidos (vacío en la primera llamada); tras cada respuesta una llamada adicional al LLM con un prompt específico devuelve JSON validado con los metadatos actualizados.
- `Session.to_messages_list()` genera los mensajes enviados al LLM regenerando el system prompt con los metadatos actuales y respetando la ventana.
- Los clientes (Streamlit, Rails y React) crean y conservan el `session_id`, permiten transcripción más archivos múltiples, muestran `project_metadata` y ofrecen «Nueva conversación».
- README: arranque, tests, estrategia de adjuntos (extracción local frente a envío directo al proveedor) y método de extracción de metadatos (llamada LLM frente a heurística con regex).

**No incluido**: persistencia, resumen acumulativo, memoria híbrida con anclas, tier dinámico, búsqueda web, function calling para BBDD ni Actor-Critic-Boss.

## Capabilities

### New Capabilities
- `estimator/conversation-sessions`: sesiones en memoria con historial de ventana deslizante y ciclo de vida (crear, caducar, no encontrada).
- `estimator/attachment-extraction`: extracción local de texto de PDF y Word con separadores, límites y errores saneados.
- `estimator/project-metadata`: hechos conocidos del proyecto, inyección en el system prompt y actualización con una llamada adicional al LLM.
- `estimator/session-estimation`: endpoints `POST /sessions` y `POST /sessions/{id}/estimate`.

### Modified Capabilities
- `estimator/prompt-templates`: el prompt de sistema admite un bloque `<project_metadata>` opcional.
- `estimator/structured-estimation`: el cliente Streamlit trabaja con sesiones, adjuntos y panel de metadatos.
- `estimator/web-client`: el formulario Rails trabaja con sesiones, adjuntos y panel de metadatos.
- `estimator/web-react-client`: el formulario React trabaja con sesiones, adjuntos y panel de metadatos.

## Impact

- Código: `estimador-cag/app/services/{sessions,attachments,session_estimation}.py`, `routers/sessions.py`, `schemas/sessions.py`, `prompts/loader.py` y plantillas Jinja2, `llm_service.py` (lista de mensajes), `config.py`, `main.py`, `streamlit_*`, `estimator-web/` y `estimator-web-react/`.
- Dependencias nuevas en la API: `pypdf`, `python-docx`, `python-multipart` (ya incluida en `fastapi[standard]`).
- API aditiva: los endpoints existentes no cambian. Los clientes pasan a usar el endpoint de sesión.
- Pruebas: integración con `pytest` y `httpx.AsyncClient`; validaciones ejecutadas en contenedores Docker.
