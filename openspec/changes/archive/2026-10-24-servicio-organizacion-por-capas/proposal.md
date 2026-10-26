# Proposal

## Why

`app/` es plano: `services/` mezcla 23 módulos de naturaleza distinta (fontanería de LLM, cachés, agentes, memoria conversacional, orquestación), las fábricas de dependencias viven repartidas dentro de routers y servicios, y no hay un documento que diga dónde va el código nuevo. Los bloques de la Sesión 7 (chunking, modelos en runtime) añaden módulos nuevos; sin capas nacerían sueltos. La referencia (`ai-engineering`, rama `session_07_live`) organiza el servicio en `foundation/`, `domain/`, `generation/{cag,rag,agentic,conversation}`, `ingestion/` y `api/` con reglas de dependencia explícitas.

## What Changes

- **Reorganización progresiva por capas** (sin cambiar comportamiento): `routers/`→`api/`, `schemas/`→`domain/schemas/`, `prompts/`, `persistence/`, guardrails, adjuntos y wrapper/servicio de LLM→`foundation/`, caché exacta y semántica→`generation/cag/`, Boss y Crítico→`generation/agentic/`, sesiones, anclas, compresión y resumen→`generation/conversation/`, `embedding_pipeline/`→`generation/rag/` y `api/embeddings.py`, conductores y reglas de negocio→`domain/`.
- **Composition root único**: todas las fábricas (`get_pipeline`, `get_session_estimation_service`, `get_actor_critic_boss`, `get_history`, `get_session_store`, `get_chunker`, `get_embedder`) pasan a `app/dependencies.py`.
- **División de la caché**: el almacén Redis genérico (`EstimationCache`, `make_key`) pasa a `foundation/llm/cache.py`; la clave y el modelo de la caché de resultados quedan en `generation/cag/exact.py`.
- **Test de reglas de dependencias** (`tests/test_layer_dependencies.py`) con la deuda actual registrada y explicada.
- **Huecos de la Sesión 8** (`generation/rag/store/`, `generation/rag/retriever.py`): solo placeholders documentados.
- **Documentación**: `estimador-cag/ARCHITECTURE.md` (capas, reglas, flujo, «¿dónde va mi código nuevo?», contratos, mapa de migración) y `CLAUDE.md` en la raíz.

**No incluido**: cambios de comportamiento, de rutas HTTP o de la forma JSON; reescritura de la lógica; vector store y retriever (Sesión 8); reubicar `evals/`, `scripts/` ni los clientes Streamlit.

## Capabilities

### New Capabilities
- `estimator/layered-architecture`: capas del servicio, reglas de dependencia, composition root y huecos reservados.

### Modified Capabilities
- Ninguna: no cambia ningún requisito funcional existente.

## Impact

- Código: casi todo `app/` cambia de ruta; `app/dependencies.py` crece; `tests/` actualiza imports y cadenas de `mocker.patch`; `alembic/env.py` y `scripts/` actualizan imports.
- Las rutas HTTP y los JSON no cambian. Las pruebas existentes siguen verdes sin tocar su lógica.
- Dependencias: ninguna.
