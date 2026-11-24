# Design

## Context

`estimador-cag` ya tiene ingesta vectorial (`DocumentStore`, tabla `chunks` con HNSW halfvec) y `POST /search` sin
filtros ni umbral. `estimator/` implementa la Sesión 09 con su propia pila (settings en mayúsculas, LiteLLM +
Instructor, SQLAlchemy síncrono + async). Este cambio porta su **comportamiento**, no su código: se adapta a las
convenciones de `estimador-cag` (settings en minúsculas, SDK asíncronos, capas verificadas por
`tests/test_layer_dependencies.py`, fábricas solo en `app/dependencies.py`, errores saneados).

## Goals / Non-Goals

**Goals:**
- Cerrar el ciclo transcripción → estimación fundamentada tal como lo hace `estimator/` en la Sesión 09.
- Reutilizar `OpenAIEmbedder`, `DocumentStore`/tabla `chunks` y la generación estructurada existente.

**Non-Goals:**
- Búsqueda híbrida, *reranking*, multi-índice y horas por tarea (cambio `session-10-retrieval-avanzado`).
- Citas a nivel de línea, *gate* de alucinaciones y RAGAS (cambio `session-11-calidad-generacion-rag`).
- Cambiar `POST /search`, `/api/v1/*` o los clientes web.

## Decisions

1. **Generación estructurada con la primitiva propia, no Instructor.** `estimator/` usa `LLMWrapper` + Instructor;
   `estimador-cag` ya tiene `foundation/llm/structured.generate_structured` (corrección en la misma conversación, caché,
   *fallback*, costes) y documentó en `docs/evaluacion-instructor-litellm.md` por qué no añade Instructor. Se reutiliza.
   Los validadores Pydantic de `Estimate` provocan la corrección igual que en `estimator/`.
2. **Ubicación por capas.** Reformulador, retriever, ensamblador, *prompt builder*, orquestador, idempotencia y
   observabilidad en `generation/rag/`; esquemas `Estimate`, `EstimationQuery`, `RetrievedChunk`, etc. en
   `generation/rag/schemas.py` (como en `estimator/`); routers finos en `app/api/` (seguridad, *rate limiting* y
   `X-Request-ID` como dependencias/middleware de `api`). Los prompts de reformulación y generación pasan a plantillas
   Jinja en `foundation/prompts/rag/` en lugar de cadenas en código, siguiendo la convención de prompts versionados.
3. **Filtros en SQL sobre JSONB existente.** Los metadatos del chunk (`client_sector`, `year`, id del presupuesto) ya
   están en `chunks.metadata`; se filtra con expresiones JSONB dentro de la misma consulta halfvec para que siga usando
   `chunks_embedding_halfvec_idx`. Alternativa descartada: filtrar en Python tras el k-NN (pierde recall con filtros
   selectivos).
4. **Rate limiting con slowapi en memoria.** Igual que `estimator/`; clave = `X-API-Key` con *fallback* a IP. El
   handler devuelve el JSON y `Retry-After`. Límites por decorador en cada ruta.
5. **Idempotencia con Redis y *fallback* en memoria**, prefijo `idempotency:estimate:` y TTL `idempotency_ttl`. Cliente
   Redis asíncrono (convención del repo), no el síncrono de `estimator/`.
6. **Corpus de tareas.** Se porta `scripts/build_task_corpus.py` (determinista, con semilla) e ingesta vía el
   `DocumentStore` existente, con `chunk_type="historical_task"`, para que la estimación pueda fundamentar tareas finas.

## Risks / Trade-offs

- [El modelo por defecto de `estimator/` (`gpt-5`/`gpt-5-mini`) puede no estar en el catálogo] → los modelos de
  reformulación y generación son settings y se resuelven por el catálogo de runtime existente.
- [slowapi en memoria no se comparte entre workers] → aceptable a escala de curso; documentado.
- [Endpoints deshabilitados si no hay claves] → `.env.example` documenta `RETRIEVAL_API_KEY`/`ESTIMATE_API_KEY` y el
  Compose de desarrollo las define con valores de ejemplo.

## Migration Plan

Sin migración de datos (se reutiliza `chunks`). Despliegue aditivo; *rollback* = quitar los routers nuevos.
