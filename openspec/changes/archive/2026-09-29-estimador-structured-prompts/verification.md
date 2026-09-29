# Verificación

Fecha: 2026-09-29. Rama `feature/pre-session-04`, base master `b7882628c998f4ad767c1d3b81263c31f9baeca9`.
Antes de empezar se archivó el cambio anterior como
`changes/archive/2026-09-29-estimador-resilience-and-streaming` (sus specs ya estaban sincronizadas).

## Resultados

- Línea base antes de implementar: `uv run pytest -q` → **218 passed**.
- Suite completa final: `uv run pytest -q` → **300 passed**, ~9 s. Persiste la advertencia de
  Starlette/AnyIO (alias BlockingPortal), que ya existía.
- `tests/prompts/` → **65 passed en 0,42 s**; la prueba más lenta tarda 0,05 s. No hay E/S de red.
- `uv run python -m compileall -q app streamlit_app.py` → correcto.
- `git diff --check` → correcto.
- `openspec validate --all --strict` → **4 passed, 0 failed**.
- `jinja2>=3.1,<4` declarado en pyproject y `uv.lock` actualizado (3.1.6, ya presente de forma transitiva).
- En código, demo, docs y Postman no quedan usos de transcripción que apunten a las rutas
  antiguas; `/api/v1/estimate/stream` ahora pertenece al contrato estructurado (ver abajo).

## Seguimiento: streaming y panel del cliente

Al probarlo, el usuario detectó dos regresiones de la primera implementación: la respuesta
llegaba completa (el formulario usaba `POST /api/v1/estimate` sin streaming) y la barra
lateral había perdido el prompt, los ejemplos y las métricas. Corrección:

- Nuevo `POST /api/v1/estimate/stream` con `metadata` tipado (`EstimationStreamMetadata`),
  sobre `LLMWrapper.stream`. Las versiones y entradas inválidas dan 422 antes del stream.
- Streamlit usa `st.write_stream` dentro de un historial con «Borrar historial». La barra
  lateral recupera el system prompt (ahora renderizado desde las plantillas de la última
  solicitud), los ejemplos few-shot y las métricas, y añade la versión del prompt.
- Suite completa: `uv run pytest -q` → **306 passed**, ~12 s. `compileall`, `git diff --check`
  y `openspec validate --all --strict` (**4 passed**) correctos.
- Smoke con uvicorn real y un proveedor OpenAI simulado que tarda 0,3 s por fragmento:
  el cliente recibió los tokens a los 0,64 / 0,95 / 1,27 / 1,58 s, es decir, de forma
  progresiva y no en bloque. Después llegó `metadata` con `prompt_version=v2` y el consumo.

## Trazabilidad

| Requisito | Evidencia |
|---|---|
| Renderizado versionado, StrictUndefined, versión inválida/traversal | `tests/prompts/test_loader.py` |
| Descripción literal en `<project_description>` | `test_estimation_v1.py::test_user_prompt_wraps_description_literally` |
| `confidence_pct` con `phases_table`, ausente con `narrative` | `test_estimation_v1.py`, `test_estimation_v2.py` |
| Asunciones por fase con `detailed`, ausentes con `summary` | `test_estimation_v1.py`, `test_estimation_v2.py` |
| Las 36 combinaciones renderizan sin marcas residuales | `test_every_combination_renders_without_leftover_markup` |
| `reference_projects` recorrido con `{% for %}` | tests de referencias en v1/v2 y `test_project_estimations.py` |
| Log `prompt_rendered` con versión y hash, sin texto | `test_loader.py::test_render_logs_version_and_hash_without_content` |
| Contrato `{text, prompt_version}`, 422 sin llamar al proveedor | `tests/test_project_estimations.py` |
| `?prompt_version=v2` y versión inexistente | `tests/test_project_estimations.py` |
| Mensajes system/user separados (OpenAI) y `system=` + user (Anthropic) | `tests/test_project_estimations.py` |
| Error de proveedor saneado a través del wrapper | `test_provider_failure_is_sanitized` |
| Flujo de transcripción y SSE en `/api/v1/transcription` | `test_api_errors.py`, `test_sse_and_options.py`, `test_transcription_flow_moved_under_its_own_prefix` |
| Stream estructurado: orden de eventos, metadatos, v2/Anthropic, 422 previo, error sin `done` | `tests/test_project_estimations.py` |
| Formulario Streamlit tipado, streaming, historial, barra lateral, validación sin HTTP, errores saneados | `tests/test_streamlit_app.py` |
| El cliente rechaza streams incompletos o con metadatos fuera del contrato | `test_structured_client_never_accepts_incomplete_streams` |

## Alcance y límites

- No hubo llamadas pagadas ni se midió la calidad de las estimaciones generadas con
  v1 frente a v2: las pruebas verifican las plantillas y el contrato, no el modelo.
- La imagen Docker no se reconstruyó. Las dependencias nuevas ya estaban en la imagen,
  pero el arranque en contenedor no se comprobó en este cambio.
- El cliente ofrece `v1` y `v2` desde una constante. Si el servidor añade versiones,
  hay que añadirlas en el cliente; una versión que el servidor no conozca se rechaza
  con 422 y el cliente la muestra como error.
- La descripción se inserta literal en el prompt, como pide la spec. La defensa ante
  intentos de inyección es la instrucción del sistema y el límite de 2000 caracteres.
- AppTest no reproduce el renderizado progresivo en el navegador. La progresividad se
  verificó con el smoke HTTP; la vista en el navegador no se comprobó de forma automática.
- No se crearon commits, PR ni despliegue.
