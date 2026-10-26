# Tasks

Todo se ejecuta en Docker: `docker compose -f docker-compose.verify.yml run --rm api-test` / `api-lint`.

## 1. Almacén y resolución

- [x] 1.1 `foundation/llm/runtime_config.py`: knobs, `RuntimeModelConfig` (Redis asíncrono, lectura degradable, escritura transaccional), `effective_settings`, `task_model` y proveedor por modelo; settings `available_models`.
- [x] 1.2 Aplicar la resolución en el módulo de LLM (`generate_*`), en el wrapper (SDK según el modelo) y en las tareas: crítico, resumen, anclas y servicio de sesiones.
- [x] 1.3 Pipeline: resolver una vez por solicitud y pasar la copia a la generación; clave exacta y semántica por modelo.

## 2. Caché semántica

- [x] 2.1 `model` como filtro de la entrada y sufijo `_by_model` en el índice; pruebas de aislamiento.

## 3. API

- [x] 3.1 `GET/PUT /api/v1/config/models` con validación todo-o-nada, errores 422/400/503 y auditoría; `get_runtime_config` y chunkers en el composition root.

## 4. Pruebas y verificación

- [x] 4.1 Pruebas del almacén, de la resolución, del enrutado por proveedor, del fallback, del pipeline y de la API (`fakeredis`).
- [x] 4.2 Comprobación con Redis y Redis Stack reales en Docker (overrides entre procesos y aislamiento de la caché semántica con nombres de modelo con guiones).
- [x] 4.3 README, `.env.example`, `ARCHITECTURE.md`, `verification.md`, `openspec validate --strict`, sincronizar specs y archivar.
