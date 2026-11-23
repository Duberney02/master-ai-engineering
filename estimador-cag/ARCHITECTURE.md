# Arquitectura del estimador

Contrato de arquitectura del servicio `estimador-cag/`. El código nuevo debe respetarlo. Si una pieza no
encaja en ninguna capa, primero se decide dónde vive (y se actualiza este documento); no se crea una carpeta
suelta en `app/`. Las reglas de dependencias las verifica `tests/test_layer_dependencies.py`.

## 1. Las arquitecturas de IA y por qué componen

El estimador apila tres arquitecturas **de forma aditiva** sobre una base común:

- **CAG** (`app/generation/cag/`): responde sin llamar al LLM cuando ya hay una respuesta equivalente
  (acierto exacto por SHA-256 y acierto semántico por similitud vectorial). Los ejemplos históricos también
  se inyectan en el prompt (Context-Augmented Generation, `foundation/prompts/examples.py`).
- **RAG** (`app/generation/rag/`): convierte presupuestos históricos en chunks y embeddings. La Sesión 7 añade
  la comparación de estrategias de chunking; la Sesión 8 persiste los chunks en PostgreSQL + pgvector y expone la
  búsqueda semántica (`POST /search`). La Sesión 9 cierra el ciclo: recuperación filtrada con umbral
  (`POST /v1/retrieval/search`) y estimación fundamentada con citas desde una transcripción
  (`POST /v1/estimate/from-transcript` y sus etapas `/v1/estimate/stages/*`).
- **Agéntica** (`app/generation/agentic/`): bucle Actor–Crítico–Boss que audita la estimación antes de
  aceptarla, apoyado en la conversación multi-turno (`app/generation/conversation/`).

**Tesis**: estas capas no se conocen entre sí. Solo componen en el **conductor** (`app/domain/`).

## 2. Mapa de capas

```
app/
├── config.py · dependencies.py · main.py   # raíz: settings, composition root, factory FastAPI
├── foundation/     # fontanería técnica, sin opinión de arquitectura IA
│   ├── llm/        #   wrapper (LiteLLM/SDK async, caché de completions, fallback), service, structured,
│   │               #   cache (almacén Redis), embeddings (embedder async), runtime_config (modelos en runtime)
│   ├── prompts/    #   loader Jinja2 + plantillas versionadas (estimation v1–v4, auxiliary, sessions) + ejemplos
│   ├── guardrails/ #   input (moderación, inyección, PII)
│   ├── attachments/#   extracción de texto de PDF/DOCX
│   └── persistence/#   engine SQLAlchemy, modelos, repositorios y migraciones de la ingesta
├── domain/         # contrato y conductor
│   ├── schemas/    #   contratos Pydantic que consumen los clientes (web Go, React, Streamlit)
│   ├── pipeline.py #   conductor de /estimate: guardrails → cag → prompt → llm → validación → cag
│   ├── session_estimation.py · acb.py   # conductores conversacional y Actor–Crítico–Boss
│   └── validation.py · audience.py · history.py · evaluation.py   # reglas de negocio y servicios de dominio
├── generation/     # las arquitecturas que componen
│   ├── cag/        #   exact.py (resultados validados) + semantic.py (redisvl)
│   ├── rag/        #   chunking/ · embedding/ · analysis/ · schemas.py · store/ (S8, índice HNSW halfvec)
│   │               #   S9: retriever · query_reformulator · context_assembler · prompt_builder · validation ·
│   │               #   estimator (orquestador) · idempotency · observability · errors
│   ├── agentic/    #   boss.py + critic.py
│   └── conversation/ # sesiones en memoria, anclas, compresión y resumen
├── ingestion/      # pipeline batch offline (catálogo, loaders, parsers, limpieza, PII, orquestador)
├── api/            # routers finos: transporte, sin lógica de negocio
└── streamlit_client.py · streamlit_support.py   # cliente Streamlit: solo habla HTTP; fuera de las capas
```

Fuera de `app/`: `evals/` (evaluación y stress test, hablan HTTP), `scripts/` (CLIs) y `tests/`.

## 3. Reglas de dependencias

Cada capa solo puede importar de las que tiene por encima. `config.py` no importa nada interno.

| Capa | PUEDE importar | NO PUEDE importar |
|---|---|---|
| `foundation/*` | `config` | `domain`, `generation`, `ingestion`, `api` |
| `domain/schemas/*` | `config`, `foundation` | `generation`, `api` |
| `generation/<x>/*` | `config`, `foundation`, `domain/schemas` | `api`, `dependencies`, **otro hermano de `generation`** |
| `domain/*` (conductor) | `foundation`, `generation/*`, `domain` | `api`, `dependencies` |
| `ingestion/*` | `config`, `foundation`, `domain/schemas`, `generation/rag` | `api`, el conductor |
| `api/*` | `dependencies`, `domain`, `foundation`, `generation`, `ingestion` | lógica de negocio |
| `dependencies.py` | cualquier capa | (solo lo importan `api/`, `main.py`, scripts y pruebas) |

Aristas especiales: `agentic` **puede** importar `conversation` (no al revés), y los hermanos de `generation`
solo se encuentran en el conductor. Si dos capas deben colaborar, el método que las une va en `domain/`.

### Deuda conocida

Siete importaciones de la reorganización incumplen estas reglas y están registradas, con su motivo, en
`KNOWN_VIOLATIONS` de `tests/test_layer_dependencies.py`. La lista solo puede encogerse. Son de dos tipos:
`foundation` que renderiza o valida contratos de `domain/schemas`, y el contrato de sesión que reutiliza tipos
de `domain/audience` y `generation/conversation/sessions`.

## 4. Composition root

`app/dependencies.py` contiene **todas** las fábricas: `get_pipeline`, `get_session_estimation_service`,
`get_actor_critic_boss`, `get_history`/`close_history`, `get_session_store`/`reset_session_store`,
`get_chunker`, `get_embedder` y las de la ingesta (catálogo, cargador, parsers, seudonimizador). Vive por
encima de las capas porque su trabajo es cablearlas. Los routers solo hacen `Depends(...)`, y las pruebas
sustituyen cualquier fábrica con `app.dependency_overrides`.

## 5. Camino de la petición

```
POST /api/v1/estimate
  └─ app/api/project_estimations.py                  (HTTP fino, errores saneados)
       └─ app/domain/pipeline.py::EstimationPipeline
            1. foundation/guardrails/input.py         moderación, inyección, PII
            2. generation/cag/exact.py                acierto exacto
            3. generation/cag/semantic.py             acierto semántico
            4. foundation/prompts/loader.py           prompt versionado
            5. foundation/llm/service.py → wrapper.py generación tipada + re-prompt
            6. domain/validation.py                   reglas de negocio y filtro de fuera de alcance
            7. exact.set() + semantic.store()
```

Las sesiones (`/api/v1/sessions/*`) pasan por `domain/session_estimation.py` (memoria, audiencia, metadatos) y
`/estimate-acb` por `domain/acb.py` (Actor–Crítico–Boss).

La estimación fundamentada de la Sesión 9 no une capas hermanas, así que su orquestador vive dentro de
`generation/rag/` (no en el conductor):

```
POST /v1/estimate/from-transcript                    (X-Request-ID → structlog; X-API-Key; 10/min por clave)
  └─ app/api/estimate.py                              (HTTP fino; cualquier fallo del pipeline → 502 genérico)
       └─ generation/rag/estimator.py::GroundedEstimator
            0. idempotency.py                         Redis asíncrono (o memoria) por idempotency_key
            1. query_reformulator.py                  transcripción → EstimationQuery + texto de búsqueda (en inglés)
            2. retriever.py                           embedding + k-NN halfvec con filtros JSONB y umbral → soft-fail
            3. context_assembler.py                   truncado a max_context_tokens (chunks completos) + <source id=…>
            4. prompt_builder.py → foundation/llm/structured.generate_structured
            5. validation.py                          ids inventados (1 reintento → `low`) y coherencia (1 reparación → 502)
```

`/v1/estimate/stages/{reformulate,retrieve,assemble,generate}` llaman a los mismos métodos de `GroundedEstimator`,
sin estado y sin los reintentos del paso 5. `/v1/retrieval/search` usa solo el paso 2. Cada etapa registra
`rag_stage_started/completed/failed` con `stage`, `duration_ms` y el `request_id`.

## 6. ¿Dónde va mi código nuevo?

| Si añades… | Va en… |
|---|---|
| Backend LLM, plantilla de prompt, guardrail, adjunto, persistencia | `foundation/` |
| Modelo seleccionable en runtime (knob nuevo) | `foundation/llm/runtime_config.py` (`MODEL_KNOBS`) y su ruta en `api/config.py` |
| Estrategia de chunking, embeddings, comparación | `generation/rag/` |
| Vector store (Sesión 8) o retriever | `generation/rag/store/` (`DocumentStore`) y `generation/rag/retriever.py` (`ChunkRetriever`) |
| Etapa del pipeline RAG de estimación (Sesión 9) | `generation/rag/` (método de `GroundedEstimator`) + plantilla en `foundation/prompts/rag/` |
| Seguridad, rate limiting o middleware HTTP | `api/` (`security.py`, `rate_limiting.py`, `request_id.py`) |
| Estrategia de caché | `generation/cag/` |
| Rol de agente | `generation/agentic/` |
| Memoria conversacional | `generation/conversation/` |
| Contrato con los clientes | `domain/schemas/` |
| Paso de orquestación que une capas | `domain/` (nunca un import cruzado) |
| Endpoint HTTP | `api/` (fino) + fábrica en `dependencies.py` |
| Fuente de datos, parser, limpieza offline | `ingestion/` |
| Evaluación o stress test | `evals/` |

## 7. Contratos que no se rompen

- **Rutas HTTP**: `/api/v1/estimate`, `/api/v1/transcription/*`, `/api/v1/sessions/*`, `/api/v1/estimations`,
  `/api/v1/prompts/*`, `/api/v1/ingestion/*`. (`/embeddings/ingest` cambió de contrato en la Sesión 8 —ahora persiste— tras
  comprobar que ningún cliente lo usaba.) Los clientes web Go, React y Streamlit
  dependen de ellas. Los cambios son **aditivos**: rutas nuevas (`/embeddings/compare`, `/search`, `/api/v1/config/models`,
  `/v1/retrieval/*`, `/v1/estimate/*`), nunca cambios de forma de las existentes. `POST /search` (Sesión 8) se conserva
  sin cambios; `POST /embeddings/ingest` solo gana el campo opcional `chunk_type`.
- **`EstimationResult`** (`domain/schemas/`): el orden de campos importa para la salida estructurada y sus
  validadores disparan el re-prompt.
- **Errores saneados**: ninguna respuesta incluye trazas, claves ni URLs internas; el detalle va al log.
- **SDK asíncronos**: ninguna llamada bloqueante en el event loop.
- **Pruebas sin claves reales**: fakes, `fakeredis`, mocks.

## 8. Huecos reservados

- `generation/rag/store/` y `generation/rag/retriever.py`: persisten y buscan con índice HNSW halfvec; la Sesión 9
  añade filtros por metadatos (JSONB) y umbral de distancia. Pendiente (Sesión 10): búsqueda híbrida y *reranking*.

### Índice vectorial: regla de alineación expresión/operator class

`chunks.embedding` es `vector(1536)` (full precision); la migración `0003` crea `chunks_embedding_halfvec_idx`, un
HNSW sobre la *expresión* `embedding::halfvec(1536)` con `halfvec_cosine_ops` (≈ 50 % del tamaño del índice `vector`,
que se conserva como `chunks_embedding_idx` solo para comparar). Para que Postgres use el índice, el `ORDER BY` de la
consulta debe repetir **exactamente** esa expresión con el operador `<=>`: `CAST(embedding AS HALFVEC(1536)) <=> :q`.
Si no coincide (otro cast, otro operador, otra dimensión) Postgres cae a *Seq Scan* sin avisar. La expresión vive en un
único sitio (`halfvec_embedding()` en `foundation/persistence/models.py`, con `EMBEDDING_DIMENSIONS`) y la usa
`generation/rag/store/documents.py::search_statement`; `tests/test_vector_store.py` comprueba con `EXPLAIN` que el plan
usa el índice. La búsqueda fija `hnsw.ef_search` (`HNSW_EF_SEARCH`) con `SET LOCAL` en su transacción. La búsqueda
filtrada de la Sesión 9 (`generation/rag/retriever.py::filtered_search_statement`) reutiliza la misma expresión y
añade los filtros en el `WHERE` de la misma consulta; `tests/test_rag_retrieval_store.py` lo comprueba con `EXPLAIN`.

## Apéndice: mapa de migración (ruta antigua → nueva)

| Antes | Ahora |
|---|---|
| `app/services/llm_wrapper.py`, `llm_service.py`, `structured.py`, `embeddings.py` | `app/foundation/llm/{wrapper,service,structured,embeddings}.py` |
| `app/services/cache.py` | `app/foundation/llm/cache.py` (almacén) + `app/generation/cag/exact.py` |
| `app/services/semantic_cache.py` | `app/generation/cag/semantic.py` |
| `app/services/guardrails.py` | `app/foundation/guardrails/input.py` |
| `app/services/attachments.py` | `app/foundation/attachments/extractor.py` |
| `app/services/{pipeline,session_estimation,acb,audience,history,evaluation,validation}.py` | `app/domain/` |
| `app/services/{boss,critic}.py` | `app/generation/agentic/` |
| `app/services/{sessions,anchors,compression,summarizer,context}.py` | `app/generation/conversation/` |
| `app/schemas/*` | `app/domain/schemas/*` |
| `app/prompts/*`, `app/context/examples.py` | `app/foundation/prompts/*` |
| `app/persistence/*` | `app/foundation/persistence/*` |
| `app/routers/*` | `app/api/*` |
| `app/embedding_pipeline/{schemas,chunker,embedder,router}.py` | `app/generation/rag/{schemas,chunking/structural,embedding/embedder}.py`, `app/api/embeddings.py` |
