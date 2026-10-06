# Generación resiliente y streaming HTTP

Este cambio está especificado con OpenSpec en la raíz. Conserva el endpoint JSON,
salida española, límites de entrada y evaluación de horas; añade metadatos.

## Configuración

| Variable | Default | Efecto |
|---|---|---|
| `LLM_TIMEOUT` | 60 | Segundos por intento SDK, hasta 600 |
| `LLM_RETRIES` | 2 | Reintentos SDK, de 0 a 5 |
| `FALLBACK_PROVIDER` / `FALLBACK_MODEL` | sin configurar | Alternativa explícita; necesita su clave |
| `REDIS_URL` | sin configurar | Desactiva caché si no se configura |
| `CACHE_TTL` | 86400 | Duración máxima en segundos |
| `CACHE_TIMEOUT` | 0.5 | Timeout Redis en segundos |
| `MODEL_PRICES` | `{}` | JSON de precios USD por millón de tokens |
| `ESTIMATOR_API_BASE_URL` | `http://localhost:8000` | URL de la API usada por Streamlit |

Ejemplo de precios **ficticios para pruebas**, sustituir por tarifas contratadas:

```dotenv
MODEL_PRICES={"gpt-4o-mini":{"input":1.0,"output":2.0}}
```

Las claves deben coincidir con el modelo devuelto por el SDK, incluidos sufijos.
Sin coincidencia, el coste es `null`. `estimated_cost_usd` representa el coste de
generar el contenido con las tarifas configuradas actuales, incluso al reutilizarlo.
`request_cost_usd` suma solo fases exitosas no cacheadas; reutilizar cuesta 0.
No es una factura: podrían facturarse intentos fallidos o aplicarse descuentos de
prompt caching que esta aproximación no contempla.

`cache_hit=true` significa que todas las fases se reutilizaron. `usage.phases`
detalla proveedor real, tokens, caché, costes y `usage_available` por fase.
Los tokens cacheados describen la generación original. Sin uso reportado en
streaming, los contadores son 0 con `usage_available=false`, coste null y sin
almacenamiento. Nunca se inventa finish_reason.

## Caché y fallback

La clave SHA-256 incluye prompt, entrada, proveedores/modelos, parámetros y
namespace versionado. Las dos fases se cachean por separado. Cambiar ejemplos,
tarifas de proyecto o razonamiento invalida la entrada. Si Redis falla o devuelve
datos inválidos, continúa la generación. No se guardan vacíos, errores o
truncamientos. No hay deduplicación en vuelo: misses simultáneos pueden generar
varias llamadas.

Redis almacena contenido derivado de transcripciones y está destinado a un solo
ámbito de confianza. Separar instancias/namespaces y añadir autenticación antes
de convertirlo en multiusuario. La API sigue sin autenticación; Compose es para
desarrollo. Redis interno es **Redis Stack** (RediSearch, necesario para la caché semántica), con volumen y sin puerto publicado ni política de evicción: el índice vectorial no debe expulsarse. Las entradas caducan por TTL.

Fallback ocurre ante timeout/conexión/429/5xx tras reintentos SDK, no ante errores
de credenciales o parámetros. `model` explícito lo desactiva. Después del primer
fragmento nunca se cambia de modelo. Timeout es por intento, no por solicitud.

## Contrato SSE

`POST /api/v1/transcription/estimate/stream` acepta los mismos campos que `/api/v1/transcription/estimate`.
`two_phase` termina la extracción antes de emitir texto. Ejemplo Bash:

```sh
curl -N http://localhost:8000/api/v1/transcription/estimate/stream \
  -H 'Content-Type: application/json' \
  -d '{"transcription":"Necesitamos un catálogo web con usuarios, pagos y panel de administración."}'
```

Eventos con JSON en `data` (metadatos abreviados):

```text
event: token
data: {"text":"## Estimación: Catálogo\n"}

event: metadata
data: {"model":"...","usage":{},"cache_hit":false,"request_cost_usd":null}

event: done
data: {"status":"complete"}
```

`metadata` es la respuesta normal excepto `estimation`, incluida evaluación y
fases. Ante fallo se emite `error` con `status_code` y `message` saneado, sin done.
Desconexión sin done significa respuesta incompleta. Entradas inválidas producen
HTTP 422 antes del stream. `done` confirma fin del transporte: consultar evaluación
para detectar truncamiento o estructura inválida. Caché puede emitir un único token.

Demo: abrir `/static/sse_demo.html` en la API. Los clientes Python de
`app.streamlit_client` limitan la lectura a 600 s y la conexión a 10 s;
configuraciones extremas pueden requerir adaptar el cliente/proxy. Streamlit usa el
mismo formato de eventos, pero sobre el contrato estructurado
`POST /api/v1/estimate/stream`, cuyo `metadata` es `EstimationStreamMetadata`
(ver README).

## Opciones adicionales

- `thinking_budget`: 1024–15000, solo Anthropic con modelo compatible. Se aplica a
  estimación, no extracción. Límite efectivo >= presupuesto + 1024, hasta 16024.
  Se rechaza con 422 si el principal o fallback aplicable es OpenAI. El proveedor
  valida soporte específico del modelo y sus errores se sanean.
- `include_project_costs`: false por defecto; activa una tabla adicional
  `Rol | Horas | Tarifa EUR/h | Coste EUR`, con Desarrollo y Diseño.
- `developer_rate_eur` / `designer_rate_eur`: 62.5 / 50 por defecto, > 0 y <= 10000.
  Son tarifas de proyecto, no de inferencia.
- Evaluación: `project_cost_match`, `declared_project_cost_eur`; comprueba tarifas,
  multiplicaciones, total monetario y reparto de horas. Presupuesto orientativo,
  sin impuestos ni servicios externos.

## Observabilidad y pruebas

Los módulos de aplicación usan `structlog.get_logger(__name__)` con eventos
estables y campos nombrados. `APP_ENV=production` usa `JSONRenderer`;
desarrollo usa `ConsoleRenderer`. `ProcessorFormatter` integra también los
registros estándar de Python con el mismo formato y respeta `LOG_LEVEL`.
Se incluyen modelo, proveedor, tokens, coste, latencia y finalización. Un
procesador conserva solo campos operativos permitidos; los errores se registran
por tipo, sin claves, prompts ni mensajes internos de excepciones.

```python
import structlog

logger = structlog.get_logger(__name__)
logger.info("llm_completed", provider="openai", model="demo", input_tokens=100,
            output_tokens=50, cost_usd=None, latency_ms=125, cache_hit=False)
```

No introducir información sensible en el nombre/texto del evento ni en los
campos operativos; el filtrado de claves no sanea valores arbitrarios.
Referencia: https://www.structlog.org/en/stable/standard-library.html.

```sh
uv sync --locked --group dev
uv run pytest -q
```

Pruebas con SDK/HTTP simulados: fallback, caché normal/streaming, TTL, corrupción,
cancelación, coste por fase, parser SSE, UI y evaluación monetaria. No usan modelos pagados.

## Estimación estructurada: guardrails, validación y caché semántica

`POST /api/v1/estimate` ejecuta un pipeline único (`app/services/pipeline.py`):
guardrails de entrada → caché exacta → caché semántica → render del prompt →
generación → validación de negocio (con reintentos) → almacenamiento.

| Variable | Defecto | Efecto |
|---|---|---|
| `MODERATION_ENABLED` | true | Moderación de OpenAI; se omite sin `OPENAI_API_KEY` |
| `MODERATION_MODEL` | omni-moderation-latest | Modelo de moderación |
| `MODERATION_FAIL_OPEN` | true | Si la moderación falla: continuar (true) o responder 503 (false) |
| `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` | text-embedding-3-small / 1536 | Embeddings (OpenAI); forman parte del nombre del índice |
| `SEMANTIC_CACHE_MODE` | active | `off`, `log_only` (consulta y registra `semantic_cache_would_hit`, no devuelve) o `active` |
| `SEMANTIC_CACHE_THRESHOLD` | 0.92 | Similitud coseno mínima (0–1) |
| `SEMANTIC_CACHE_TTL` | 86400 | TTL de las entradas semánticas en segundos |
| `VALIDATION_MAX_ATTEMPTS` | 3 | Intentos totales para obtener un resultado válido (1 = sin corrección) |

**Guardrails**: se evalúan `description` y los textos de `reference_projects`. Orden: datos
personales (correo, teléfono, IBAN con mod-97), prompt injection (heurística ES/EN) y moderación.
Un rechazo es `400 {"reason", "message"}` con `reason` en `pii_email`, `pii_phone`, `pii_iban`,
`prompt_injection` o `moderation`; el mensaje no reproduce el dato detectado. Los guardrails
corren antes de cualquier caché o llamada al proveedor.

**Validación**: la suma de `cost_eur` de las fases debe coincidir con `total_cost_eur` (±0,01 EUR) y,
con `confidence_pct` < 30, `summary` debe empezar por `Out of scope:`. Si falla, se reenvía la
respuesta anterior y el error concreto al modelo; agotados los intentos, 502 saneado. Un resultado
fuera de alcance se normaliza a una fase placeholder `No estimable` (0 EUR, 1 semana).

**Caché semántica**: `redisvl` sobre Redis Stack; cada consulta filtra por versión de prompt, tipo de
proyecto, detalle y formato, de modo que nunca se mezclan. Sin `REDIS_URL` o sin `OPENAI_API_KEY`
(Anthropic no ofrece embeddings) queda desactivada. Los fallos de Redis o embeddings se tratan como
un fallo de caché. Para calibrar el umbral, arrancar en `log_only` y revisar los eventos
`semantic_cache_would_hit` y su `similarity`.
