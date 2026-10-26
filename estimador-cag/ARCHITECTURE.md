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
  la comparación de estrategias de chunking; la persistencia y la recuperación llegan en la Sesión 8.
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
│   ├── schemas/    #   contratos Pydantic que consumen los clientes (Rails, React, Streamlit)
│   ├── pipeline.py #   conductor de /estimate: guardrails → cag → prompt → llm → validación → cag
│   ├── session_estimation.py · acb.py   # conductores conversacional y Actor–Crítico–Boss
│   └── validation.py · audience.py · history.py · evaluation.py   # reglas de negocio y servicios de dominio
├── generation/     # las arquitecturas que componen
│   ├── cag/        #   exact.py (resultados validados) + semantic.py (redisvl)
│   ├── rag/        #   chunking/ · embedding/ · analysis/ · schemas.py · store/ (S8) · retriever.py (S8)
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

## 6. ¿Dónde va mi código nuevo?

| Si añades… | Va en… |
|---|---|
| Backend LLM, plantilla de prompt, guardrail, adjunto, persistencia | `foundation/` |
| Modelo seleccionable en runtime (knob nuevo) | `foundation/llm/runtime_config.py` (`MODEL_KNOBS`) y su ruta en `api/config.py` |
| Estrategia de chunking, embeddings, comparación | `generation/rag/` |
| Vector store o retriever (Sesión 8) | `generation/rag/store/` y `generation/rag/retriever.py` |
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
  `/api/v1/prompts/*`, `/api/v1/ingestion/*`, `/embeddings/ingest`. Los clientes Rails, React y Streamlit
  dependen de ellas. Los cambios son **aditivos**: rutas nuevas (`/embeddings/compare`, `/api/v1/config/models`),
  nunca cambios de forma de las existentes.
- **`EstimationResult`** (`domain/schemas/`): el orden de campos importa para la salida estructurada y sus
  validadores disparan el re-prompt.
- **Errores saneados**: ninguna respuesta incluye trazas, claves ni URLs internas; el detalle va al log.
- **SDK asíncronos**: ninguna llamada bloqueante en el event loop.
- **Pruebas sin claves reales**: fakes, `fakeredis`, mocks.

## 8. Huecos reservados (Sesión 8)

- `generation/rag/store/`: persistencia pgvector con índice HNSW.
- `generation/rag/retriever.py`: recuperación semántica con filtrado por metadatos.

Ambos son placeholders documentados; cuando RAG entre en la petición, el paso se añade al conductor.

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
