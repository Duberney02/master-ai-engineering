# Evaluación: generación estructurada (Instructor) y unificación de proveedores (LiteLLM)

Fecha: 2026-10-09 · Estado: **decisión de no adoptar ninguna de las dos por ahora**; ninguna es requisito del proyecto.

## Criterio

Una librería nueva solo entra si aporta una ventaja medible frente a lo que ya hay **sin duplicar** lo que ya resuelve el proyecto:

- caché de completions con validación previa (`LLMWrapper`), reintentos con el SDK, *fallback* de proveedor y modelo, costes por `MODEL_PRICES` y errores de proveedor saneados (nunca se expone el mensaje del SDK);
- clientes **asíncronos** (`AsyncOpenAI`, `AsyncAnthropic`) y streaming propio;
- contrato en español con reglas de negocio (`validate_text`, filtro de fuera de alcance, corrección automática con el motivo del fallo).

## Primitiva propia: `app.services.structured.generate_structured`

Es la «primitiva de generación estructurada basada en modelos Pydantic» del proyecto: recibe un generador (`generate_from_messages` por defecto), una lista de mensajes y un modelo Pydantic; valida la respuesta con `extract_json` + `model_validate`, y ante una respuesta inválida reintenta con la respuesta anterior y el motivo (`correction_message`) hasta `attempts` veces, devolviendo el objeto y las completions consumidas. Se usa en el crítico (`CriticFeedback`) y en el detector de anclas con LLM (`AnchorVerdict`). Como pasa por `generate_from_messages`, hereda caché (solo se cachean respuestas válidas), fallback, métricas y errores saneados. Son ~60 líneas sin dependencias nuevas, cubiertas por `tests/test_structured.py`.

## Instructor

Qué aporta: `response_model=` sobre clientes de varios proveedores, reintentos ante fallos de validación, soporte de *tool calling*/modos JSON nativos y *streaming* parcial de modelos.

Hallazgos:

- **Dependencias** (resolución en seco dentro del contenedor de desarrollo, `uv pip install --dry-run instructor`): 13 paquetes nuevos (entre ellos `aiohttp` y `rich`) y **cambia la versión de `openai`** (3.13.0 → 3.3.0) y de `rich`/`jiter`. Habría que fijar la compatibilidad con los SDK que ya usa el wrapper.
- **Solapamiento**: reintentos y validación ya existen; Instructor llamaría al SDK por su cuenta y **saltaría** `LLMWrapper` (caché con validación previa, fallback, costes, sanitizado de errores), de modo que habría que reimplementar esas políticas alrededor o duplicar llamadas.
- **Ventaja real**: el modo de *tool calling* con esquema JSON obliga al modelo a respetar el formato; hoy el formato se pide en el prompt y se valida (con corrección), y los casos de corrección son raros. No hay evidencia en este proyecto de que justifique el coste.

Decisión: **no adoptar**. Se reevaluará si aparecen modelos con muchas respuestas inválidas, esquemas anidados complejos o necesidad de *streaming* parcial de objetos; en ese caso encajaría como implementación alternativa de `generate_structured` detrás del mismo contrato, sin cambiar a los llamadores.

## LiteLLM

Qué aporta: una interfaz común a más de cien proveedores, *router* con *fallbacks*, seguimiento de costes y caché.

Hallazgos:

- **Dependencias** (`uv pip install --dry-run litellm`): 28 paquetes nuevos (entre ellos `tiktoken`, `tokenizers`, `huggingface-hub` y `aiohttp`) y **cambia la versión de `openai`** (3.13.0 → 2.54.0). Es una superficie de dependencias y de actualizaciones muy superior a la del wrapper actual.
- **Solapamiento**: el wrapper ya unifica **dos** proveedores (OpenAI y Anthropic) con *fallback* configurable, reintentos, costes (`MODEL_PRICES`, con tarifa visible y revisable) y caché con validación previa. LiteLLM no elimina `LLMWrapper`: habría que mantener la caché validada y el sanitizado de errores encima, y adaptar el streaming y las pruebas, que simulan los SDK concretos.
- **Ventaja real**: solo compensa si se necesitan más proveedores (Gemini, Bedrock, modelos locales…). Hoy no es un requisito; añadirlos al wrapper supone un adaptador por proveedor (`_call_*`/`_stream_*`).

Decisión: **no adoptar**. Condición para reabrir: un tercer proveedor con requisitos reales. Alternativa de menor riesgo entonces: un adaptador nuevo en `llm_service.py` o usar LiteLLM únicamente como cliente dentro de un adaptador, manteniendo `LLMWrapper`.

## Reproducibilidad

```sh
docker compose -f docker-compose.verify.yml run --rm api-uv pip install --dry-run --python /opt/venv/bin/python instructor
docker compose -f docker-compose.verify.yml run --rm api-uv pip install --dry-run --python /opt/venv/bin/python litellm
```

Son resoluciones en seco: no modifican el entorno ni el `uv.lock`. Los números dependen de la fecha y del resolvedor; no se ha comparado rendimiento ni calidad de respuestas con proveedores reales.
