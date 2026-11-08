# Arquitectura de estimator-web-go

El backend de negocio (capa 2) es el espejo, del otro lado del cable, de la API de IA (`../estimador-cag/ARCHITECTURE.md`,
capa 3). Donde la API se organiza por capas y por arquitecturas de IA que componen (CAG, RAG, agentes, conversación), el
backend se organiza por **los mismos contextos**, con una capa que es *lo único que habla HTTP con la API de IA*. Hacia
arriba expone un API JSON a los frontends (capa 1: React y Streamlit), que no conocen el servicio de IA.

## Mapa

```
estimador-cag (Python)                  estimator-web-go (Go)
───────────────────────────             ──────────────────────────────────────────────
foundation/ (llm, guardrails…)    ←→    internal/estimatorai/   cliente base, errores tipados, clientes por contexto, corpus
domain/schemas                    ←→    internal/rag · internal/ai   contratos que reflejan los schemas
generation/rag                    ←→    internal/rag/           Chunking Lab (+ historial en PostgreSQL)
foundation/llm/runtime_config     ←→    internal/ai/            Ajustes (modelos en runtime)
domain/ (estimar, sesiones)       ←→    internal/estimation/    validación de la estimación
api/ (routers finos)              ←→    internal/httpapi/       transporte: rutas JSON `/api/...`, errores `{"detail"}`
```

```
estimator-web-go/
├── cmd/server/            composición: config, pool PostgreSQL, servidor, apagado ordenado, subcomando `healthcheck`
└── internal/
    ├── config/            variables de entorno → Config
    ├── jsondoc/           documentos JSON dinámicos tolerantes (números con su texto original)
    ├── estimatorai/       CAPA HTTP — única puerta a la API de IA
    │   ├── errors.go          taxonomía: ConnectionFailed ⊃ RequestTimeout, NotFound ⊃ SessionExpired, …
    │   ├── base.go            conexión, mapeo respuesta → error tipado, mensajes en español saneados
    │   ├── clients.go         EstimationsClient · SessionsClient · EmbeddingsClient · ConfigClient
    │   └── corpus.go          corpus de presupuestos embebido (data/*.json)
    ├── rag/               CONTEXTO RAG: catálogo de 8 estrategias, Comparison, PgStore, coste de ingesta
    ├── ai/                CONTEXTO configuración: ModelConfig, Catalog (7 knobs)
    ├── estimation/        validación de la estimación: descripción, `.txt`, adjuntos
    ├── httpapi/           TRANSPORTE: router, handlers y errores JSON (sin HTML, cookies ni CSRF)
    └── archtest/          prueba de las reglas de dependencias
```

## Las 4 reglas

1. **Solo `estimatorai` habla HTTP con la API de IA.** Ningún handler ni paquete de contexto abre conexiones hacia
   ella (`archtest` lo comprueba: prohíbe `http.NewRequest`, `http.Get`, `http.Client`… fuera de `estimatorai`). Los
   clientes comparten el cliente base (conexión, mapeo de estados a errores, mensajes). La taxonomía de errores es única
   (`*estimatorai.Error` con `Kind`) y todos los mensajes son para el usuario: nunca un cuerpo crudo, una traza ni la URL
   interna. Y recíprocamente: **este backend es el único cliente de la API de IA**; React y Streamlit solo lo llaman a
   él.
2. **Los contratos reflejan los schemas Pydantic.** `ai.ModelConfig` es el espejo de la instantánea de configuración y
   `rag` lee de la comparación solo el coste de ingesta (`ChunkingStats`); el resto del payload se guarda y se reexpone
   tal cual, y lo tipan los clientes. Si el contrato cambia en Python, cambia aquí y solo aquí. Los atributos
   desconocidos que añada una versión nueva del servicio se ignoran. Los registros del historial guardan el payload
   completo como JSONB.
3. **Los contextos no se importan entre sí.** `rag`, `ai` y `estimation` comparten, como mucho, `jsondoc`; el único que
   los junta es `httpapi`. Cada paquete solo puede importar lo que su capa permite (tabla `allowed` en `archtest`).
4. **Los handlers solo hacen de transporte.** Validan parámetros, llaman al cliente, traducen los errores tipados a
   `{"detail": ...}` con un estado HTTP adecuado y persisten el payload. La lógica de negocio vive en los paquetes de
   contexto.

## Mapeo de errores en los handlers

Todos los handlers responden `{"detail": "<mensaje saneado>"}` con el estado de esta tabla (`statusFor` y
`writeLabError`/`settingsUpdate` para los matices del Lab y de Ajustes):

| Error tipado | Estado | Dónde |
|---|---|---|
| `InvalidRequest` (400/413/415/422) y `GuardrailViolation` | 422 | estimación, Lab, Ajustes |
| `NotFound` (404) y `SessionExpired` | 404 | detalle de la estimación, estimación de una conversación caducada |
| `ServiceUnavailable` (503) | 503 con el detalle (p. ej. la clave ausente) | todos |
| `ConnectionFailed` | 503 | todos |
| `RequestTimeout` | 504 | todos (el Lab sugiere menos estrategias) |
| `ServerError`, `InvalidResponse` y cualquier otro | 502 | todos |

## Decisiones

- **Biblioteca estándar**: `net/http` (rutas con método y comodín de Go 1.22+). Sin framework web: ~13 rutas, sin
  middleware complejo. La única dependencia externa es `pgx/v5` (PostgreSQL).
- **SQL directo sobre `pgx`**: una tabla, dos consultas. Sin ORM.
- **Sin estado de navegador**: no hay cookie, flash ni CSRF. Un API JSON consumido por una SPA del mismo origen (nginx) y
  por Streamlit (servidor a servidor) no usa cookies, así que no hay CSRF que proteger. El cliente conserva el
  `conversation_id` (el `session_id` de la API de IA); los `project_metadata` vuelven completos en cada respuesta.
- **Prefijo `/api/` sin `/v1`**: `/api/v1/...` es el espacio de rutas del servicio de IA; los clientes no deben poder
  confundir ambos contratos. Los cuerpos de estimación reutilizan la forma JSON de la API de IA (el backend la
  encapsula, no la rediseña).
- **Validación también aquí**: `internal/estimation` es la fuente de verdad de las reglas de entrada (descripción,
  `.txt`, adjuntos); los clientes validan además para dar respuesta inmediata.
- **Flujos síncronos a propósito**: el Lab ejecuta por defecto solo estrategias gratuitas; las de pago son opt-in, se
  avisan en el formulario del cliente y tienen su propio tiempo de espera (`ESTIMATOR_COMPARE_TIMEOUT`).
- **Degradación**: sin base de datos el Lab calcula y devuelve el resultado con `saved:false` y un aviso; con la API caída
  `GET /api/primary-model` devuelve el modelo vacío y cachea el fallo 15 s.

## ¿Dónde va mi código nuevo?

| Si añades… | Va en… |
|---|---|
| Un endpoint nuevo del servicio de IA | método en el cliente de su contexto (o un cliente nuevo si el contexto es nuevo), en `estimatorai` |
| Un error HTTP nuevo | `Kind` en `errors.go` + mapeo en `errorFor`/`detailErrorFor` (`base.go`) y en `statusFor` (`httpapi`) |
| Un campo nuevo en un schema de la API | campo en el contrato del contexto (`ai`) y su lectura en `…FromDoc`; los payloads que solo se reexponen no necesitan tipos |
| Un endpoint del backend | handler en `httpapi`, ruta en `Handler()` y prueba en `api_test.go` |
| Un dato persistido | tabla/consulta en el paquete del contexto, con el payload completo en JSONB |
| Una estrategia de chunking nueva | entrada en `rag.Catalog` (mismo nombre y orden que el servicio) |
| Un knob de modelo nuevo | entrada en `ai.Entries` (mismo nombre que `MODEL_KNOBS` del servicio) |

## Pruebas

`go test` + `httptest`: la API de IA es un servidor simulado por prueba (`httpapi/harness_test.go`); nunca se llama a la
real y todo acceso no simulado falla la prueba. Las de persistencia usan PostgreSQL real (`web-db` efímero,
`TEST_DATABASE_URL`) y se ejecutan con `-p 1` porque comparten la base. `web-lint` = `gofmt -l` + `go vet`.
