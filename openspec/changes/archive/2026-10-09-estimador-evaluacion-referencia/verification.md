# Verification

Todas las comprobaciones se ejecutaron en contenedores Docker (nada en el host). Fecha: 2026-10-09.

## Resultados

| Comprobación | Comando (contenedor) | Resultado |
|---|---|---|
| Pruebas de la API | `docker compose -f docker-compose.verify.yml run --rm api-test` | 880 passed, 7 skipped (PostgreSQL real: requiere `TEST_DATABASE_URL`); antes del cambio: 810 passed |
| Lint | `docker compose -f docker-compose.verify.yml run --rm api-lint` | All checks passed |
| Listado del dataset | `docker compose -f docker-compose.verify.yml run --rm api-eval --list` | 16 casos, dos por categoría |
| Caso adversarial real en proceso | `docker compose -f docker-compose.verify.yml run --rm -e MODERATION_ENABLED=false api-eval --case adversarial-01` | `PASS adversarial-01`, 1 evaluado, 1 aprobado, código de salida 0 (el guardrail local rechaza la inyección sin llamar a ningún proveedor) |
| Caso con clave ficticia | `docker compose -f docker-compose.verify.yml run --rm -e MODERATION_ENABLED=false -e LLM_RETRIES=0 api-eval --case saas-01` | `ERR saas-01 HTTP 502: LLM authentication failed`, 0 aprobados, código de salida 1 |
| Selección vacía | `docker compose -f docker-compose.verify.yml run --rm api-eval --limit 0` | código de salida 2 |
| OpenSpec | `docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict` | todos válidos |

## Trazabilidad

| Requisito | Pruebas |
|---|---|
| Dataset de 16 casos, cobertura, identificadores, validación estricta | `tests/evals/test_dataset.py` |
| Expectativas por caso (cifras, fuera de alcance, rechazo) | `tests/evals/test_dataset.py` (también comprueba que solo `adversarial-01` activa los guardrails) |
| `schema_adherence`, `cost_bounds`, `content_recall` | `tests/evals/test_metrics.py` |
| Evaluaciones existentes intactas | `tests/test_evaluation.py` (sin cambios) y `tests/evals/test_metrics.py::test_existing_structural_evaluation_is_unchanged` |
| Modos `actor`/`acb`, sesiones independientes, `TestClient`/URL HTTP | `tests/evals/test_runner.py` |
| Selección (`--limit`, `--case`, `--category`) y exportación | `tests/evals/test_runner.py` |
| Código de salida 0/1/2 y errores por caso | `tests/evals/test_runner.py` |
| Reporte JSON (latencia, métricas, aprobado, resumen, versión del prompt, decisión ACB, errores, totales) | `tests/evals/test_runner.py::test_all_cases_passing_exit_zero_and_write_the_report`, `::test_acb_mode_*`, `::test_api_errors_are_recorded_and_do_not_stop_the_run` |

## Limitaciones y observaciones

- **No se ha ejecutado el dataset completo contra un proveedor real**: no hay claves en el entorno de verificación. Las pruebas usan proveedores simulados y los rangos del dataset son una primera calibración que conviene revisar con una ejecución real (`api-eval --mode actor|acb`).
- Las métricas son deterministas y basadas en palabras clave: penalizan sinónimos no previstos; las alternativas (`a|b`) y `min_recall` lo mitigan.
- El modo `acb` multiplica las llamadas al proveedor (crítico y regeneraciones).
