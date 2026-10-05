# Tasks

## 1. Base

- [x] 1.1 Declarar `jinja2` en pyproject y actualizar uv.lock; verificar con `uv sync` y registrar la línea base de `uv run pytest -q`.

## 2. Contrato y plantillas

- [x] 2.1 Crear `EstimationRequest`, `EstimationResponse`, enums y `ReferenceProject` en `app/schemas/project_estimation.py` y reexportarlos en `app/schemas`; verificar con pruebas de validación (límites de longitud, enums, referencias opcionales).
- [x] 2.2 Crear `app/prompts/loader.py` con `render_estimation_prompt(request, version="v1")`, descubrimiento de versiones, rechazo de versiones inválidas y log `prompt_rendered` con hash; verificar con pruebas de versión desconocida, traversal, StrictUndefined y evento de log sin la descripción.
- [x] 2.3 Escribir las plantillas `v1` (`system.j2`, `user.j2` y `examples.j2` con tres ejemplos), con bloques condicionales por formato y detalle y el recorrido de `reference_projects`; verificar con `tests/prompts/test_estimation_v1.py` (descripción literal, `confidence_pct` según formato, asunciones por fase según detalle, referencias).
- [x] 2.4 Escribir `v2` con tono y ejemplos distintos; verificar con `tests/prompts/test_estimation_v2.py` que difiere de v1 y respeta formato y detalle.

## 3. Endpoint

- [x] 3.1 Montar el flujo de transcripción en `/api/v1/transcription` y crear el router estructurado en `/api/v1/estimate` con `?prompt_version`, mensajes separados vía el wrapper existente y `EstimationResponse`; verificar con pruebas de 200, 422 (entrada y versión), v2, mensajes system/user separados y error saneado del proveedor, y actualizar las pruebas existentes a las rutas nuevas.
- [x] 3.2 Actualizar la demo SSE, README, docs y Postman/curls a las rutas y el contrato nuevos; verificar con una búsqueda de rutas antiguas (la demo HTML no tiene prueba automatizada).

## 4. Cliente

- [x] 4.1 Sustituir el chat de Streamlit por un formulario `st.form` que construye `EstimationRequest`; verificar con AppTest (envío válido, validación sin HTTP, error de red saneado) y con pruebas unitarias del cliente HTTP.

## 5. Streaming y panel del cliente

- [x] 5.1 Añadir `POST /api/v1/estimate/stream` con `EstimationStreamMetadata` y `generate_from_prompts_stream` sobre el wrapper; verificar con pruebas de orden de eventos, metadatos, v2, 422 antes del stream, error sin `done` y mensajes separados en OpenAI y Anthropic.
- [x] 5.2 Pasar Streamlit a streaming con historial, barra lateral (prompt de sistema, ejemplos few-shot, métricas y versión) y «Borrar historial»; verificar con AppTest (texto por streaming, métricas, prompt y ejemplos, historial, errores) y actualizar README y docs.

## 6. Integración

- [x] 6.1 Ejecutar la suite completa, `compileall`, `git diff --check` y `openspec validate --all --strict`, y registrar resultados y límites en `verification.md`.
