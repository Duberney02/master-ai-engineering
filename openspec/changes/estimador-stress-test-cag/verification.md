# Verification

Entorno: Docker (`docker-compose.verify.yml`; API del Compose raíz con Redis y PostgreSQL). Rama `feature/pre-session-06`, base `feature/session_5_refined`.

| Comprobación | Resultado |
|---|---|
| `api-test` (pytest completo) | 1008 passed, 7 skipped |
| `api-lint check .` | 1 aviso E501 en `app/services/anchors.py`, preexistente en la rama base; 0 en el código nuevo |
| `openspec validate --all --strict` | 31 passed, 0 failed |
| Medición real | `api-stress --http http://host.docker.internal:8000 --scenarios growing,pivot,contradiction --attachment-sizes 0,5,20,50,100 --repeats 3 --workers 4`: 900 filas, 45 sesiones, gpt-4o-mini-2024-07-18, 1,11 USD |

## Requisitos

- **turn-observability**: `tests/test_turn_observed.py` (campos, índice > ventana, turno fallido sin evento, `last_turn`, `include_memory`, sin texto en el evento).
- **stress-scenarios**: `tests/test_stress_scenarios.py` (20 turnos por perfil, N admitidos, pivote en el turno 5, 30.000 → 80.000, tracker, PDFs deterministas y tamaños).
- **stress-metrics**: `tests/test_stress_metrics.py` (éxito, fallo, límites inclusivos, coste nulo, presupuestos inválidos, snapshot no posterior).
- **stress-runner**: `tests/test_stress_runner.py` y `tests/test_stress_report.py` (matriz, fila por turno, error 502 sin cortar la sesión, uso incorrecto, reporte).

## Bloqueos y desviaciones reales

- `master` no tiene la memoria con resumen/anclas ni los evals: la rama parte de `feature/session_5_refined`.
- El enunciado nombra `estimate_conversational()`, `evals/run.py`, `MAX_ATTACHMENT_CHARS=60.000` y cachés exacta/semántica por turno; no existen. Equivalentes y límite real (80.000, rechazo 413) en `design.md` y `REPORT.md`.
- El hit semántico es 0 por construcción; el exacto procede de la caché de completions de Redis al repetir sesiones idénticas, por lo que latencia y coste se calculan solo sobre sesiones frías (26 de 45).
- 26 de 900 turnos devolvieron 502 (validación agotada, 24 en `contradiction`); se conservan en el CSV con su error.
- Una primera ejecución en el host (sin Redis) se descartó al pasar a Docker.
