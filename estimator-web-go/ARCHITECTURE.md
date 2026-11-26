# Arquitectura de estimator-web-go

El servicio web es el espejo del otro lado del cable de la API de IA (`../estimador-cag/ARCHITECTURE.md`). Donde la API
se organiza por capas y por arquitecturas de IA que componen (CAG, RAG, agentes, conversación), el servicio web se
organiza por **los mismos contextos**, con una capa que es *lo único que habla HTTP con la API*. Es la misma estructura
que tenía el cliente Rails, expresada con paquetes de Go. Desde las tareas 10.1 y 10.2 del cambio
`homelab-route-clients-through-go` el servicio no renderiza HTML: es el backend REST y SSE que consume React.

## Mapa

```
estimador-cag (Python)                  estimator-web-go (Go)
───────────────────────────             ──────────────────────────────────────────────
foundation/ (llm, guardrails…)    ←→    internal/estimatorai/   cliente base, errores tipados, clientes por contexto, corpus
domain/schemas                    ←→    internal/rag · internal/ai   contratos que reflejan los schemas
generation/rag                    ←→    internal/rag/           Chunking Lab (+ historial en PostgreSQL)
foundation/llm/runtime_config     ←→    internal/ai/            Ajustes (modelos en runtime)
domain/ (estimar, sesiones)       ←→    internal/estimation/    reglas de la solicitud de estimación (sin consumidor HTTP directo)
api/ (routers finos)              ←→    internal/web/           transporte: API REST/SSE, autorización, origen, `/up`
```

```
estimator-web-go/
├── cmd/server/            composición: config, pool PostgreSQL, servidor, apagado ordenado, subcomando `healthcheck`
└── internal/
    ├── config/            variables de entorno → Config (nombres y defectos conservados)
    ├── jsondoc/           documentos JSON dinámicos tolerantes (números con su texto original, semántica de Ruby)
    ├── estimatorai/       CAPA HTTP — única puerta a la API de IA
    │   ├── errors.go          taxonomía: ConnectionFailed ⊃ RequestTimeout, NotFound ⊃ SessionExpired, …
    │   ├── base.go            conexión, mapeo respuesta → error tipado, mensajes en español saneados
    │   ├── clients.go         EstimationsClient · SessionsClient · EmbeddingsClient · ConfigClient
    │   └── corpus.go          corpus de presupuestos embebido (data/*.json)
    ├── rag/               CONTEXTO RAG: catálogo de 8 estrategias, contratos, Comparison, PgStore
    ├── ai/                CONTEXTO configuración: ModelConfig, Catalog (7 knobs)
    ├── estimation/        reglas de la solicitud de estimación: validación, `.txt`, adjuntos (se conservan; hoy solo las ejercitan sus pruebas)
    ├── web/               TRANSPORTE: `/up`, API REST y SSE (`api*.go`), autorización administrativa, origen, historial del Lab
    └── archtest/          prueba de las reglas de dependencias
```

## Las 4 reglas

1. **Solo `estimatorai` habla HTTP con la API.** Ningún handler ni paquete de contexto abre conexiones hacia
   ella (`archtest` lo comprueba: prohíbe `http.NewRequest`, `http.Get`, `http.Client`… fuera de `estimatorai`). Los
   clientes comparten el cliente base (conexión, mapeo de estados a errores, mensajes). La taxonomía de errores es única
   (`*estimatorai.Error` con `Kind`) y todos los mensajes son para el usuario: nunca un cuerpo crudo, una traza ni la URL
   interna.
2. **Los contratos reflejan los schemas Pydantic.** `rag.Stats`, `rag.TopChunk`, `ai.ModelConfig`… son el espejo de
   `ChunkingStats`, `TopChunk` y de la instantánea de configuración. Si el contrato cambia en Python, cambia aquí y solo
   aquí. Los atributos desconocidos que añada una versión nueva del servicio se ignoran. Los registros del historial
   guardan el payload completo como JSONB y lo tipan al leerlo (`Comparison.Response()`).
3. **Los contextos no se importan entre sí.** `rag`, `ai` y `estimation` comparten, como mucho, `jsondoc`; el único que
   los junta es `web`. Cada paquete solo puede importar lo que su capa permite (tabla `allowed` en `archtest`).
4. **Los handlers solo hacen de transporte.** Validan parámetros, llaman al cliente, traducen los errores tipados a respuestas
   JSON con un estado HTTP adecuado y persisten el payload. La lógica de negocio vive en los paquetes de contexto.

## Mapeo de errores en los handlers

Las respuestas de error de la API son JSON saneado (`{"detail": …}`; `{"reason","message"}` para guardrails).

| Error tipado | Estado | Dónde |
|---|---|---|
| `InvalidRequest` (400/413/415/422) | el del upstream (400 con `reason` si es guardrail) | todas |
| `NotFound` (404) | 404 | sesión caducada, detalle de estimación o comparación |
| `ServiceUnavailable` (503) | 503 con el detalle (p. ej. la clave ausente) | Lab, Ajustes |
| `ConnectionFailed` | 503 | todas |
| `RequestTimeout` | 504 | todas |
| `ServerError`, `InvalidResponse` y cualquier otro | 502 con mensaje genérico | todas |
| Acceso administrativo no concedido | 403 antes de leer, cachear, llamar a IA o tocar el repositorio | Ajustes, Lab |
| Origen no permitido en una mutación | 403 antes de enrutar | todas |

## Decisiones

- **Biblioteca estándar**: `net/http` (rutas con método y comodín de Go 1.22+). Sin framework web ni `html/template`.
  La única dependencia externa es `pgx/v5` (PostgreSQL).
- **SQL directo sobre `pgx`**: una tabla, dos consultas. Sin ORM.
- **Sin estado de navegador**: no hay cookie, sesión ni CSRF de formulario. La conversación la identifica el UUID de la
  sesión de la API, que conserva React. La cookie legada `_estimator_web_session` solo se expira. Las mutaciones se
  protegen con la validación de origen (`ESTIMATOR_PUBLIC_ORIGIN`) y las operaciones administrativas con la decisión
  de autorización, denegada por defecto.
- **Cadena de transporte**: `logging` → `recoverer` → `expireLegacyCookie` → enrutador (`/up` y API). `logging` registra
  método, patrón de ruta (nunca la ruta resuelta ni la consulta, para no filtrar IDs de sesión), estado y duración.
  `recoverer` devuelve un 500 JSON saneado, o corta la conexión si la respuesta ya empezó (SSE). Los wrappers exponen
  `Unwrap` para que `http.ResponseController` alcance `FlushError`, `Flush` y los plazos de lectura y escritura.
- **Flujos síncronos a propósito**: el Lab ejecuta por defecto solo estrategias gratuitas; las de pago son opt-in, se
  avisan en el formulario y tienen su propio tiempo de espera (`ESTIMATOR_COMPARE_TIMEOUT`).
- **Degradación**: sin base de datos el Lab calcula y devuelve el resultado con un aviso; con la API caída el indicador
  del primario responde `{"model":null}` y cachea el fallo 15 s.

## ¿Dónde va mi código nuevo?

| Si añades… | Va en… |
|---|---|
| Un endpoint nuevo del servicio de IA | método en el cliente de su contexto (o un cliente nuevo si el contexto es nuevo), en `estimatorai` |
| Un error HTTP nuevo | `Kind` en `errors.go` + mapeo en `errorFor`/`detailErrorFor` (`base.go`) |
| Un campo nuevo en un schema de la API | campo en el contrato del contexto (`rag`, `ai`) y su lectura en `…FromDoc` |
| Un endpoint REST de un contexto | handler `api*.go` en `web`, registro en `apiHandler`, contrato alineado con los schemas de Python; la pantalla va en React |
| Un dato persistido | tabla/consulta en el paquete del contexto, con el payload completo en JSONB |
| Una estrategia de chunking nueva | entrada en `rag.Catalog` (mismo nombre y orden que el servicio) |
| Un knob de modelo nuevo | entrada en `ai.Entries` (mismo nombre que `MODEL_KNOBS` del servicio) |

## Pruebas

`go test` + `httptest`: la API de IA es un servidor simulado por prueba (`harness_test.go`) y las rutas se ejercitan por REST; nunca se llama a la real y
todo acceso no simulado falla la prueba. Las de persistencia usan PostgreSQL real (`web-db` efímero,
`TEST_DATABASE_URL`) y se ejecutan con `-p 1` porque comparten la base. `web-lint` = `gofmt -l` + `go vet`.
Las pruebas de la frontera (`security_test.go`) comprueban la retirada del HTML, la sonda, la cookie legada, la recuperación,
el registro saneado y la propagación de `FlushError`, `Unwrap` y plazos. La correspondencia con las pruebas HTML retiradas
está en `EVIDENCIA-RETIRADA-HTML.md`.
