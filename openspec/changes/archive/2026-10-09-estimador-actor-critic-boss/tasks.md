# Tasks

Todas las verificaciones se ejecutan en contenedores Docker (`docker compose -f docker-compose.verify.yml ...`).

## 1. Contrato y plantillas del crítico

- [x] 1.1 Crear `schemas/critic.py` (`CriticIssue`, `CriticFeedback`, enums y validaciones); verificar con `tests/test_critic_contract.py` (valores, `needs_iteration`, `reject`, confianza, normalización).
- [x] 1.2 Crear `prompts/auxiliary/critic/v1/{system,user,feedback}.j2`; verificar con `tests/prompts/test_auxiliary.py`.
- [x] 1.3 Crear `services/critic.py`; verificar con `tests/test_critic_service.py` (entradas del prompt, modelo, reintento, error, sin sesión).

## 2. Boss y orquestación

- [x] 2.1 Añadir `BOSS_MAX_ITERATIONS` a `config.py` y `.env.example`; crear `services/boss.py`; verificar con `tests/test_boss.py` y `tests/test_config.py`.
- [x] 2.2 Separar `draft` y `commit` en `SessionEstimationService` sin cambiar `estimate`; verificar con la suite existente de sesiones.
- [x] 2.3 Crear `schemas/acb.py` y `services/acb.py` (bucle, regeneración con feedback, traza, fallo del crítico); verificar con `tests/test_acb.py` (aceptación, regeneración, rechazo, límite, un único turno, traza).

## 3. API

- [x] 3.1 Añadir `POST /sessions/{id}/estimate-acb` comparando contrato con el endpoint normal; verificar con `tests/test_acb_api.py` (respuesta con traza, errores, historial único, endpoint normal intacto).

## 4. Cierre

- [x] 4.1 Actualizar README; ejecutar `ruff`, `pytest` y `openspec validate --all --strict` en contenedores y registrar el resultado en `verification.md`.
