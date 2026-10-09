# Verification

Todas las comprobaciones se ejecutaron en contenedores Docker (nada en el host). Fecha: 2026-10-09.

## Resultados

| Comprobación | Comando (contenedor) | Resultado |
|---|---|---|
| Pruebas de la API | `docker compose -f docker-compose.verify.yml run --rm api-test` | 931 passed, 7 skipped (PostgreSQL real: requiere `TEST_DATABASE_URL`); antes del cambio: 880 passed |
| Lint | `docker compose -f docker-compose.verify.yml run --rm api-lint check .` | All checks passed (al introducir Ruff había 21 avisos: 13 de orden de imports, 5 imports sin usar y 3 líneas largas, corregidos) |
| `uv.lock` | `docker compose -f docker-compose.verify.yml run --rm api-uv lock` | resuelve 102 paquetes; añade `fakeredis`, `ruff` y `sortedcontainers` solo al grupo `dev` |
| OpenSpec | `docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict` | 27 passed, 0 failed |
| Compose | `docker compose -f docker-compose.verify.yml config --quiet` y `docker compose config --quiet` | ambos válidos |
| Imagen de producción | `docker build -t estimador-cag:verify estimador-cag` y comprobación dentro del contenedor | se construye; sin `ruff`, sin `fakeredis` y sin `/app/evals` |
| Smoke contra la imagen real | contenedor `estimador-cag:verify` (clave ficticia) + `urllib` dentro del contenedor | `healthy`; OpenAPI incluye `estimate-acb` y `GET /sessions/{id}`; `POST /sessions` 201; estado inicial correcto; sesión desconocida 404; `tier` inválido 422 en ambos endpoints; `estimate-acb` llega al proveedor y devuelve 502 saneado («LLM authentication failed») |
| Evaluación de librerías | `uv pip install --dry-run instructor` / `litellm` en el contenedor `api-uv` | Instructor: 13 paquetes nuevos y cambia `openai`; LiteLLM: 28 paquetes nuevos y cambia `openai` (ver `docs/evaluacion-instructor-litellm.md`) |

## Trazabilidad

| Requisito | Pruebas |
|---|---|
| `APP_ENV` / `LOG_LEVEL` válidos y normalizados | `tests/test_config.py` (defaults, normalización, inválidos, variable de entorno) |
| Caché: ida y vuelta, no ASCII, desactivada, errores de Redis | `tests/test_cache_fakeredis.py` |
| Caché: serialización (corrupto, no objeto, no serializable) | `tests/test_cache_fakeredis.py::test_corrupt_or_non_object_values_read_as_missing`, `::test_unserializable_values_are_not_written_and_do_not_raise` |
| Caché: TTL y caducidad real | `tests/test_cache_fakeredis.py::test_entries_are_written_with_the_configured_ttl`, `::test_ttl_follows_the_setting`, `::test_entries_expire_after_the_ttl` |
| Primitiva de generación estructurada | `tests/test_structured.py` |
| Ruff y servicios Docker de verificación | comandos de la tabla anterior |

## Limitaciones y observaciones

- La evaluación de Instructor y LiteLLM es un análisis de diseño y de dependencias (resolución en seco), no una comparativa de calidad o rendimiento con proveedores reales.
- `ruff format` no se aplica: reformatearía archivos existentes sin relación con este trabajo.
- Mientras se redactaba este trabajo se usó el Python del host únicamente como editor de texto para algunos ficheros (sin instalar ni ejecutar dependencias del proyecto); toda instalación, prueba, lint y validación se ejecutó en contenedores.
