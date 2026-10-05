# Software Estimation CAG API

FastAPI backend que genera estimaciones iniciales de proyectos de software con
OpenAI o Anthropic. Ofrece dos flujos:

- **Estimación estructurada** (`POST /api/v1/estimate`): una descripción breve más
  tipo de proyecto, nivel de detalle y formato de salida. El prompt se renderiza
  desde plantillas Jinja2 versionadas (`app/prompts/estimation/<versión>/`).
- **Estimación desde transcripción** (`POST /api/v1/transcription/estimate` y
  `/stream`): parte de una reunión con el cliente y usa CAG (Context-Augmented
  Generation) con ejemplos históricos.

## ¿Qué es CAG en este proyecto?

CAG inyecta ejemplos históricos de estimaciones **directamente dentro del prompt
del LLM** — sin embeddings, sin vector stores, sin recuperación semántica.
El modelo recibe toda la información de contexto en una sola llamada.

## Arquitectura

### Estimación estructurada

```
POST /api/v1/estimate?prompt_version=v3        ← EstimationPipeline inyectado con Depends
       │
       ▼
EstimationRequest (app.schemas: description, project_type, detail_level,
                   output_format, reference_projects?)
       │
       ▼
1. Guardrails de entrada (PII, prompt injection, moderación)  → 400 {reason, message}
2. Caché exacta (Redis)            ┐ cached=true
3. Caché semántica (redisvl)       ┘ filtrada por versión/tipo/detalle/formato
4. render_estimation_prompt(request, version)   ← app/prompts/estimation/<versión>/*.j2
5. generate_from_prompts(system, user)          ← wrapper: caché, reintentos, fallback, costes
6. Validación de negocio + corrección automática (suma de costes, "Out of scope:")
7. Filtro de fuera de alcance → almacenamiento en ambas cachés
       │
       ▼
EstimationResponse {result: EstimationResult, prompt_version, cached}
```

### Estimación desde transcripción

```
POST /api/v1/transcription/estimate
       │
       ▼
EstimationRequest (app.schemas.estimation: transcripción + opciones validadas)
       │
       ▼
generate_estimation(transcription, GenerationOptions)
       ├── [two_phase] fase 1: extracción de requisitos (llamada async)
       ├── build_system_prompt()   ← ejemplos CAG (n, formato) + limpieza opcional
       ├── _call_openai()   o   _call_anthropic()   (clientes asíncronos)
       └── LLMEstimationResult (tokens y finish_reason por fase)
       │
       ▼
evaluate_estimation()   ← evaluación estructural (regex, sin LLM), opcional
       │
       ▼
EstimationResponse (JSON)
```

## Estructura del proyecto

```
estimador-cag/
├── app/
│   ├── main.py              — FastAPI app, /health, lifespan, Swagger
│   ├── config.py            — BaseSettings + lru_cache + validación por proveedor
│   ├── routers/
│   │   ├── project_estimations.py — POST /api/v1/estimate (contrato estructurado)
│   │   └── estimations.py  — POST /api/v1/transcription/estimate[/stream]
│   ├── schemas/
│   │   ├── project_estimation.py — contrato estructurado (compartido con Streamlit)
│   │   └── estimation.py   — contratos del flujo de transcripción
│   ├── prompts/
│   │   ├── loader.py       — render_estimation_prompt(request, version) -> (system, user)
│   │   └── estimation/
│   │       ├── v1/         — system.j2, user.j2, examples.j2
│   │       └── v2/         — variación de tono y ejemplos
│   ├── services/
│   │   ├── llm_service.py  — prompts, preprocesamiento, dispatch OpenAI/Anthropic
│   │   └── evaluation.py   — evaluación estructural de la estimación
│   └── context/
│       └── examples.py     — catálogo CAG (5 ejemplos estructurados) y formatos
├── tests/
├── Dockerfile              — imagen multietapa, usuario sin privilegios, health check
├── docker-compose.yml      — entorno de desarrollo (hot reload)
├── .dockerignore
├── .env.example
├── pyproject.toml
└── README.md
```

## Requisitos

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) instalado
- API key de OpenAI **o** Anthropic
- (Opcional) Docker con Docker Compose v2 para ejecutar en contenedor

## Instalación

```bash
cd estimador-cag
uv sync --group dev
```

## Configuración

```bash
cp .env.example .env
# Editar .env con tu API key
```

| Variable | Descripción | Default |
|---|---|---|
| `LLM_PROVIDER` | `openai` o `anthropic` | `openai` |
| `LLM_MODEL` | Modelo a usar | `gpt-4o-mini` |
| `OPENAI_API_KEY` | API key de OpenAI | — (requerida si provider=openai) |
| `ANTHROPIC_API_KEY` | API key de Anthropic | — (requerida si provider=anthropic) |
| `APP_ENV` | Entorno | `development` |
| `LOG_LEVEL` | Nivel de logging | `DEBUG` |
| `ALLOWED_MODELS` | Lista (separada por comas) de modelos que una solicitud puede pedir con `model`. Vacío = sin restricción | vacío |

### Selección automática de modelo

Si `LLM_MODEL` no se configura explícitamente (o queda en `gpt-4o-mini`) y
`LLM_PROVIDER=anthropic`, el sistema usa automáticamente `claude-haiku-4-5`.
Para usar otro modelo de Anthropic, configura `LLM_MODEL` explícitamente.

## Ejecución local

```bash
uv run uvicorn app.main:app --reload
```

La API queda disponible en `http://localhost:8000`.

## Interfaz web (Streamlit)

Formulario para probar la estimación estructurada sin curl/Postman/Swagger:
descripción, tipo de proyecto, nivel de detalle, formato de salida y versión
del prompt.

```bash
uv run streamlit run streamlit_app.py
```

Se abre en `http://localhost:8501`. Arranca también la API en otra terminal.
El formulario construye el mismo `EstimationRequest` que valida la API (lo
importa de `app.schemas`), lo envía a `POST /api/v1/estimate/stream` y muestra
la estimación en streaming dentro de un historial. No necesita claves LLM.
Configura `ESTIMATOR_API_BASE_URL` (por defecto `http://localhost:8000`) en
el entorno, `.env` o `st.secrets`; el entorno tiene prioridad. Las claves de
proveedores se configuran únicamente en el backend.

El `st.sidebar` muestra, de solo lectura:

- el system prompt renderizado con las plantillas de la última solicitud (o una
  vista previa con los valores por defecto antes de la primera);
- los ejemplos few-shot que incluye ese prompt;
- las métricas de la última llamada: modelo, versión del prompt, tokens de
  entrada y salida, latencia, coste y si la respuesta vino de caché.

El prompt se renderiza con las plantillas de esta versión del cliente. Si la API
remota tiene otras plantillas, el panel no las refleja. «Borrar historial» limpia
los mensajes y las métricas. Cada solicitud se estima por separado: el historial
visible no se envía al modelo.

Los errores de validación (por ejemplo, una descripción de menos de 20
caracteres) se muestran sin llamar a la API. Los errores de red, HTTP o del
stream se muestran como mensajes genéricos y nunca se guardan como estimaciones.

## Ejecución con Docker

El `.env` **nunca** entra en la imagen (está en `.dockerignore`): las claves se
inyectan al arrancar el contenedor.

### Desarrollo (Docker Compose, con recarga en caliente)

```bash
cp .env.example .env        # completa la API key del proveedor elegido
docker compose up --build   # API: http://localhost:8000  ·  Chat: http://localhost:8501
docker compose ps           # STATUS pasa a "healthy" cuando /health y /_stcore/health responden
docker compose down
```

Levanta `estimador-cag` (API), `estimador-cag-chat` (chat HTTP) y **Redis Stack**
(RediSearch, necesario para la caché semántica) con volumen. Redis no publica su puerto. API y chat montan
`app/` como volumen de solo lectura, así que los cambios de código se aplican
sin reconstruir; si cambian las dependencias (`pyproject.toml`/`uv.lock`),
vuelve a ejecutar `up --build`. El chat espera la API saludable; solo la API
recibe el `.env` con claves. Las entradas de caché caducan por TTL.

Consulta [resiliencia, caché y contrato SSE](docs/resilience-and-streaming.md)
para configurar fallback, precios, razonamiento y presupuesto económico.

### Imagen para ejecución sin Compose

```bash
docker build -t estimador-cag .
docker run --rm -p 8000:8000 --env-file .env estimador-cag
```

Características de la imagen:

- **Multietapa**: una etapa `builder` instala solo las dependencias de producción
  (`uv sync --frozen --no-dev`, respeta `uv.lock`); la etapa `runtime` copia únicamente
  el entorno virtual y `app/`. `uv`, pytest y las herramientas de compilación no
  llegan a la imagen final.
- **Usuario sin privilegios**: el proceso corre como `app` (UID 10001), no como root.
- **Health check**: `GET /health` cada 30 s (sin `curl`, con la biblioteca estándar).
- Si falta la API key del proveedor configurado, el contenedor termina al arrancar con
  un mensaje claro en `docker logs`.

## Uso

### Health check

```bash
curl http://localhost:8000/health
```

### Estimación estructurada

```bash
curl -X POST "http://localhost:8000/api/v1/estimate" \
  -H "Content-Type: application/json" \
  -d '{
    "description": "Marketplace de servicios profesionales con perfiles de freelancers, pagos con comisión, mensajería interna y valoraciones.",
    "project_type": "web_saas",
    "detail_level": "detailed",
    "output_format": "phases_table",
    "reference_projects": [
      {"name": "Portal de reservas", "description": "Agenda, pagos y avisos", "actual_hours": 520}
    ]
  }'
```

Respuesta (`EstimationResult`; el coste total es la suma de las fases):

```json
{
  "result": {
    "summary": "Proyecto mediano con pagos y mensajería…",
    "confidence_pct": 70,
    "phases": [
      {"name": "Diseño", "description": "UX y flujos", "duration_weeks": 3, "cost_eur": 7200},
      {"name": "Desarrollo", "description": "Plataforma y pagos", "duration_weeks": 10, "cost_eur": 24000}
    ],
    "total_duration_weeks": 13,
    "total_cost_eur": 31200,
    "out_of_scope": false
  },
  "prompt_version": "v3",
  "cached": false
}
```

**Fuera de alcance**: con `confidence_pct` < 30 el resumen empieza por `Out of scope:`, `out_of_scope`
es `true` y las fases se reducen a un placeholder `No estimable` (0 EUR, 1 semana); el chat lo
muestra como «No estimable». **Guardrails**: una entrada con correo, teléfono, IBAN, intento de
prompt injection o contenido moderado devuelve `400 {"reason": "…", "message": "…"}` sin tocar
cachés ni proveedor. Detalles y variables en [docs](docs/resilience-and-streaming.md).

**Streaming**: `POST /api/v1/estimate/stream` acepta el mismo cuerpo y el mismo
`?prompt_version`. Un resultado estructurado solo es válido completo, así que emite el evento SSE
`result` (el `EstimationResult`), luego `metadata`
(`prompt_version`, `model`, `provider`, `finish_reason`, `usage`, `latency_ms`,
`cache_hit`, `estimated_cost_usd`, `request_cost_usd`) y `done`. Ante un fallo emite
`error` saneado sin `done`. Las entradas o versiones inválidas dan `422`, y los guardrails `400`, antes del stream.

```bash
curl -N "http://localhost:8000/api/v1/estimate/stream?prompt_version=v2" \
  -H "Content-Type: application/json" \
  -d '{"description": "Portal interno para reservar salas de reuniones en la oficina.", "project_type": "internal_tool", "detail_level": "summary", "output_format": "phases_table"}'
```

| Campo | Valores |
|---|---|
| `description` | 20–2000 caracteres |
| `project_type` | `mobile_app`, `web_saas`, `internal_tool`, `data_pipeline` |
| `detail_level` | `summary`, `medium`, `detailed` (este último pide asunciones por fase) |
| `output_format` | `phases_table` (con `confidence_pct`), `line_items`, `narrative` |
| `reference_projects` | opcional, hasta 5 `{name, description, actual_hours}` |
| `?prompt_version` | query param; `v3` por defecto (`v1` y `v2` siguen disponibles con el contrato JSON añadido). Una versión inexistente → `422` |

**Versionado de prompts**: cada versión es un directorio en `app/prompts/estimation/`
con `system.j2` (rol, reglas y bloques condicionales por formato y detalle, que
incluye `examples.j2`), `user.j2` (envuelve la descripción en `<project_description>`
y recorre `reference_projects`) y `examples.j2` (ejemplos few-shot en el formato
pedido). Crear `v4/` basta para exponer `?prompt_version=v4`. `v3` pide JSON y adapta
resumen y descripciones al formato y detalle; `v1` y `v2` (markdown) reciben al final el
contrato de salida compartido `output_contract.j2`. `v2` usa un tono de consultor de preventa. Cada render emite el evento `prompt_rendered`
con la versión y el SHA-256 del prompt, sin incluir el texto.

### Estimación desde transcripción

```bash
curl -X POST "http://localhost:8000/api/v1/transcription/estimate" \
  -H "Content-Type: application/json" \
  -d '{
    "transcription": "El cliente solicita desarrollar un marketplace de servicios profesionales. Los freelancers podrán publicar perfiles y los clientes contratar servicios. Se requiere sistema de pagos con comisión, mensajería interna, valoraciones y un panel de administración. Stack preferido: React, Node.js, PostgreSQL. Plazo deseado: 5 meses."
  }'
```

Con solo `transcription` el comportamiento es el de siempre (sin preprocesamiento,
2 ejemplos en Markdown, modelo y límite de tokens del servidor); la respuesta añade
campos nuevos pero conserva los anteriores.

### Opciones por solicitud

Todas son opcionales y se validan (`422` si son inválidas).

| Campo | Valores | Default | Efecto |
|---|---|---|---|
| `preprocessing` | `none`, `inline_cleaning`, `two_phase` | `none` | Cómo se prepara la transcripción (ver abajo) |
| `example_format` | `markdown`, `json`, `narrative` | `markdown` | Cómo se representan los ejemplos CAG en el prompt |
| `num_examples` | `0`–`5` | `2` | Cuántos ejemplos del catálogo se incluyen |
| `use_examples` | `true`/`false` | `true` | `false` elimina todo el bloque de ejemplos |
| `model` | nombre de modelo (`[A-Za-z0-9._:/-]`, máx. 100) | `LLM_MODEL` | Modelo para esta solicitud (restringible con `ALLOWED_MODELS`) |
| `max_tokens` | `1`–`16000` | límite del proveedor (OpenAI) / `4096` (Anthropic) | Tokens máximos de salida de la estimación |
| `evaluate` | `true`/`false` | `true` | Incluye la evaluación estructural en la respuesta |

**Preprocesamiento**

- `inline_cleaning`: una sola llamada; el prompt añade instrucciones para ignorar
  charla irrelevante, resolver contradicciones (prevalece lo último dicho) y tratar lo
  implícito como *supuestos*, no como requisitos explícitos.
- `two_phase`: primero una llamada barata (máx. 2000 tokens) extrae los requisitos en
  Markdown; después la estimación se calcula a partir de esa lista. Los requisitos
  extraídos se devuelven en `extracted_requirements` y el consumo de cada fase en
  `usage.phases`.

**Ejemplos CAG**: el catálogo tiene 5 proyectos de tamaño y dominio distintos (de ~110 a
~630 h); `num_examples=n` toma los `n` primeros, ordenados para que cualquier prefijo
mezcle tamaños. Cada ejemplo se define una vez como datos estructurados y de ahí se
derivan los tres formatos, de modo que el total es siempre la suma del desglose. El
formato de **salida** que se pide al modelo siempre es el Markdown en español.

Ejemplo combinando opciones:

```bash
curl -X POST "http://localhost:8000/api/v1/transcription/estimate" \
  -H "Content-Type: application/json" \
  -d '{
    "transcription": "…",
    "preprocessing": "two_phase",
    "example_format": "json",
    "num_examples": 3,
    "max_tokens": 3000
  }'
```

### Ejemplo de respuesta (`two_phase`)

```json
{
  "estimation": "## Estimación: Marketplace de Servicios Profesionales\n\n...",
  "model": "gpt-4o-mini",
  "provider": "openai",
  "finish_reason": "stop",
  "usage": {
    "input_tokens": 4140,
    "output_tokens": 1620,
    "total_tokens": 5760,
    "phases": [
      {"phase": "preprocessing", "model": "gpt-4o-mini", "finish_reason": "stop",
       "input_tokens": 300, "output_tokens": 420, "total_tokens": 720, "latency_ms": 1500},
      {"phase": "estimation", "model": "gpt-4o-mini", "finish_reason": "stop",
       "input_tokens": 3840, "output_tokens": 1200, "total_tokens": 5040, "latency_ms": 5200}
    ]
  },
  "estimated_cost_usd": null,
  "latency_ms": 6700,
  "generated_at": "2026-09-11T15:30:00Z",
  "preprocessing": "two_phase",
  "extracted_requirements": "### Requisitos funcionales\n- ...",
  "evaluation": {
    "sections": {"titulo": true, "supuestos": true, "requisitos_identificados": true,
                 "desglose_de_tareas": true, "resumen": true,
                 "riesgos_e_incertidumbres": true, "preguntas_abiertas": true},
    "sections_in_order": true,
    "has_breakdown_table": true,
    "table_rows": 19,
    "declared_total_hours": 292.0,
    "sum_row_hours_min": 292.0,
    "sum_row_hours_max": 292.0,
    "hours_match": true,
    "range_min": 280.0,
    "range_max": 340.0,
    "range_consistent": true,
    "has_team": true,
    "has_duration": true,
    "finish_reason_ok": true,
    "truncated": false,
    "score": 1.0,
    "issues": []
  }
}
```

`usage.input_tokens/output_tokens/total_tokens` son la suma de todas las fases (en modo
`none` o `inline_cleaning` hay una sola fase, y los totales coinciden con los de antes).

### Evaluación estructural

`evaluation` se calcula con expresiones regulares (sin llamar al LLM) contra el formato
que exige el prompt: encabezado `## Estimación:`, secciones `### Supuestos`,
`### Requisitos identificados`, `### Desglose de tareas`, `### Resumen`,
`### Riesgos e incertidumbres` y `### Preguntas abiertas` (y su orden), la tabla
`| # | Área | Tarea | Horas |` y las líneas *Total estimado*, *Rango recomendado*,
*Equipo recomendado* y *Duración aproximada*. Además:

- **Discrepancias numéricas**: `hours_match` compara el total declarado con la suma de la
  tabla (tolerancia de 1 h; las filas con rango `8–12` suman como mínimo y máximo) y
  `range_consistent` verifica que el total caiga dentro del rango recomendado.
- **Truncamiento**: `truncated` es `true` si el proveedor terminó por límite de tokens
  (`length` en OpenAI, `max_tokens` en Anthropic); en ese caso sube `max_tokens`. Si la
  extracción de la fase 1 se trunca, se anota en `issues`.
- `score` es la fracción de comprobaciones superadas (0–1) e `issues` las describe en
  español. Es una comprobación de forma, no de calidad del contenido.

## Swagger

Documentación interactiva en `http://localhost:8000/docs`.

## Tests

```bash
uv run pytest -v
```

La suite no llama a los proveedores reales (los SDK se simulan). `tests/prompts/` prueba las
plantillas en milisegundos (descripción literal, formato, detalle, referencias, versiones
y log del render). El resto cubre el contrato estructurado, las opciones del
endpoint de transcripción, ambos modos de preprocesamiento, selección y formatos de ejemplos (incluida la
coherencia de totales), la evaluación, los metadatos de respuesta y el mapeo de errores.
El workflow de CI (`.github/workflows/estimador-cag-ci.yml`) ejecuta la suite completa y
además construye la imagen Docker y comprueba que arranca sin root y queda `healthy`.

## Proveedores soportados

| Proveedor | Config | Modelo por defecto |
|---|---|---|
| OpenAI | `LLM_PROVIDER=openai` | `gpt-4o-mini` |
| Anthropic | `LLM_PROVIDER=anthropic` | `claude-haiku-4-5` |

## Seguridad

- API keys cargadas exclusivamente desde variables de entorno / `.env`
- `.env` está en `.gitignore` y `.dockerignore` — nunca se versiona ni entra en la imagen
- Las API keys no aparecen en respuestas HTTP, logs ni trazas de error
- Los errores del proveedor se normalizan antes de enviarse al cliente, sin el mensaje
  original de la excepción: `502` (fallo o autenticación), `504` (timeout), `429`
  (límite del proveedor) y `400` (el proveedor rechazó el modelo u opciones)
- Las llamadas a los proveedores usan clientes asíncronos (`AsyncOpenAI`/`AsyncAnthropic`)
  y no bloquean el event loop
- El contenedor no corre como root

## Limitaciones

- `estimated_cost_usd` siempre es `null` — campo preparado para futura tabla de precios
- Sin autenticación en la API (fuera del alcance); cualquier cliente puede elegir `model`
  y `max_tokens` salvo que se restrinja con `ALLOWED_MODELS`
- `two_phase` duplica las llamadas (y la latencia); la estimación no ve la transcripción
  original, solo los requisitos extraídos
- La evaluación valida forma y aritmética, no la calidad del contenido; con formatos de
  tabla muy distintos al exigido puede no reconocer las filas
- `num_examples` toma los primeros ejemplos del catálogo; no hay selección por similitud
- No hay tiempo de espera configurable para las llamadas al proveedor (se usa el del SDK)
