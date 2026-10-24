# Arquitectura de estimator-web

El cliente Rails es el espejo del otro lado del cable del servicio (`../estimador-cag/ARCHITECTURE.md`). Donde el
servicio se organiza por capas y por arquitecturas de IA que componen (CAG, RAG, agentes, conversación), el cliente se
organiza por **los mismos contextos**, con una capa que es *lo único que habla HTTP con el servicio*.

## Mapa

```
estimador-cag (Python)                  estimator-web (Rails)
───────────────────────────             ──────────────────────────────────────────────
foundation/ (llm, guardrails…)    ←→    app/services/estimator_ai/    clientes HTTP, errores tipados, corpus
domain/schemas                    ←→    app/models/<contexto>/        contratos (POROs) que reflejan los schemas
generation/rag                    ←→    rag/                          Chunking Lab
foundation/llm/runtime_config     ←→    ai/                           Ajustes (modelos en runtime)
domain/ (estimar, sesiones)       ←→    estimations (formulario, historial y conversación)
api/ (routers finos)              ←→    controllers + views           transporte
```

```
app/
├── services/estimator_ai/        # CAPA HTTP — única puerta al servicio
│   ├── base_client.rb            #   Faraday, mapeo respuesta → error tipado, mensajes en español
│   ├── error.rb … session_expired.rb   # taxonomía: un archivo por error (Zeitwerk)
│   ├── estimations_client.rb     #   POST /api/v1/estimate · historial · vista previa del prompt
│   ├── sessions_client.rb        #   /api/v1/sessions y estimaciones dentro de la conversación
│   ├── embeddings_client.rb      #   POST /embeddings/compare (Chunking Lab)
│   ├── config_client.rb          #   GET/PUT /api/v1/config/models (Ajustes)
│   └── budget_corpus.rb          #   corpus estático que envía el Lab (lib/estimator_ai/data/)
│
├── models/
│   ├── estimation_form.rb        # formulario de estimación (validación local, antes de llamar a la API)
│   ├── application_record.rb
│   ├── rag/                      # CONTEXTO RAG
│   │   ├── strategy              #   catálogo de las 8 estrategias (espejo de ALL_STRATEGIES)
│   │   ├── comparison_response · stats · token_distribution · query_result · top_chunk   # contratos
│   │   └── chunking_comparison   #   ActiveRecord: historial persistido (tabla chunking_comparisons)
│   └── ai/                       # CONTEXTO configuración del servicio
│       ├── model_config          #   un knob: effective / default / overridden
│       └── catalog               #   snapshot completo de GET /config/models
│
├── controllers/
│   ├── home_controller           # panel de inicio (una tarjeta por contexto)
│   ├── estimations_controller · conversations_controller
│   ├── ai_settings_controller    # Ajustes
│   └── rag/chunking_comparisons_controller
└── helpers/  navigation_helper (sección activa) · ai_settings_helper (indicador del modelo primario)
```

## Las 4 reglas

1. **Solo `services/estimator_ai/` habla HTTP.** Ningún controller, helper ni modelo usa Faraday. Los clientes heredan de
   `BaseClient` (conexión, mapeo de estados a errores, mensajes saneados). La taxonomía de errores es única
   (`EstimatorAi::Error` y sus hijos: `ConnectionFailed`, `RequestTimeout`, `InvalidRequest`, `GuardrailViolation`,
   `NotFound`, `SessionExpired`, `ServiceUnavailable`, `ServerError`, `InvalidResponse`) y todos los mensajes son para el
   usuario: nunca un cuerpo crudo, una traza ni la URL interna.
2. **Los contratos reflejan los schemas Pydantic.** `Rag::Stats`, `Rag::TopChunk`, `Ai::ModelConfig`… son el espejo de
   `ChunkingStats`, `TopChunk` y de la instantánea de configuración. Si el contrato cambia en Python, cambia aquí y
   solo aquí. Los atributos desconocidos que añada una versión nueva del servicio se ignoran. Los registros
   ActiveRecord guardan el payload completo como JSONB y lo tipan al leerlo (`to_response`).
3. **Los contextos no se importan entre sí.** `rag/`, `ai/` y la estimación comparten la capa HTTP y nada más. Excepción
   deliberada: la barra de navegación consulta `Ai` (modelo primario) a través de un helper tolerante a fallos.
4. **Los controllers solo hacen de transporte.** Validan parámetros, llaman al cliente, traducen los errores tipados a
   avisos con un estado HTTP adecuado y persisten el payload. La lógica de negocio vive en el servicio.

## Mapeo de errores en los controllers

| Error tipado | Estado | Dónde |
|---|---|---|
| `InvalidRequest` (400/413/415/422) | 422 | Lab, Ajustes, formulario |
| `GuardrailViolation` (400 de guardrails) | 422 con el mensaje de la API | formulario |
| `NotFound` (404) | 404 | historial, detalle |
| `SessionExpired` | nueva conversación y aviso | formulario |
| `ServiceUnavailable` (503) | 503 con el detalle (p. ej. la clave ausente) | Lab, Ajustes |
| `ConnectionFailed` | 503 (Lab, Ajustes) / 502 (estimaciones) | todos |
| `RequestTimeout` | 504 (Lab) / 502 | Lab / resto |
| `ServerError`, `InvalidResponse` y cualquier otro `EstimatorAi::Error` | 502 | todos |

## Frontera con el servicio IA

- El cliente **nunca** habla con OpenAI ni Anthropic: solo con `ESTIMATOR_API_URL`.
- Tiempo de espera global de 300 s (`ESTIMATOR_READ_TIMEOUT`). La comparación del Lab usa 600 s
  (`ESTIMATOR_COMPARE_TIMEOUT`) **solo en su llamada**, pasando `read_timeout` al crear el cliente. El indicador del modelo
  primario usa 2 s (`ESTIMATOR_BADGE_TIMEOUT`) y cachea el resultado (también el fallo) 15 s.
- Flujos síncronos a propósito (sin infraestructura de trabajos): el Lab ejecuta por defecto solo estrategias gratuitas
  (segundos); las de pago son opt-in, se avisan en el formulario y se guardan para no volver a pagarlas.

## Persistencia

El cliente ya no es del todo sin estado: PostgreSQL (`estimator-web-db` en Compose, `DATABASE_URL`) guarda solo
`chunking_comparisons`. Se eligió PostgreSQL y no SQLite porque es el mismo motor del resto del stack, soporta JSONB y no se
pierde al reconstruir el contenedor (volumen propio). Si la base de datos falla, el Lab muestra igualmente el resultado
recién calculado con un aviso en lugar de perder una ejecución de pago, y el resto de pantallas siguen funcionando.

## ¿Dónde va mi código nuevo?

| Si añades… | Va en… |
|---|---|
| Un endpoint nuevo del servicio | método en el cliente de su contexto (o un cliente nuevo si el contexto es nuevo) |
| Un error HTTP nuevo | subclase de `EstimatorAi::Error` en su archivo + mapeo en `BaseClient#error_for` |
| Un campo nuevo en un schema de la API | atributo en el PORO del contexto (`app/models/<contexto>/`) |
| Una pantalla de un contexto | controller + vistas bajo el espacio de nombres del contexto; enlace en `NavigationHelper` |
| Un dato persistido | modelo ActiveRecord en el contexto, con el payload completo en JSONB |
| Una estrategia de chunking nueva | entrada en `Rag::Strategy::CATALOG` (mismo nombre y orden que el servicio) |
| Un knob de modelo nuevo | entrada en `Ai::ModelConfig::CATALOG` (mismo nombre que `MODEL_KNOBS` del servicio) |

## Pruebas

Minitest + WebMock: nunca llaman a la API real; todo acceso de red no simulado falla. Se ejecutan en Docker con una base
de datos efímera (`docker compose -f docker-compose.verify.yml run --rm web-test`) y el lint con RuboCop omakase
(`run --rm web-lint`). `test_helper` simula siempre `GET /config/models` para que cualquier página (la barra incluida)
se pueda renderizar sin el servicio levantado; hay pruebas que lo hacen fallar para comprobar que la barra se degrada.

## Lo que sigue sin migrar

`EstimationForm` (validación local del formulario) y la sesión de conversación (`ConversationSession`) siguen como
estaban; solo cambiaron sus llamadas, que ahora usan los clientes por contexto. El monolito `EstimatorApi` se eliminó.
