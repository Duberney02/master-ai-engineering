# Design

## Context

Motivación en proposal.md. El prompt actual se construye en `llm_service.build_system_prompt` con f-strings, y los adaptadores ya envían `system` y `user` por separado: OpenAI usa dos mensajes y Anthropic usa `system=` más un mensaje `user`. `LLMWrapper` concentra la caché, el fallback y los costes. `app/schemas/` ya es un paquete (`estimation.py`), así que no puede coexistir con un `app/schemas.py`.

## Goals / Non-Goals

**Goals:**
- Que las plantillas sean la única fuente del prompt estructurado y que añadir `v3/` baste para tener una versión nueva.
- Reutilizar el wrapper de proveedor sin duplicar la lógica de caché, fallback ni costes.
- Que las clases Pydantic se compartan entre el servicio y el cliente.

**Non-Goals:**
- Migrar el flujo de transcripción a plantillas Jinja2 o cambiar su comportamiento.
- Evaluación estructural del texto del nuevo contrato.

## Decisions

1. **Esquemas en `app/schemas/project_estimation.py`, reexportados en `app/schemas/__init__.py`.** Así `from app.schemas import EstimationRequest` funciona igual que con el `app/schemas.py` pedido, sin romper `app.schemas.estimation`. Alternativa descartada: renombrar el paquete, que rompe imports y pruebas existentes.
2. **Rutas.** El router estructurado se monta en `/api/v1` y el de transcripción en `/api/v1/transcription`, sin tocar su código. Se eligió según la decisión del usuario, por encima del reemplazo total o de dejar `/estimate` intacto.
3. **Un `Environment` por versión con `FileSystemLoader(estimation/<v>)`, cacheado.** Permite `{% include "examples.j2" %}` relativo a la versión. Usa `StrictUndefined`, `trim_blocks`, `lstrip_blocks` y `autoescape=False` (el destino es texto para el LLM, no HTML). Las versiones se descubren listando directorios `v<n>`. El nombre se valida con la regex `^v\d+$` y se comprueba que exista antes de construir rutas, lo que impide el path traversal.
4. **Contexto de plantilla = `request.model_dump(mode="json")`.** Las plantillas comparan cadenas (`output_format == "phases_table"`) y no dependen de las clases Enum.
5. **Ejemplos few-shot como datos Jinja (`{% set %}`) renderizados con macros según `output_format` y `detail_level`.** Cada ejemplo se muestra en el mismo formato que se pide. Así la tabla de ejemplo no filtra `confidence_pct` cuando el formato es `narrative`, y las asunciones por fase solo aparecen con `detailed`.
6. **Llamada al modelo.** `llm_service.generate_from_prompts(system, user)` delega en el `_complete` existente (wrapper, caché, fallback, costes) y devuelve el texto. La caché ya distingue por `system` y `user`, así que las versiones no se mezclan.
7. **Log del render.** Evento `prompt_rendered` con `prompt_version`, `prompt_hash` (SHA-256 de `system + "\0" + user`), `project_type`, `output_format`, `detail_level` y longitudes. No incluye texto.
8. **Versión inválida → 422.** El loader lanza `UnknownPromptVersionError(ValueError)` y el router lo traduce a `HTTPException(422)`.
9. **Streaming estructurado.** `POST /api/v1/estimate/stream` renderiza antes de abrir el stream, así que las versiones inválidas dan 422 y no un evento. `llm_service.generate_from_prompts_stream` reutiliza `LLMWrapper.stream` y los adaptadores `_stream_openai` y `_stream_anthropic`, igual que el flujo de transcripción: caché, fallback solo antes del primer fragmento y cierre de recursos. `metadata` se tipa como `EstimationStreamMetadata` en `app.schemas`, y la usan el servidor y el cliente. La respuesta completa de `/api/v1/estimate` no cambia.
10. **Cliente.** `streamlit_client` comparte el lector SSE entre `stream_estimation` (transcripción) y `stream_structured_estimation` (formulario). Esta última valida `metadata` con `EstimationStreamMetadata`. Streamlit usa `st.write_stream` dentro de un historial de `st.chat_message` y conserva «Borrar historial». La barra lateral renderiza en local el prompt de sistema con `render_estimation_prompt` para la última solicitud (o una vista previa por defecto), como antes hacía con `build_system_prompt`, y extrae de él los títulos de los ejemplos few-shot. Si la API remota usa otras plantillas, el panel refleja las del cliente; así ya ocurría antes.

## Risks / Trade-offs

- [Cambio incompatible de ruta para consumidores del flujo de transcripción] → documentarlo en README, docs y Postman, y actualizar la demo HTML.
- [La descripción del usuario puede intentar cerrar `</project_description>` e inyectar instrucciones] → el sistema indica que ese bloque son datos, no instrucciones. La descripción se inserta literal, como exige la spec, y se limita a 2000 caracteres.
- [Las listas de versiones del cliente y del servidor pueden divergir] → si el cliente pide una versión que no existe, el servidor responde 422 y el cliente muestra el error.

## Migration Plan

Cambiar `/api/v1/estimate/stream` por `/api/v1/transcription/estimate/stream` (y lo mismo para `/estimate`) en integraciones que envían `transcription`. Rollback: revertir la rama; no hay datos persistentes. Las claves de caché antiguas no colisionan con las nuevas porque los prompts son distintos.
