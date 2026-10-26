# Verification

Todo se ejecutó en Docker desde la raíz del repositorio, rama `session_07/refined`.

| Comando | Resultado |
|---|---|
| `docker compose -f docker-compose.verify.yml run --rm api-uv lock` | `nltk 3.10.4` (más `joblib`, `cloudpickle`) añadido a `uv.lock` |
| `docker compose -f docker-compose.verify.yml build api-test` | Imagen reconstruida con los datos de Punkt |
| `docker compose -f docker-compose.verify.yml run --rm --entrypoint python api-test -c "import nltk; print(nltk.data.find('tokenizers/punkt_tab'))"` | `/opt/nltk_data/tokenizers/punkt_tab` (descargado al construir la imagen, no en ejecución) |
| `docker compose build estimador-cag` + `docker run --rm -e OPENAI_API_KEY=sk-test-dummy --entrypoint python estimador-cag:latest scripts/compare_chunkers.py --show-stats` | La imagen de producción incluye `NLTK_DATA`, `scripts/` y `data/`; imprime la tabla de las 5 estrategias gratuitas |
| `docker compose -f docker-compose.verify.yml run --rm api-lint` | All checks passed! |
| `docker compose -f docker-compose.verify.yml run --rm api-test` | **1164 passed, 13 skipped** (línea base 1107 tras el change de capas: +57 pruebas) |
| `docker compose -f docker-compose.verify.yml run --rm openspec validate comparacion-estrategias-chunking --strict` | Change is valid |

## Contraste con la spec

- **Interfaz y estrategias**: `tests/test_chunking_strategies.py` cubre las ocho estrategias (forma de los chunks, solapamiento, ventana de frases, jerárquica padre/hijo, corte semántico, proposicional con modelo configurable y fallo degradado, contextual con `cache_control`, coste con escritura/lectura de caché) y que las ocho emiten el mismo evento `chunking_done`.
- **Embedder**: `tests/test_embeddings_pipeline.py` verifica lotes de 100 (250 → 100/100/50), orden por `index`, `dimensions` enviado, valores por defecto de `Settings`, reintentos 1 s/2 s/4 s y propagación de otros errores.
- **Comparación**: estadísticas (huérfanos/obesos/percentiles/coste), orden del top-k, `level`/`parent_chunk_id`, memoización (un único chunking y un único embedding de chunks) y `use_embedder`.
- **Endpoint**: 200 por defecto con las 5 gratuitas, top-k, 400, 503 (clave de estrategia y clave de embeddings), 500 genérico sin filtrar texto interno, 422 y presencia en OpenAPI; `/embeddings/ingest` sigue devolviendo 200.
- **CLI**: `tests/test_compare_chunkers_cli.py` (9 pruebas): gratuitas sin claves, filtros, coste, top-k, informe, dimensiones, padres y códigos de salida.
- **Corpus**: el corpus de casos límite produce chunks obesos (estructural) y huérfanos (`sentence_window`). Informe real de las gratuitas en `app/generation/rag/COMPARISON_REPORT.md`.

## Limitaciones declaradas

- Las estrategias de pago (`semantic`, `propositional`, `contextual_retrieval`) y el top-k real **no se han ejecutado contra proveedores** en esta rama (no hay claves en el entorno); están probadas con embedder y clientes falsos. El comando para generar el informe completo está en el README y en el propio informe.
- El `CMD` del `Dockerfile` apuntaba a `app.persistence.migrate` tras el change de capas; se corrigió en un commit aparte (`fix(docker)`) y se comprobó arrancando la imagen.
- El CI nativo (`uv sync`) descarga Punkt con un paso nuevo antes de las pruebas.
