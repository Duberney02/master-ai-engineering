# Tasks

Todo se ejecuta en Docker: `docker compose -f docker-compose.verify.yml run --rm api-test` / `api-lint`.

## 1. Reorganización

- [x] 1.1 Mover los módulos a `foundation/`, `domain/`, `generation/` y `api/` con `git mv` y reescribir imports y cadenas de parche; verificar con la suite completa.
- [x] 1.2 Dividir `cache.py` en `foundation/llm/cache.py` y `generation/cag/exact.py`.
- [x] 1.3 Corregir rutas relativas por la nueva profundidad (migraciones) y `tests/test_project_structure.py`.

## 2. Composition root

- [x] 2.1 Mover las fábricas a `app/dependencies.py` y actualizar routers, `main.py` y pruebas; verificar con la suite.

## 3. Reglas y placeholders

- [x] 3.1 `tests/test_layer_dependencies.py` con `KNOWN_VIOLATIONS` explicadas.
- [x] 3.2 Placeholders de `generation/rag/store/` y `generation/rag/retriever.py`.

## 4. Documentación y verificación

- [x] 4.1 `estimador-cag/ARCHITECTURE.md`, `CLAUDE.md` y actualización de README.
- [x] 4.2 `verification.md`, `openspec validate --strict`, sincronizar specs y archivar.
