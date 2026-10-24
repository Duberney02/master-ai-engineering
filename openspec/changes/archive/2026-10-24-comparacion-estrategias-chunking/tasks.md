# Tasks

Todo se ejecuta en Docker: `docker compose -f docker-compose.verify.yml run --rm api-test` / `api-lint`. La imagen se reconstruye tras añadir `nltk`.

## 1. Preparación

- [x] 1.1 Añadir `nltk` a `pyproject.toml`, regenerar `uv.lock` con `api-uv lock` y descargar los datos de Punkt en las etapas `builder` y `test` del `Dockerfile` (`NLTK_DATA`); comprobar en el contenedor que `punkt_tab` existe.
- [x] 1.2 Settings `propositional_chunker_model` y `contextual_chunker_model`; campos de log permitidos del chunking.

## 2. Núcleo

- [x] 2.1 Interfaz `Chunker`, helpers de tokens, `chunking_done` y `pricing.py`; migrar el chunker estructural.
- [x] 2.2 Embedder asíncrono con modelo y dimensión configurables; migrar `/embeddings/ingest` y `scripts/compare.py`.
- [x] 2.3 Estrategias gratuitas: `fixed_size`, `recursive`, `sentence_window`, `hierarchical`.
- [x] 2.4 Estrategias de pago: `semantic`, `propositional`, `contextual_retrieval` con clientes inyectables.
- [x] 2.5 Registro de estrategias (gratuitas vs de pago, claves y modelos).

## 3. Comparación

- [x] 3.1 `analysis/similarity.py` y `analysis/comparison.py` (estadísticas, top-k, memoización).
- [x] 3.2 `POST /embeddings/compare` con errores diferenciados y `get_chunker_builder` en el composition root.
- [x] 3.3 `data/test_queries.json` y `data/budgets_stress_cases.json`.
- [x] 3.4 `scripts/compare_chunkers.py`.

## 4. Pruebas, documentación y verificación

- [x] 4.1 Pruebas de estrategias, embedder, comparador, registro, endpoint y CLI con fakes (sin claves reales).
- [x] 4.2 README, `.env.example`, informe `COMPARISON_REPORT.md` con las estrategias gratuitas y rutas de specs actualizadas.
- [x] 4.3 `verification.md`, `openspec validate --strict`, sincronizar specs y archivar.
