# Proposal

## Why

Hoy el prompt del estimador está embebido como cadenas Python y la única entrada es una transcripción libre, así que no se puede versionar, revisar ni probar el prompt por separado del código. Un contrato tipado (tipo de proyecto, nivel de detalle, formato de salida) y plantillas Jinja2 versionadas permiten iterar el prompt, compararlo entre versiones y probarlo en milisegundos sin llamar al modelo.

## What Changes

- **BREAKING** `POST /api/v1/estimate` pasa a aceptar `EstimationRequest` (`description`, `project_type`, `detail_level`, `output_format` y `reference_projects` opcional) y devuelve `EstimationResponse` (`text`, `prompt_version`).
- **BREAKING** El flujo existente de transcripción (opciones, evaluación, dos fases y SSE) se conserva sin cambios de comportamiento, pero se mueve a `POST /api/v1/transcription/estimate` y `POST /api/v1/transcription/estimate/stream`.
- Nuevo query param `prompt_version` (por defecto `v1`) en `/api/v1/estimate`; las versiones desconocidas se rechazan con 422.
- Plantillas Jinja2 versionadas en `app/prompts/estimation/<versión>/` (`system.j2`, `user.j2`, `examples.j2`) y un loader que devuelve `(system, user)`. Las versiones `v1` y `v2` difieren deliberadamente en tono y ejemplos.
- Proyectos de referencia opcionales, que la plantilla recorre cuando están presentes.
- Log estructurado por cada renderizado con la versión del prompt y un hash del contenido, sin incluir el texto.
- Nuevo `POST /api/v1/estimate/stream` (SSE: `token`, `metadata`, `done`/`error`) para el contrato estructurado, con la misma política de proveedor.
- El cliente Streamlit sustituye el chat por un formulario tipado con las mismas clases Pydantic, recibe la respuesta por streaming en un historial borrable y mantiene la barra lateral con el prompt de sistema, los ejemplos few-shot y las métricas de la última llamada.
- Pruebas de plantilla que no tocan APIs externas.

## Capabilities

### New Capabilities

- `estimator/prompt-templates`: plantillas de prompt versionadas, renderizado estricto, proyectos de referencia y trazabilidad del render.
- `estimator/structured-estimation`: contrato tipado de solicitud/respuesta de `/api/v1/estimate`, selección de versión y cliente de formulario.

### Modified Capabilities

- `estimator/http-streaming`: el contrato SSE de transcripción se mueve a `/api/v1/transcription/...` y Streamlit pasa a consumir el streaming del contrato estructurado.

## Impact

- Código: `app/schemas/`, nuevo `app/prompts/`, `app/routers/`, `app/main.py`, `app/services/llm_service.py`, `app/streamlit_client.py`, `streamlit_app.py`, `app/static/sse_demo.html`.
- API: los consumidores de `/api/v1/estimate` y `/estimate/stream` con transcripción deben migrar a `/api/v1/transcription/...`. Postman, README y docs se actualizan.
- Dependencias: `jinja2` se declara de forma explícita (ya estaba instalada de forma transitiva mediante `fastapi[standard]`).
- Se conservan el wrapper de proveedor (caché, fallback, costes), los SDK asíncronos y los errores saneados. No se hacen llamadas pagadas para verificar.
