# Proposal

## Why

Cambiar el modelo del LLM exige hoy editar `.env` y reiniciar el servicio; no se puede comparar modelos «en caliente» ni dar a un cliente una pantalla de Ajustes. Además, la caché semántica no separa las entradas por modelo: con modelos intercambiables en tiempo de ejecución serviría respuestas generadas por otro modelo. La referencia (`ai-engineering`, `session_07_live`) resuelve ambas cosas con un almacén de overrides en Redis, un catálogo filtrado por claves y una API de lectura/escritura.

## What Changes

- **Overrides persistentes en Redis** (`foundation/llm/runtime_config.py`) por knob: modelo primario, fallback, crítico, metadatos, resumen/compresión y los dos chunkers con LLM. Sobreviven a reinicios y se comparten entre procesos; si Redis cae, la lectura vuelve a los valores de `.env`. El modelo de embeddings queda fuera a propósito.
- **Resolución por solicitud**: cada solicitud lee los overrides una vez (`effective_settings`) y trabaja con esa copia: wrapper del LLM, tareas (crítico, resumen, anclas, metadatos), pipeline y chunkers. Sin reconstruir clientes ni reiniciar.
- **Enrutado por proveedor**: el wrapper elige el SDK según el modelo (un crítico de Anthropic convive con un primario de OpenAI).
- **Catálogo** `available_models` (setting), filtrado en la API por las claves configuradas.
- **`GET/PUT /api/v1/config/models`** (aditivo): lectura con valor efectivo, por defecto y si hay override; escritura parcial y todo-o-nada, `null` restablece; errores específicos (422 knob desconocido o modelo fuera del catálogo, 400 clave ausente, 503 almacén caído); log de auditoría por cambio.
- **Caché semántica por modelo**: `model` pasa a ser un filtro de la entrada y el índice cambia de nombre (`…_by_model`).
- Documentación del comportamiento del fallback bajo un override.

**No incluido**: cambiar el modelo de embeddings en runtime; autenticación de la API de configuración (no existe en ninguna ruta del servicio); interfaz de usuario (bloque D).

## Capabilities

### New Capabilities
- `estimator/runtime-model-config`: almacén de overrides, resolución por solicitud, catálogo y API.

### Modified Capabilities
- `estimator/semantic-cache`: el aislamiento por atributos incluye el modelo que generó la entrada.

## Impact

- Código: `app/foundation/llm/{runtime_config,service,wrapper}.py`, `app/domain/{pipeline,session_estimation}.py`, `app/generation/{cag/semantic,agentic/critic,conversation/anchors,conversation/summarizer}.py`, `app/api/config.py`, `app/dependencies.py`, `app/config.py`, `app/main.py`, `app/logging_config.py`.
- Rutas nuevas: `GET/PUT /api/v1/config/models`. Ninguna ruta ni JSON existente cambia.
- La caché semántica estrena índice (`…_by_model`): las entradas antiguas dejan de usarse y caducan por TTL.
- Las pruebas usan `fakeredis`; la integración se comprobó también contra Redis y Redis Stack reales en Docker.
