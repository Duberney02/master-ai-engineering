# Proposal

## Why

Quedan huecos de higiene que los otros cambios de esta sesión asumen: la caché de completions no tiene pruebas con un Redis simulado (la serialización y el TTL solo se ejercitan indirectamente), `APP_ENV` y `LOG_LEVEL` aceptan cualquier texto (un typo en `production` desactiva silenciosamente el logging JSON), no hay linter de proyecto y no está decidido qué librerías de generación estructurada conviene adoptar.

## What Changes

- **Pruebas de la caché con FakeRedis**: ida y vuelta, serialización (valores no JSON, no objeto, caracteres no ASCII) y aplicación del TTL, sin Redis real.
- **`APP_ENV` y `LOG_LEVEL` restringidos**: `APP_ENV` ∈ {`development`, `test`, `staging`, `production`}; `LOG_LEVEL` ∈ {`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`}. Se normalizan mayúsculas/minúsculas; cualquier otro valor falla al arrancar con un error claro.
- **Ruff como herramienta de desarrollo**: dependencia del grupo `dev`, configuración en `pyproject.toml` (`E`, `W`, `F`, `I`, longitud 120) y servicio `api-lint` en Docker; el código existente queda sin avisos.
- **Servicios Docker de desarrollo/verificación** (`docker-compose.verify.yml`): pruebas, lint, evaluación, `uv` y el CLI de OpenSpec, sin instalar nada en el host.
- **Evaluación de librerías** (documento de decisión): primitiva de generación estructurada con modelos Pydantic (se adopta la propia, `generate_structured`, ya en uso) frente a Instructor, y LiteLLM frente al wrapper existente. Ninguna se convierte en requisito obligatorio.

**No incluido**: adoptar Instructor o LiteLLM, formateo automático del código existente (`ruff format`), reglas de lint adicionales.

## Capabilities

### New Capabilities
- `estimator/environment-validation`: valores válidos de `APP_ENV` y `LOG_LEVEL`.
- `estimator/development-tooling`: Ruff y servicios Docker de verificación.
- `estimator/completion-cache`: comportamiento verificado de la caché de completions (ida y vuelta, serialización, TTL).
- `estimator/structured-generation`: primitiva de generación estructurada con Pydantic y criterio de evaluación de librerías.

### Modified Capabilities
- Ninguna.

## Impact

- Código: `app/config.py`, `.env.example`; pruebas `tests/test_cache_fakeredis.py`; `pyproject.toml` (`fakeredis` y `ruff` en `dev`); `docker-compose.verify.yml`, `openspec/Dockerfile`; `docs/evaluacion-instructor-litellm.md`.
- Cambio de comportamiento acotado: valores de `APP_ENV`/`LOG_LEVEL` fuera de la lista dejan de arrancar.
- Producción: sin dependencias nuevas (solo `dev`).
