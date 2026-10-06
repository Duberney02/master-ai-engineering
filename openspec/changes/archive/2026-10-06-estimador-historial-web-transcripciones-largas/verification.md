# Verification

## Entorno

Python y Ruby no se ejecutan en el host: todas las comprobaciones corren en Docker.

- Python: `ghcr.io/astral-sh/uv:python3.11-bookworm-slim`, entorno en un volumen y el repositorio montado.
- Rails: `ruby:3.4-slim` con las gemas en un volumen.
- Stack: Compose raíz con un servidor OpenAI falso (`OPENAI_BASE_URL`) para ejercitar generación, moderación y embeddings sin claves ni coste.

Línea base antes del cambio: 408 pruebas Python en verde.

## Resultados

| Comprobación | Resultado |
|---|---|
| `pytest -q` sin PostgreSQL (CI por defecto) | 472 passed, 1 skipped (`test_history_postgres.py`) |
| `pytest -q` con `TEST_DATABASE_URL` hacia el PostgreSQL 17 del stack | 473 passed, 0 skipped |
| `bin/rails test` (Minitest + WebMock) | 61 runs, 302 assertions, 0 failures |
| `docker compose config --quiet` (raíz) | válido; servicios `estimador-cag`, `estimador-cag-chat`, `estimator-web`, `redis`, `postgres` |
| `docker compose up -d --build` | los servicios `healthy` (incluido el chat Streamlit: `/` → 200 en el puerto 8501) (API `/health`, web `/up`, `pg_isready`, `redis-cli ping`) |
| Reinicio del stack sin `-v` | el historial conserva sus 13 registros (volumen `postgres_data`) |
| Entorno de `estimator-web` y `estimador-cag-chat` | sin ninguna variable `OPENAI_*`/`ANTHROPIC_*` |
| Barra lateral Rails (prompt, few-shot, métricas) | cubierta por las suites anteriores; comprobada visualmente en el navegador contra el stack |
| Workflow de CI | YAML válido; jobs `specs`, `test` (con PostgreSQL), `docker`, `web`, `stack` |
| `openspec validate --all --strict` | 10 passed, 0 failed |

### Prueba de extremo a extremo (stack real, LLM simulado)

| Escenario | Resultado |
|---|---|
| Solicitud nueva | 200, `cache_source="none"`, `estimation_id` entero |
| Misma solicitud | `cache_source="exact"` |
| Texto distinto, mismos atributos | `cache_source="semantic"` |
| Mismo texto con otro `detail_level` | `cache_source="none"` (aislamiento por atributos) |
| 80 000 caracteres | 200; la moderación recibió 3 tramos `[30000, 30000, 20000]`; sin caché semántica; repetida → `exact` |
| 80 001 caracteres / 19 caracteres | 422 sin llamar al proveedor |
| Correo en la última línea de 80 000 caracteres | 400 `pii_email` |
| Baja confianza | resultado normalizado `out_of_scope`, coste 0, fase `No estimable`; listado con `out_of_scope=true` |
| `GET /api/v1/estimations` | lista ordenada, sin descripción completa, extracto ≤ 200; `limit=51` → 422 |
| `GET /api/v1/estimations/{id}` | descripción completa y resultado idénticos; inexistente → 404 |
| Web: `/estimations`, `/estimations/:id` | procedencias, «No estimable» sin cifras, `20.000,00 EUR`, `10 semanas`, `70%` y fases |
| Web: POST con `.txt` UTF-8 (CSRF real) | redirige a la estimación; la API guardó el contenido con acentos |
| Web: descripción corta, `.pdf`, correo | 422 con los mensajes esperados; el guardrail 400 de la API se muestra al usuario |

## Trazabilidad

- 80 000 caracteres y validadores: `tests/test_long_transcriptions.py` (límites 19/20/80 000/80 001, 422 sin proveedor), `tests/test_streamlit_app.py` (`max_chars`), `EstimationFormTest`.
- Rechazos de entrada: `tests/test_long_transcriptions.py` (PII al final, inyección en mitad, moderación por tramos), `tests/test_guardrails.py`.
- Baja confianza: `tests/test_validation.py`, `test_low_confidence_long_transcript_is_corrected_and_reported_out_of_scope`, `tests/test_history.py`, controlador Rails (`No estimable` sin cifras).
- Caché semántica (aislamiento, umbral, `log_only`, omisión por longitud): `tests/test_semantic_cache.py`, `tests/test_long_transcriptions.py`.
- Procedencia de caché: `tests/test_pipeline.py`, `tests/test_history.py`.
- Persistencia: `tests/test_history.py` (SQLite en memoria, API, fallos, desactivado) y `tests/test_history_postgres.py` (PostgreSQL real, JSONB y `timestamptz`).
- Cliente web y errores: `test/services/estimator_api_test.rb`, `test/models/estimation_form_test.rb`, `test/controllers/estimations_controller_test.rb`.
- Streamlit (`.txt`, tiempo transcurrido): `tests/test_streamlit_app.py`, `tests/test_streamlit_support.py`.
- Compose raíz: `tests/test_project_structure.py` y el arranque real.

## Hallazgos durante la verificación

- El YAML del workflow tenía dos errores de sintaxis introducidos al editarlo; se detectaron al validarlo con un parser y se corrigieron.
- Un contenedor `estimator-web` de otro proyecto (`ai-engineering`) colisionaba con `container_name`; se eliminaron los nombres fijos del Compose raíz y no se tocó el contenedor ajeno.

## Límites

- No se ejecutó la CI de GitHub: el workflow se validó sintácticamente y sus pasos equivalen a lo ejecutado en local, pero el job `stack` no se probó en un runner.
- El LLM, la moderación y los embeddings estaban simulados; no se validó la calidad de las estimaciones ni el límite real de tokens de los proveedores con 80 000 caracteres.
- No se probó el temporizador ni el indicador de carga en un navegador: se verifican como marcado y script (`#timer`, `#loading`), no su comportamiento visual.
- `create_all` crea la tabla pero no migra esquemas: una base creada antes de añadir la columna `metrics` necesitaría añadirla a mano.
