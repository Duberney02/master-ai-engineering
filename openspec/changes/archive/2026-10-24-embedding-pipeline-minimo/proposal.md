# Proposal

## Why

La sesión 7 introduce la recuperación semántica sobre presupuestos históricos. Antes de montar una base vectorial hace falta la pieza mínima y comprobable: convertir los presupuestos normalizados en chunks con contexto, vectorizarlos con OpenAI y poder medir a mano qué entiende el modelo como "parecido" (similitud coseno). Este cambio construye solo esa base, en memoria y sin persistencia.

## What Changes

- **Paquete `app/embedding_pipeline/`**: modelos Pydantic v2 (`schemas.py`), `JSONStructuralChunker` (un chunk por componente, con el contexto del presupuesto en el texto y metadatos aparte), `OpenAIEmbedder` (`text-embedding-3-small`, lotes de 100, reintentos ante `RateLimitError`, coste estimado) y el router `POST /embeddings/ingest`.
- **CLI `scripts/compare.py`**: embebe dos textos con el mismo `OpenAIEmbedder` y calcula la similitud coseno con la biblioteca estándar.
- **Datos y validación**: `data/budgets_sample.json` (15 presupuestos) y `SANITY_CHECK.md` con los valores reales de tres parejas de textos.
- **Dependencias y Docker**: `tiktoken` en `pyproject.toml`/`uv.lock`; Compose monta `scripts/` y `data/` para desarrollo.
- **Documentación**: README con construcción, endpoint y CLI dentro y fuera del contenedor.

**No incluido**: otras estrategias de chunking u overlap, comparación de modelos, enriquecimiento con LLM, bases vectoriales (PostgreSQL/pgvector), búsqueda semántica, métricas de retrieval, cambios de interfaz o del backend de negocio. Los vectores no se persisten.

## Capabilities

### New Capabilities
- `estimator/embedding-chunking`: contratos Pydantic y chunking estructural por componente.
- `estimator/embedding-ingest`: embedder de OpenAI y endpoint `POST /embeddings/ingest`.
- `estimator/embedding-compare-cli`: CLI de similitud coseno y comprobación con tres parejas.

### Modified Capabilities
- Ninguna.

## Impact

- Código nuevo: `app/embedding_pipeline/`, `scripts/compare.py`; cambios mínimos en `app/main.py` (registro del router) y `app/logging_config.py` (campos operativos permitidos).
- Dependencias: `tiktoken>=0.7.0` (`openai>=1.0.0` ya existía). Sin NumPy ni scikit-learn.
- El servicio `app.services.embeddings.OpenAIEmbedder` (caché semántica, asíncrono, una cadena) no se toca; el nuevo vive en otro módulo y es síncrono por lotes.
- Las mediciones reales requieren `OPENAI_API_KEY` en `.env`; ningún secreto entra en el repositorio.
