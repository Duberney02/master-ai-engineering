# Software Estimation CAG API

Estimaciones iniciales de proyectos de software a partir de transcripciones de
reuniones con clientes, usando CAG (Context-Augmented Generation) con OpenAI o
Anthropic. El proyecto tiene dos piezas independientes:

- **API FastAPI** (`app/`): prompts, ejemplos, preprocesamiento, wrapper LLM con
  reintentos/fallback, caché Redis, generación normal y streaming SSE.
- **Chat Streamlit** (`streamlit_app.py` + `estimator_client/`): cliente HTTP de la API.
  No importa el backend, no construye prompts y no necesita claves ni Redis.

## ¿Qué es CAG en este proyecto?

CAG inyecta ejemplos históricos de estimaciones **directamente dentro del prompt
del LLM** — sin embeddings, sin vector stores, sin recuperación semántica.

## Arquitectura

```
 Streamlit (estimator_client)                     API FastAPI (app/)
 ─────────────────────────────                    ──────────────────────────────────────────────
 streamlit_app.py                                 routers/estimations.py   ← transporte HTTP/SSE
   └─ EstimatorApiClient ── HTTP ──────────────▶    validación, 422 antes del stream, errores saneados
        ├─ GET  /api/v1/context                         │  Depends(get_resources)
        ├─ POST /api/v1/estimate                        ▼
        └─ POST /api/v1/estimate/stream (SSE)     services/estimation_service.py ← negocio
             SSEDecoder (WHATWG)                    prompts, ejemplos, preprocesamiento, fases,
                                                    evaluación estructural
                                                        │  LLMGateway (protocolo)
                                                        ▼
                                                  llm/client.py (LLMClient)  ← wrapper LLM
                                                    política de modelos, timeout, reintentos,
                                                    fallback, métricas/costes, deduplicación
                                                   ├─ llm/providers/{openai,anthropic}_provider.py
                                                   │    SDK asíncronos → tipos normalizados + LLMError
                                                   └─ cache/result_cache.py  ← caché Redis
                                                        claves SHA-256, TTL, modo degradado
                                                  dependencies.py ← construcción por proceso y cierre
                                                  observability.py ← logs estructurados + X-Request-ID
```

| Capa | Módulo | Responsabilidad |
|---|---|---|
| Transporte | `app/routers/estimations.py`, `app/transport/` | Validación de entrada, HTTP, SSE, traducción de errores (`transport/errors.py`) |
| Negocio | `app/services/estimation_service.py`, `prompts.py`, `evaluation.py`, `reporting.py` | Prompts, ejemplos, preprocesamiento, coordinación de fases, evaluación, metadatos |
| Wrapper LLM | `app/llm/` | Proveedores, normalización, timeout, reintentos, fallback, costes, integración con caché. Sin dependencias de FastAPI |
| Caché | `app/cache/result_cache.py` | Claves, serialización, lectura/escritura, expiración, degradación |
| Dependencias | `app/dependencies.py`, `app/main.py` | Construcción única en el `lifespan`, inyección con `Depends`, cierre al apagar |

Decisiones técnicas relevantes:

- **Sin LiteLLM.** Se mantienen los SDK asíncronos oficiales detrás de un protocolo
  `ProviderAdapter` pequeño y tipado. Así el control de fallback es explícito (sobre todo
  en streaming, donde no se puede cambiar de proveedor tras emitir contenido), el mapeo de
  errores es exacto y las pruebas sustituyen proveedores sin parches globales. Añadir
  LiteLLM no aportaba nada que el wrapper no cubra y sumaba una dependencia pesada.
- **Excepciones propias** (`app/llm/errors.py`) independientes de FastAPI; solo la capa de
  transporte las convierte en códigos HTTP o eventos SSE.
- **Cliente síncrono en Streamlit** (`httpx.Client`): Streamlit ejecuta scripts síncronos;
  el servidor sigue siendo 100 % asíncrono (SDK async, `redis.asyncio`).

## Estructura del proyecto

```
estimador-cag/
├── app/                       — SERVIDOR (extra `api`)
│   ├── main.py                — create_app(), lifespan, /health
│   ├── config.py              — Settings del servidor (credenciales, modelos, caché, logs)
│   ├── dependencies.py        — construcción/reutilización/cierre de recursos, Depends
│   ├── observability.py       — logs (consola/JSON) y middleware X-Request-ID
│   ├── routers/estimations.py — /estimate, /estimate/stream, /context
│   ├── transport/             — SSE (formato, latidos) y traducción de errores
│   ├── schemas/estimation.py  — contratos Pydantic
│   ├── services/              — estimación, prompts, evaluación, métricas
│   ├── llm/                   — wrapper: client, routing, errors, pricing, types, providers/
│   ├── cache/result_cache.py  — caché Redis
│   └── context/examples.py    — catálogo CAG (5 ejemplos estructurados)
├── estimator_client/          — CLIENTE (extra `ui`): config, api, sse, presentation
├── streamlit_app.py           — interfaz de chat
├── tests/
├── Dockerfile                 — objetivos `api` (por defecto) y `ui`
├── docker-compose.yml         — api + chat + redis
├── docker-compose.redis-debug.yml — publica Redis en 127.0.0.1 (solo depuración)
├── .env.example               — servidor (sin secretos)
├── .env.client.example        — cliente (sin secretos)
└── postman/                   — colección y ejemplos cURL
```

## Instalación

Requisitos: Python 3.11+, [uv](https://docs.astral.sh/uv/). Opcional: Docker con Compose v2 y Redis.

```bash
cd estimador-cag
uv sync --all-extras          # servidor + cliente + herramientas de desarrollo
# Solo servidor:  uv sync --extra api --no-dev
# Solo cliente:   uv sync --extra ui  --no-dev
```

Las dependencias están separadas en extras: `api` (FastAPI, SDK de OpenAI/Anthropic,
Redis, pydantic-settings) y `ui` (Streamlit, httpx).

## Configuración

### Servidor (`.env`, ver `.env.example`)

| Variable | Descripción | Default |
|---|---|---|
| `LLM_PROVIDER` | Proveedor del modelo primario: `openai` o `anthropic` | `openai` |
| `LLM_MODEL` | Modelo primario (admite `proveedor/modelo`) | `gpt-4o-mini` (`claude-haiku-4-5` si el proveedor es Anthropic y no se cambia) |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Claves; se exige la del proveedor de **cada** modelo configurado | — |
| `LLM_FALLBACK_MODEL` | Modelo secundario (`proveedor/modelo` o nombre inferible). Vacío = sin fallback | vacío |
| `ALLOWED_MODELS` | Modelos que una solicitud puede pedir con `model` (comas). Vacío = sin restricción | vacío |
| `LLM_TIMEOUT_SECONDS` | Timeout por intento (y de inactividad en streaming) | `60` |
| `LLM_MAX_RETRIES` | Reintentos por modelo ante errores recuperables (0–5) | `2` |
| `LLM_RETRY_BACKOFF_SECONDS` | Backoff base exponencial (máx. 10 s por espera) | `0.5` |
| `LLM_INFLIGHT_WAIT_SECONDS` | Espera máxima de una petición idéntica concurrente | `120` |
| `LLM_PRICING_OVERRIDES` | JSON con tarifas adicionales (USD/millón de tokens) | vacío |
| `CACHE_ENABLED` | Activa la caché Redis | `true` |
| `REDIS_URL` | URL de Redis (Compose: `redis://redis:6379/0`) | `redis://localhost:6379/0` |
| `CACHE_TTL_SECONDS` | TTL de cada entrada (1 s – 30 días) | `86400` |
| `CACHE_PREFIX` | Prefijo de las claves | `estimador-cag` |
| `REDIS_TIMEOUT_SECONDS` | Timeout de conexión y de cada operación Redis | `0.5` |
| `CACHE_RETRY_AFTER_SECONDS` | Tras un fallo de Redis, tiempo sin volver a consultarlo | `15` |
| `SSE_HEARTBEAT_SECONDS` | Intervalo de latidos `: keep-alive` durante esperas | `15` |
| `APP_ENV` / `LOG_LEVEL` | Entorno y nivel de log | `development` / `DEBUG` |
| `LOG_FORMAT` | `auto` (JSON si `APP_ENV=production`), `json` o `console` | `auto` |

La configuración se valida al arrancar: clave ausente para un modelo configurado
(primario, secundario o permitido), proveedor no inferible, secundario igual al primario,
`LLM_MODEL` con prefijo de otro proveedor o tarifas mal formadas detienen el arranque con
un mensaje claro.

### Cliente (`.env.client.example`)

| Variable | Descripción | Default |
|---|---|---|
| `ESTIMATOR_API_BASE_URL` | URL base de la API | `http://localhost:8000` |
| `ESTIMATOR_API_CONNECT_TIMEOUT_SECONDS` | Timeout de conexión | `5` |
| `ESTIMATOR_API_READ_TIMEOUT_SECONDS` | Máximo sin recibir datos (el servidor envía latidos) | `120` |

## Ejecución local

```bash
cp .env.example .env                                   # completa la clave del proveedor
docker run -d --name redis -p 127.0.0.1:6379:6379 redis:7.4-alpine   # opcional
uv run uvicorn app.main:app --reload                   # API en http://localhost:8000

# En otra terminal (el cliente solo necesita la URL de la API):
ESTIMATOR_API_BASE_URL=http://localhost:8000 uv run streamlit run streamlit_app.py
```

Sin Redis la API funciona igual (modo degradado): `/health` informa
`"cache": {"enabled": true, "reachable": false}` y cada petición llama al proveedor.
Para desactivar la caché explícitamente: `CACHE_ENABLED=false`.

## Ejecución con Docker

```bash
cp .env.example .env        # completa la API key del proveedor elegido
docker compose up --build   # API: http://localhost:8000 · Chat: http://localhost:8501
docker compose ps           # los tres servicios pasan a "healthy"
docker compose down         # conserva la caché; `down -v` también borra el volumen de Redis
```

| Servicio | Imagen (objetivo) | Recibe | Expuesto en el host |
|---|---|---|---|
| `api` | `Dockerfile` → `api` | `.env` (credenciales) + `REDIS_URL=redis://redis:6379/0` | `8000` |
| `chat` | `Dockerfile` → `ui` | solo `ESTIMATOR_API_BASE_URL=http://api:8000` | `8501` |
| `redis` | `redis:7.4-alpine` | — | **no** (solo red interna) |

- **Comunicación interna** por nombre de servicio (`http://api:8000`, `redis://redis:6379`).
- **Credenciales solo en el backend**: el chat no lee `.env`; su imagen no contiene `app/`,
  SDK de proveedores ni cliente Redis (lo verifica el CI).
- **Salud**: `api` → `/health`; `chat` → `/_stcore/health`; `redis` → `redis-cli ping`.
  `chat` espera a que `api` esté sana; `api` solo espera a que Redis *arranque* (no a que
  esté sano) para conservar el modo degradado.
- **Persistencia de Redis**: volumen `redis-data` con AOF (`appendfsync everysec`), sin
  snapshots RDB, `maxmemory 256mb` y expulsión `allkeys-lru`. Es una caché: perderla solo
  implica volver a llamar al proveedor.
- **Depuración de Redis**: `docker compose exec redis redis-cli`, o publica el puerto solo
  en loopback con `docker compose -f docker-compose.yml -f docker-compose.redis-debug.yml up`.
- **Seguridad**: ambas imágenes son multietapa, corren como usuario sin privilegios
  (UID 10001), no incluyen `uv` ni herramientas de desarrollo, y el código se monta en solo
  lectura en desarrollo. Redis no tiene contraseña porque no sale de la red interna; si lo
  expones, usa `REDIS_URL=redis://:contraseña@host:6379/0` (la URL nunca se registra).

Imágenes sin Compose:

```bash
docker build --target api -t estimador-cag-api .
docker build --target ui  -t estimador-cag-ui  .
docker run --rm -p 8000:8000 --env-file .env estimador-cag-api
docker run --rm -p 8501:8501 -e ESTIMATOR_API_BASE_URL=http://host.docker.internal:8000 estimador-cag-ui
```

## Uso de la API

Documentación interactiva: `http://localhost:8000/docs`. Más ejemplos en
[`postman/curls.md`](postman/curls.md) y en la colección de Postman.

### Opciones por solicitud (ambos endpoints)

Todas son opcionales y se validan (`422` si son inválidas).

| Campo | Valores | Default | Efecto |
|---|---|---|---|
| `transcription` | 20–50 000 caracteres | — | Transcripción de la reunión |
| `preprocessing` | `none`, `inline_cleaning`, `two_phase` | `none` | Preparación de la transcripción |
| `example_format` | `markdown`, `json`, `narrative` | `markdown` | Representación de los ejemplos CAG |
| `num_examples` | `0`–`5` | `2` | Ejemplos del catálogo incluidos |
| `use_examples` | `true`/`false` | `true` | `false` elimina todo el bloque de ejemplos |
| `model` | `gpt-4o`, `claude-haiku-4-5`, `proveedor/modelo`… | primario | Modelo de esta solicitud (restringible con `ALLOWED_MODELS`) |
| `allow_fallback` | `true`/`false` | `false` | Con `model`: permite pasar al secundario ante errores recuperables |
| `max_tokens` | `1`–`16000` | proveedor (OpenAI) / `4096` (Anthropic) | Límite de salida de la estimación |
| `evaluate` | `true`/`false` | `true` | Incluye la evaluación estructural |

**Preprocesamiento**: `inline_cleaning` añade instrucciones de limpieza al prompt (una
llamada); `two_phase` extrae primero los requisitos (máx. 2000 tokens) y estima a partir de
ellos. Los prompts siguen exigiendo distinguir requisitos explícitos de supuestos.

**Parámetros no soportados** (p. ej. `thinking_budget`, que no está implementado):
`/estimate/stream` los rechaza con `422`; `/estimate` los sigue aceptando por
compatibilidad pero ya no los ignora en silencio: los registra en el log y los devuelve en
la cabecera `X-Ignored-Fields`.

### `POST /api/v1/estimate`

```bash
curl -X POST http://localhost:8000/api/v1/estimate \
  -H "Content-Type: application/json" \
  -d '{"transcription": "El cliente quiere un marketplace de servicios profesionales con pagos, mensajería y valoraciones. Plazo: 5 meses.", "preprocessing": "two_phase"}'
```

Respuesta (abreviada):

```json
{
  "request_id": "5f0c…",
  "estimation": "## Estimación: Marketplace de Servicios Profesionales\n\n...",
  "model": "gpt-4o-mini-2024-07-18",
  "provider": "openai",
  "finish_reason": "stop",
  "usage": {
    "input_tokens": 4140, "output_tokens": 1620, "total_tokens": 5760,
    "incurred_input_tokens": 3840, "incurred_output_tokens": 1200, "incurred_total_tokens": 5040,
    "phases": [
      {"phase": "preprocessing", "provider": "openai", "model": "gpt-4o-mini-2024-07-18",
       "requested_model": "gpt-4o-mini", "finish_reason": "stop",
       "input_tokens": 300, "output_tokens": 420, "total_tokens": 720,
       "latency_ms": 3, "original_latency_ms": 1500, "cache": "hit",
       "generated_at": "2026-09-28T10:00:00Z", "fallback_used": false, "attempts": 0,
       "cost": {"original_generation_usd": 0.000297, "incurred_usd": 0.0}},
      {"phase": "estimation", "provider": "openai", "model": "gpt-4o-mini-2024-07-18",
       "requested_model": "gpt-4o-mini", "finish_reason": "stop",
       "input_tokens": 3840, "output_tokens": 1200, "total_tokens": 5040,
       "latency_ms": 5200, "original_latency_ms": 5200, "cache": "miss",
       "generated_at": "2026-09-28T12:00:00Z", "fallback_used": false, "attempts": 1,
       "cost": {"original_generation_usd": 0.001296, "incurred_usd": 0.001296}}
    ]
  },
  "estimated_cost_usd": 0.001296,
  "cost": {"currency": "USD", "pricing_source": "Tarifas públicas de lista…",
           "original_generation_usd": 0.001593, "incurred_usd": 0.001296, "saved_usd": 0.000297},
  "cache": {"status": "partial", "phases": {"preprocessing": "hit", "estimation": "miss"}},
  "fallback_used": false,
  "latency_ms": 5210,
  "generated_at": "2026-09-28T12:00:05Z",
  "preprocessing": "two_phase",
  "extracted_requirements": "### Requisitos funcionales\n- ...",
  "evaluation": {"score": 1.0, "truncated": false, "issues": [], "...": "..."}
}
```

### `POST /api/v1/estimate/stream` — contrato SSE

Mismo cuerpo que `/estimate`. La solicitud se valida **antes** de abrir el stream: los
errores de validación (campos, límites, modelo no permitido o sin proveedor configurado,
parámetros no soportados) devuelven `422` JSON normal. Una vez abierto (`200`,
`Content-Type: text/event-stream`), todo llega como eventos:

```
event: <tipo>
data: <JSON en una línea>

```

| Evento | Cuándo | `data` |
|---|---|---|
| `start` | Siempre, primero | `{"request_id", "preprocessing", "route": ["openai/gpt-4o-mini", …]}` |
| `extraction` | Solo `two_phase`, al terminar la fase 1 | `{"phase": "preprocessing", "text", "cache"}` — **nunca** se mezcla con los `delta` |
| `delta` | 0..n veces | `{"text": "<fragmento de la estimación>"}` |
| `metadata` | Tras el último `delta` de una generación completa | Igual que la respuesta de `/estimate` **sin** `estimation` (modelo y proveedor reales, tokens por fase, latencia, `finish_reason`, caché, costes, evaluación) |
| `done` | Último evento en caso de éxito | `{"status": "completed"}` |
| `error` | Último evento si algo falla tras abrir el stream | `{"code", "message", "status", "retryable", "partial"}` |

- Solo `done` significa estimación completa. `error` con `partial: true` indica que ya se
  habían emitido `delta`: ese texto **no** es una estimación válida. Si la conexión se
  cierra sin `done` ni `error`, el cliente debe tratarlo como **interrupción**.
- Los mensajes de `error` son fijos y saneados (`provider_auth`, `provider_timeout`,
  `provider_rate_limited`, `provider_rejected_request`, `provider_empty_response`,
  `provider_unavailable`, `provider_error`, `stream_interrupted`, `model_not_allowed`,
  `internal_error`); nunca incluyen textos de SDK.
- Durante esperas largas (p. ej. la fase 1) se envían comentarios `: keep-alive`.
- El texto viaja como JSON (saltos de línea y espacios escapados); aun así, el cliente
  implementa la especificación completa (varias líneas `data:` unidas con `\n`, CR/LF/CRLF,
  eliminación de un único espacio tras `:`, comentarios) en `estimator_client/sse.py`.
- Si el cliente se desconecta, el servidor cancela la generación, cierra el stream del
  proveedor, lo registra (`stream_interrupted`) y **no** escribe nada en caché.
- Un `finish_reason` de truncamiento (`length`, `max_tokens`) llega como `done` porque la
  transmisión terminó bien, pero `metadata.evaluation.truncated` es `true` (el chat lo
  marca como estimación incompleta) y el resultado no se guarda en caché.

```bash
curl -N -X POST http://localhost:8000/api/v1/estimate/stream \
  -H "Content-Type: application/json" -H "Accept: text/event-stream" \
  -d '{"transcription": "El cliente quiere una tienda online con pagos y envíos a domicilio."}'
```

### `GET /api/v1/context`

Configuración pública para clientes (sin credenciales): el system prompt para las
opciones dadas (`preprocessing`, `example_format`, `num_examples`, `use_examples`), el
prompt de extracción si aplica, los ejemplos incluidos, modelos primario/secundario y
permitidos, si la caché está activa y los límites de validación. El chat lo usa para su
barra lateral.

### `GET /health`

Sonda de vida: `status`, entorno, proveedor/modelo primario, modelo secundario y
`cache: {enabled, reachable}` (ping a Redis acotado por timeout). Sigue siendo `healthy`
sin Redis.

## Modelos, fallback y reintentos

- Cada modelo es **proveedor + nombre**. El proveedor se toma del prefijo
  (`openai/…`, `anthropic/…`) o se infiere (`gpt-*`, `chatgpt-*`, `o1*`/`o3*`/`o4*` →
  OpenAI; `claude-*` → Anthropic). Las credenciales se eligen por el proveedor real de
  cada modelo; un modelo cuyo proveedor no tiene clave se rechaza con `422`.
- **Ruta** de una solicitud (candidatos en orden; el primero siempre se intenta antes):
  - sin `model` → `[primario, secundario]`;
  - con `model` → exactamente `[model]` (se respeta el modelo pedido);
  - con `model` y `allow_fallback: true` → `[model, secundario]`.
- **Política de errores** (`app/llm/errors.py`):

  | Error | Reintento mismo modelo | Fallback |
  |---|:-:|:-:|
  | timeout, rate limit (429), no disponible (5xx, conexión) | sí | sí |
  | autenticación/permisos, respuesta vacía, error desconocido | no | sí |
  | solicitud rechazada (400/404/422 del proveedor) | no | no |
  | fallo de stream **después** de emitir contenido | no | no |

  Reintentos: hasta `LLM_MAX_RETRIES`, con backoff exponencial `LLM_RETRY_BACKOFF_SECONDS
  · 2^n` (máx. 10 s). Los SDK tienen sus reintentos internos desactivados para que la
  política sea única y predecible. Timeout: `LLM_TIMEOUT_SECONDS` por intento; en streaming
  es el máximo sin recibir fragmentos.
- **Streaming**: el fallback solo ocurre antes del primer fragmento. Si el proveedor falla
  después, se emite `error` (`stream_interrupted`, `partial: true`) en vez de cambiar de
  proveedor y mezclar dos respuestas.
- Los metadatos informan `model` (el que reporta el proveedor), `requested_model`,
  `provider`, `fallback_used` y `attempts` por fase.

## Caché Redis

Caché de **coincidencia exacta** de llamadas al LLM (`app/cache/result_cache.py`):

- **Clave**: `<CACHE_PREFIX>:v<versión>:llm:<sha256>` sobre una serialización JSON
  canónica (claves ordenadas, separadores fijos, UTF-8) de: prompt de sistema completo
  (que ya incluye ejemplos, formato y limpieza), mensaje de usuario, límite de salida, la
  **ruta de modelos** en orden (proveedor y modelo de cada candidato) y los parámetros fijos
  de cada adaptador (temperatura de OpenAI, límite por defecto de Anthropic). Cambiar un
  prompt, un ejemplo, el modelo, el secundario o el límite produce otra clave.
- **Cambios de configuración de modelos**: como la ruta forma parte de la clave, cambiar
  `LLM_MODEL` o `LLM_FALLBACK_MODEL` no reutiliza entradas de la configuración anterior.
  Un resultado generado por el secundario se guarda con su modelo real y `fallback_used`.
- **Dos fases**: extracción y estimación se cachean como llamadas independientes; la
  respuesta informa el estado de caché **por fase** (`cache.phases`) y un resumen
  (`hit`, `partial`, `miss`, `disabled`, `error`).
- **Qué se guarda**: solo generaciones completas y confirmadas (texto no vacío y
  `finish_reason` en `stop`/`end_turn`/`stop_sequence`). No se guardan errores,
  respuestas vacías, truncadas, con finalización desconocida ni streams interrumpidos.
  Se guardan los metadatos reales (modelo, proveedor, tokens —`null` si se desconocen—,
  latencia y coste original).
- **Streaming y generación normal comparten entradas**: ambos guardan el mismo registro
  (el texto se normaliza sin espacios extremos). Un acierto por SSE emite el mismo contrato
  (`start`, `delta`, `metadata`, `done`).
- **Peticiones idénticas concurrentes** (mismo proceso): la primera llama al proveedor y las
  demás esperan su resultado (estado `shared`), como máximo `LLM_INFLIGHT_WAIT_SECONDS`; si
  la primera falla, se interrumpe o tarda más, las demás generan por su cuenta.
- **Robustez**: cada operación Redis tiene timeout (`REDIS_TIMEOUT_SECONDS`); errores o
  indisponibilidad devuelven estado `error` y la solicitud continúa sin caché; tras un fallo
  no se consulta Redis durante `CACHE_RETRY_AFTER_SECONDS`. Entradas corruptas o de otra
  versión de esquema se tratan como fallo de caché y se borran.
- **Invalidación**: expira por TTL; para invalidar todo al cambiar el formato, se sube
  `CACHE_SCHEMA_VERSION`; para una limpieza manual, cambia `CACHE_PREFIX` o vacía Redis.

## Costes y métricas

Fuente única de precios: `app/llm/pricing.py` (tarifas públicas de lista en USD por millón
de tokens, ampliables con `LLM_PRICING_OVERRIDES`). Coincide por `proveedor/modelo` o por
instantánea fechada del mismo modelo. Un modelo sin tarifa → coste `null`.

| Campo | Significado |
|---|---|
| `cost.original_generation_usd` | Coste estimado de generar el resultado desde cero (suma de fases, aunque hoy se sirvan de caché) |
| `cost.incurred_usd` = `estimated_cost_usd` | Coste estimado de **esta** solicitud: fases reutilizadas cuentan `0` |
| `cost.saved_usd` | Coste original de las fases reutilizadas (ahorro estimado) |
| `usage.{input,output,total}_tokens` | Tokens de la generación (suma de fases) |
| `usage.incurred_*_tokens` | Tokens consumidos por esta solicitud |
| `usage.phases[].cost` | Lo mismo por fase |

Cualquier agregado que dependa de un valor desconocido es `null`, nunca `0`. Los intentos
fallidos (reintentos) se consideran no facturados: los proveedores no cobran las
solicitudes rechazadas, pero un timeout puede haber consumido tokens que no se reportan.

## Observabilidad

Logs estructurados (`app/observability.py`): legibles en desarrollo y JSON (una línea por
evento) con `APP_ENV=production` o `LOG_FORMAT=json`. Todos llevan `request_id` (se acepta
la cabecera `X-Request-ID` o se genera, y se devuelve en la respuesta y en el evento
`start`). Eventos principales: `http_request_started/completed/failed`,
`estimation_started/completed`, `llm_call_started/completed` (proveedor y modelo reales,
tokens, latencia, coste, estado de caché, intentos), `llm_attempt_failed`, `llm_fallback`,
`cache_hit/miss/store/skip_store/error/corrupt_entry`, `llm_inflight_join`,
`stream_completed/failed/interrupted`. Nunca se registran credenciales, transcripciones
ni prompts (solo tamaños y opciones), ni mensajes de excepciones de SDK (solo su tipo).

## Cambios de contrato y transición

`/api/v1/estimate` conserva todos sus campos y valores por defecto. Cambios:

| Cambio | Motivo | Transición |
|---|---|---|
| Campos nuevos: `request_id`, `cost`, `cache`, `fallback_used`, `usage.incurred_*`, y por fase `provider`, `requested_model`, `cache`, `generated_at`, `original_latency_ms`, `fallback_used`, `attempts`, `cost` | Metadatos explícitos | Aditivo |
| `estimated_cost_usd` deja de ser siempre `null`: es el coste incurrido por la solicitud (`0` en un acierto; `null` si se desconoce) | Tabla de precios centralizada | Mismo tipo (`float \| null`) |
| Tokens (`usage.*`, `phases[].*_tokens`) y `model` pueden ser `null` si el proveedor no los informa (solo posible en streaming) | No presentar desconocidos como `0` | Los clientes deben admitir `null` |
| Un `model` sin prefijo y con proveedor no inferible (p. ej. `modelo-que-no-existe`) → `422` antes de llamar al proveedor (antes `400` tras llamarlo) | Selección de credenciales por proveedor | Usa `openai/<modelo>` o `anthropic/<modelo>` |
| Campos desconocidos: se aceptan pero se informan en `X-Ignored-Fields` | No ignorar en silencio | En `/estimate/stream` se rechazan |
| La interfaz Streamlit ya no lee claves (`st.secrets`/`.env`) | Separación cliente/servidor | Configura `ESTIMATOR_API_BASE_URL` |

## Tests y calidad

```bash
uv run pytest -v
uv run ruff check .
```

Ninguna prueba llama a proveedores reales ni a Redis: se usan dobles
(`tests/_fakes.py`: `FakeProvider`, `FakeRedis`, SDK simulados). Cubren la separación
cliente/servidor (incluido un proceso que bloquea cualquier import del backend, SDK o Redis),
el contrato SSE (multilínea, finalización, error, interrupción, desconexión), reutilización
de caché, claves, TTL, Redis caído o lento, entradas corruptas, compatibilidad
streaming/normal, fallback y política de modelo explícito, costes y estados de caché en una
y dos fases, validaciones, evaluación, errores saneados y que el event loop no se bloquea.
El CI (`.github/workflows/estimador-cag-ci.yml`) ejecuta lint y tests, construye ambas
imágenes, comprueba que corren sin root, que la imagen `ui` no contiene backend, SDK ni
Redis, y que la API queda `healthy` sin Redis.

## Limitaciones

- La deduplicación de peticiones idénticas concurrentes es por proceso; entre réplicas
  solo se comparte lo ya escrito en Redis (no hay bloqueo distribuido).
- Una petición idéntica que espera a otra en streaming no recibe fragmentos hasta que la
  primera termina (luego recibe el texto completo).
- `thinking_budget` y otros parámetros de razonamiento no están implementados.
- Las tarifas son de lista y pueden quedar desactualizadas: revisa `app/llm/pricing.py` o
  usa `LLM_PRICING_OVERRIDES`. El coste de intentos fallidos no se contabiliza.
- Sin autenticación en la API (fuera del alcance); restringe modelos con `ALLOWED_MODELS`.
- `two_phase` duplica llamadas y latencia; la estimación no ve la transcripción original.
- La evaluación valida forma y aritmética, no la calidad del contenido.
- `num_examples` toma los primeros ejemplos del catálogo; no hay selección por similitud.
- La inferencia de proveedor por nombre cubre los prefijos conocidos; otros modelos
  necesitan el prefijo `proveedor/`.
