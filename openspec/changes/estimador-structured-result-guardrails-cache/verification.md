# Verification

## Entorno

Smart App Control de Windows bloquea los intérpretes de Python sin firma (error 4551), por lo que las pruebas se ejecutan dentro de Docker (`ghcr.io/astral-sh/uv:python3.11-bookworm-slim`, entorno en un volumen para no tocar el `.venv` del host). Línea base antes del cambio: 306 pruebas en verde.

## Resultados

| Comprobación | Resultado |
|---|---|
| `pytest -q` (suite completa, sin claves reales) | 408 passed |
| `python -m compileall -q app streamlit_app.py` | correcto |
| `docker compose config` | válido |
| `git diff --check` | sin errores de espacios (solo avisos de fin de línea CRLF de Git) |
| `openspec validate --all --strict` | 6 passed, 0 failed |
| Redis Stack real (`redis/redis-stack-server`) con `redisvl` | acierto exacto, acierto cercano (similitud 0,9987), fallo lejano, aislamiento por `prompt_version` y `detail_level`, y `log_only` correctos |
| Pipeline completo contra Redis Stack real (generación y embeddings simulados) | 4 solicitudes → 2 generaciones; `cached` = [false, true (exacta), true (semántica), false] |

## Trazabilidad

- Resultado tipado y respuesta `{result, prompt_version, cached}`: `tests/test_validation.py`, `tests/test_project_estimations.py`.
- Validación y corrección automática: `tests/test_validation.py`, `tests/test_pipeline.py` (segundo intento con error y respuesta previa, suma de uso, agotamiento → 502).
- Guardrails y 400 con `reason`/`message`: `tests/test_guardrails.py`, `tests/test_project_estimations.py`, `tests/test_pipeline.py` (no se consulta ninguna caché).
- Fuera de alcance: `tests/test_validation.py`, `tests/test_project_estimations.py`, `tests/test_streamlit_app.py` («No estimable» sin cifras).
- Caché semántica (umbral, aislamiento, `log_only`, TTL, fallos): `tests/test_semantic_cache.py` y la comprobación contra Redis Stack real.
- Pipeline inyectable: `tests/test_pipeline.py` y `test_pipeline_is_injectable_with_dependency_overrides`.
- Prompt `v3` y contrato JSON compartido: `tests/prompts/test_estimation_v3.py`.

## Límites

- No se hicieron llamadas reales a OpenAI ni a Anthropic: moderación, embeddings y generación se simulan. La forma de las llamadas (`moderations.create`, `embeddings.create` con `dimensions`) sigue la API documentada pero no se ha ejercitado en vivo.
- La moderación y los embeddings requieren `OPENAI_API_KEY`; con Anthropic como único proveedor ambos se omiten.
- El umbral por defecto de similitud (0,92) no está calibrado con datos reales; se recomienda arrancar en `SEMANTIC_CACHE_MODE=log_only`.
- La demo HTML (`sse_demo.html`) solo cubre el streaming de transcripción y no cambia.
- `docker compose up --build` no se ejecutó completo; se validó la configuración y la imagen de Redis Stack por separado.
