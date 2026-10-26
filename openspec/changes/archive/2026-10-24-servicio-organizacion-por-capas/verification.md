# Verification

Todo se ejecutó en Docker desde la raíz del repositorio, en la rama `session_07/refined`.

| Comando | Resultado |
|---|---|
| `docker compose -f docker-compose.verify.yml build api-test` | Imagen reconstruida (la anterior no tenía `tiktoken`, ya declarado en `pyproject.toml`) |
| `docker compose -f docker-compose.verify.yml run --rm api-test` (línea base, antes de tocar nada) | 1105 passed, 13 skipped |
| `docker compose -f docker-compose.verify.yml run --rm api-test` (tras el cambio) | **1107 passed, 13 skipped** (+2 de `test_layer_dependencies.py`) |
| `docker compose -f docker-compose.verify.yml run --rm api-lint` | All checks passed! |
| `docker compose -f docker-compose.verify.yml run --rm openspec validate servicio-organizacion-por-capas --strict` | Change is valid |

## Contraste con la spec

- **Capas del servicio**: `app/` contiene `foundation/`, `domain/`, `generation/{cag,rag,agentic,conversation}`, `ingestion/` y `api/`; `app/services`, `app/routers` y `app/schemas` ya no existen. `tests/test_project_structure.py` actualizado.
- **Contratos HTTP intactos**: no se modificó ninguna aserción sobre rutas ni JSON; solo imports, rutas de módulos en `mocker.patch` y los parches de `get_settings` (que ahora apuntan a `app.dependencies`).
- **Reglas de dependencias**: `tests/test_layer_dependencies.py` pasa con siete aristas de deuda documentadas.
- **Composition root**: `get_pipeline`, `get_session_estimation_service`, `get_actor_critic_boss`, `get_history`, `close_history`, `get_session_store`, `reset_session_store`, `get_chunker` y `get_embedder` están en `app/dependencies.py`; los tests existentes las sustituyen con `dependency_overrides`.
- **Placeholders**: `generation/rag/store/__init__.py` y `generation/rag/retriever.py` solo contienen docstring.
- **Documentación**: `estimador-cag/ARCHITECTURE.md` y `CLAUDE.md`.

## Notas

- Los artefactos del change se redactaron una vez la reorganización estaba hecha y verde; las tareas reflejan el trabajo realizado.
- Dos correcciones surgieron al ejecutar la suite: `migrate.py` calculaba `alembic.ini` con `parents[2]` (ahora `parents[3]` por la nueva profundidad) y `get_session_store` debe leer `app.config.get_settings()` en vivo, porque `tests/test_session_state_api.py` fija `SESSION_MAX_TURNS` por variable de entorno.
