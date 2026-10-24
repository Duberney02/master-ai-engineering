# Tasks

Todo se construye y ejecuta en Docker desde `estimador-cag/`: `docker compose build estimador-cag` y `docker compose up -d estimador-cag`.

## 1. Preparación

- [x] 1.1 Rama `session-07/pre-exercise`; añadir `tiktoken>=0.7.0` a `pyproject.toml`, regenerar `uv.lock` y añadir `data/budgets_sample.json`.
- [x] 1.2 Compose monta `./scripts` y `./data` (solo lectura); añadir los campos de log a `SAFE_FIELDS`.

## 2. Pipeline

- [x] 2.1 `schemas.py`: modelos Pydantic v2 y validadores.
- [x] 2.2 `chunker.py`: `JSONStructuralChunker`.
- [x] 2.3 `embedder.py`: `OpenAIEmbedder` (lotes, reintentos, logging, coste).
- [x] 2.4 `router.py` y registro en `main.py` con prefijo `/embeddings`.

## 3. CLI

- [x] 3.1 `scripts/compare.py` con coseno manual.

## 4. Verificación

- [x] 4.1 Reconstruir imagen; comprobar `/docs` y `POST /embeddings/ingest` con los 15 presupuestos (200, 422).
- [x] 4.2 Ejecutar las tres parejas con la CLI en el contenedor y registrar los valores reales en `SANITY_CHECK.md`.
- [x] 4.3 Comprobar la CLI fuera del contenedor (`uv run`) si el entorno lo permite.
- [x] 4.4 README actualizado; `openspec validate` y contraste con la especificación.

