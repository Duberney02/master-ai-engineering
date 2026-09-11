# Software Estimation CAG API

FastAPI backend que genera estimaciones iniciales de proyectos de software
a partir de transcripciones de reuniones con clientes, utilizando CAG
(Context-Augmented Generation) con OpenAI o Anthropic.

## ¿Qué es CAG en este proyecto?

CAG inyecta ejemplos históricos de estimaciones **directamente dentro del prompt
del LLM** — sin embeddings, sin vector stores, sin recuperación semántica.
El modelo recibe toda la información de contexto en una sola llamada.

## Arquitectura

```
POST /api/v1/estimate
       │
       ▼
EstimationRequest (Pydantic, validación min/max)
       │
       ▼
generate_estimation(transcription)
       ├── build_system_prompt()   ← inyecta ESTIMATION_EXAMPLES verbatim
       ├── _call_openai()   o   _call_anthropic()
       └── LLMEstimationResult
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
│   │   └── estimations.py  — POST /api/v1/estimate, schemas Pydantic
│   ├── services/
│   │   └── llm_service.py  — build_system_prompt() + dispatch OpenAI/Anthropic
│   └── context/
│       └── examples.py     — ESTIMATION_EXAMPLES (few-shot)
├── tests/
├── .env.example
├── pyproject.toml
└── README.md
```

## Requisitos

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) instalado
- API key de OpenAI **o** Anthropic

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

### Selección automática de modelo

Si `LLM_MODEL` no se configura explícitamente (o queda en `gpt-4o-mini`) y
`LLM_PROVIDER=anthropic`, el sistema usa automáticamente `claude-haiku-4-5`.
Para usar otro modelo de Anthropic, configura `LLM_MODEL` explícitamente.

## Ejecución

```bash
uv run uvicorn app.main:app --reload
```

La API queda disponible en `http://localhost:8000`.

## Uso

### Health check

```bash
curl http://localhost:8000/health
```

### Generar estimación

```bash
curl -X POST "http://localhost:8000/api/v1/estimate" \
  -H "Content-Type: application/json" \
  -d '{
    "transcription": "El cliente solicita desarrollar un marketplace de servicios profesionales. Los freelancers podrán publicar perfiles y los clientes contratar servicios. Se requiere sistema de pagos con comisión, mensajería interna, valoraciones y un panel de administración. Stack preferido: React, Node.js, PostgreSQL. Plazo deseado: 5 meses."
  }'
```

### Ejemplo de respuesta

```json
{
  "estimation": "## Estimación: Marketplace de Servicios Profesionales\n\n...",
  "model": "gpt-4o-mini",
  "provider": "openai",
  "usage": {
    "input_tokens": 1840,
    "output_tokens": 720,
    "total_tokens": 2560
  },
  "estimated_cost_usd": null,
  "latency_ms": 3200,
  "generated_at": "2026-09-11T15:30:00Z"
}
```

## Swagger

Documentación interactiva en `http://localhost:8000/docs`.

## Tests

```bash
uv run pytest -v
```

## Proveedores soportados

| Proveedor | Config | Modelo por defecto |
|---|---|---|
| OpenAI | `LLM_PROVIDER=openai` | `gpt-4o-mini` |
| Anthropic | `LLM_PROVIDER=anthropic` | `claude-haiku-4-5` |

## Seguridad

- API keys cargadas exclusivamente desde variables de entorno / `.env`
- `.env` está en `.gitignore` — nunca se versiona
- Las API keys no aparecen en respuestas HTTP, logs ni trazas de error
- Los errores del proveedor se normalizan antes de enviarse al cliente

## Limitaciones

- `estimated_cost_usd` siempre es `null` — campo preparado para futura tabla de precios
- Sin autenticación en la API (fuera del alcance)
- Todos los ejemplos históricos se inyectan en cada request; si crecen, aumenta el consumo de tokens
