# Tasks

Todas las verificaciones se ejecutan en contenedores Docker, nunca en el host.

## 1. Sesiones, metadatos y plantillas

- [x] 1.1 Añadir `pypdf` y `python-docx` a `estimador-cag/pyproject.toml`, regenerar `uv.lock` en un contenedor y verificar que `docker build` de la imagen runtime termina sin errores.
- [x] 1.2 Crear `app/services/sessions.py` (`ConversationHistory`, `ProjectMetadata`, `Session`, `SessionStore`) con docstrings sobre la volatilidad, y ajustes `SESSION_MAX_TURNS`, `SESSION_TTL_SECONDS` y `SESSION_MAX_COUNT` en `config.py`; verificar con `tests/test_sessions.py` (ventana, pares completos, system prompt conservado, `to_messages_list`, normalización de metadatos, TTL y tope).
- [x] 1.3 Añadir `project_metadata.j2`, incluirlo en los `system.j2` de v1–v3 y las plantillas `sessions/metadata_system.j2` y `metadata_user.j2`, y extender `loader.py` con `project_metadata` opcional y el render de extracción; verificar con `tests/prompts/test_project_metadata.py` que sin metadatos los prompts no cambian y con metadatos vacíos o completos el bloque aparece.

## 2. Adjuntos y llamada multi-turno

- [x] 2.1 Crear `app/services/attachments.py` (extracción PDF/DOCX local, separadores, saneo de nombre, límites y errores HTTP); verificar con `tests/test_attachments.py` usando PDF y DOCX generados en la prueba (texto, tablas, varios archivos, nombre malicioso, tipo falso, vacío, cifrado, tamaño).
- [x] 2.2 Permitir listas de mensajes en `llm_service`/`llm_wrapper` y añadir `generate_from_messages`; verificar con `tests/test_llm_messages.py` (OpenAI y Anthropic reciben system y turnos correctos, la caché distingue historiales) y que `tests/test_llm_service.py` y `tests/test_resilient_generation.py` siguen pasando.

## 3. Servicio y endpoints de sesión

- [x] 3.1 Crear `schemas/sessions.py`, `services/session_estimation.py` y `routers/sessions.py` y registrarlos en `main.py`; verificar con `tests/test_sessions_api.py` (crear sesión UUID v4, 404, 422, 400 de guardrails, 413/415, 502 sin modificar la sesión).
- [x] 3.2 Escribir las pruebas de integración con `httpx.AsyncClient`: dos peticiones actualizan `project_metadata`, un PDF adjunto influye en la estimación y tras ocho turnos el historial enviado respeta `MAX_TURNS`; verificar que pasan en el contenedor de pruebas.

## 4. Clientes

- [x] 4.1 Adaptar Streamlit (`streamlit_client.py`, `streamlit_app.py`): sesión al cargar, transcripción y adjuntos múltiples, panel de metadatos y «Nueva conversación»; actualizar `tests/test_streamlit_app.py` y verificar con la suite en el contenedor.
- [x] 4.2 Adaptar la web React: cliente `estimatorApi`, contexto de conversación, formulario con adjuntos, panel de metadatos y «Nueva conversación»; actualizar las pruebas Vitest y verificar `npm test` y `npm run build` en un contenedor Node.
- [x] 4.3 Adaptar la web Rails: `EstimatorApi` multipart, formulario con adjuntos, panel de metadatos y «Nueva conversación»; actualizar las pruebas Minitest y verificar `bin/rails test` en un contenedor Ruby.

## 5. Documentación e integración

- [x] 5.1 Actualizar `estimador-cag/README.md` y el README raíz (arranque, tests en Docker, sesiones, estrategia de adjuntos frente a envío directo, método de extracción de metadatos frente a heurística, volatilidad y límites) y el workflow de CI si procede; verificar que los comandos documentados se ejecutan tal cual.
- [x] 5.2 Ejecutar `openspec validate --all --strict` y la suite completa de la API en contenedor; verificar que no hay fallos nuevos y registrar el resultado en `verification.md`.
