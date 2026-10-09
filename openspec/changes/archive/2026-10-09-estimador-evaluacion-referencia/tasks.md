# Tasks

Todas las verificaciones se ejecutan en contenedores Docker (`docker compose -f docker-compose.verify.yml ...`).

## 1. Dataset

- [x] 1.1 Crear `evals/dataset.py` (modelos Pydantic estrictos y `load_dataset`) y `evals/datasets/reference_v1.json` con los 16 casos; verificar con `tests/evals/test_dataset.py` (cobertura por categoría, identificadores únicos, caso inválido, expectativas obligatorias).

## 2. Métricas

- [x] 2.1 Crear `evals/metrics.py` (`schema_adherence`, `cost_bounds`, `content_recall`, `evaluate_case`); verificar con `tests/evals/test_metrics.py` (aprobado, cada incoherencia, rangos, fuera de alcance, recall parcial, alternativas y acentos).

## 3. Runner y reporte

- [x] 3.1 Crear `evals/runner.py` (cliente `TestClient` o HTTP, modos, selección, reporte JSON, código de salida) y `evals/__main__`/uso `python -m evals.runner`; verificar con `tests/evals/test_runner.py` (actor, acb, sesiones independientes, límite, exportación, fallo y error, rechazo esperado, URL HTTP con transporte simulado).
- [x] 3.2 Probar el runner de extremo a extremo en proceso con proveedores simulados mediante el servicio `api-eval`; registrar el comando y el resultado.

## 4. Cierre

- [x] 4.1 Documentar el uso en el README (comandos Docker); ejecutar `ruff`, `pytest` y `openspec validate --all --strict` en contenedores y registrar el resultado en `verification.md`.
