# Arquitectura de estimator-web-go

El servicio web es el espejo del otro lado del cable de la API de IA (`../estimador-cag/ARCHITECTURE.md`). Donde la API
se organiza por capas y por arquitecturas de IA que componen (CAG, RAG, agentes, conversación), el servicio web se
organiza por **los mismos contextos**, con una capa que es *lo único que habla HTTP con la API*. Es la misma estructura
que tenía el cliente Rails, expresada con paquetes de Go.

## Mapa

```
estimador-cag (Python)                  estimator-web-go (Go)
───────────────────────────             ──────────────────────────────────────────────
foundation/ (llm, guardrails…)    ←→    internal/estimatorai/   cliente base, errores tipados, clientes por contexto, corpus
domain/schemas                    ←→    internal/rag · internal/ai   contratos que reflejan los schemas
generation/rag                    ←→    internal/rag/           Chunking Lab (+ historial en PostgreSQL)
foundation/llm/runtime_config     ←→    internal/ai/            Ajustes (modelos en runtime)
domain/ (estimar, sesiones)       ←→    internal/estimation/    formulario de estimación
api/ (routers finos)              ←→    internal/web/           transporte: rutas, handlers, plantillas
```

```
estimator-web-go/
├── cmd/server/            composición: config, pool PostgreSQL, servidor, apagado ordenado, subcomando `healthcheck`
└── internal/
    ├── config/            variables de entorno → Config (mismos nombres y defectos que Rails)
    ├── jsondoc/           documentos JSON dinámicos tolerantes (números con su texto original, semántica de Ruby)
    ├── estimatorai/       CAPA HTTP — única puerta a la API de IA
    │   ├── errors.go          taxonomía: ConnectionFailed ⊃ RequestTimeout, NotFound ⊃ SessionExpired, …
    │   ├── base.go            conexión, mapeo respuesta → error tipado, mensajes en español saneados
    │   ├── clients.go         EstimationsClient · SessionsClient · EmbeddingsClient · ConfigClient
    │   └── corpus.go          corpus de presupuestos embebido (data/*.json)
    ├── rag/               CONTEXTO RAG: catálogo de 8 estrategias, contratos, Comparison, PgStore
    ├── ai/                CONTEXTO configuración: ModelConfig, Catalog (7 knobs)
    ├── estimation/        formulario de estimación: validación, `.txt`, adjuntos
    ├── session/           cookie firmada (HMAC), flash, CSRF, compactado de metadatos
    ├── web/               TRANSPORTE: router, handlers, render, formato, plantillas y páginas de error embebidas
    └── archtest/          prueba de las reglas de dependencias
```

## Las 4 reglas

1. **Solo `estimatorai` habla HTTP con la API.** Ningún handler, plantilla ni paquete de contexto abre conexiones hacia
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
4. **Los handlers solo hacen de transporte.** Validan parámetros, llaman al cliente, traducen los errores tipados a avisos
   con un estado HTTP adecuado y persisten el payload. La lógica de negocio vive en los paquetes de contexto.

## Mapeo de errores en los handlers

| Error tipado | Estado | Dónde |
|---|---|---|
| `InvalidRequest` (400/413/415/422) | 422 | Lab, Ajustes, formulario |
| `GuardrailViolation` (400 de guardrails) | 422 con el mensaje de la API | formulario |
| `NotFound` (404) | 404 | detalle de la estimación |
| `SessionExpired` | nueva conversación y aviso (200) | formulario |
| `ServiceUnavailable` (503) | 503 con el detalle (p. ej. la clave ausente) | Lab, Ajustes |
| `ConnectionFailed` | 503 (Lab, Ajustes) / 502 (resultado) / 422 con aviso (formulario) | todos |
| `RequestTimeout` | 504 (Lab) / 502 (resultado) | Lab / resto |
| `ServerError`, `InvalidResponse` y cualquier otro | 502 (Lab, Ajustes, resultado) / 422 con aviso (formulario) | todos |

## Decisiones

- **Biblioteca estándar**: `net/http` (rutas con método y comodín de Go 1.22+) y `html/template`. Sin framework web: ~14
  rutas, sin middleware complejo. La única dependencia externa es `pgx/v5` (PostgreSQL).
- **SQL directo sobre `pgx`**: una tabla, dos consultas. Sin ORM.
- **Sesión propia**: cookie con JSON firmado (HMAC-SHA256) con `session_id`, metadatos compactados (nombre 80, 10
  tecnologías de 40, alcance 300 caracteres), *flash* y token CSRF. `POST/PATCH/PUT/DELETE` exigen el token (campo
  `authenticity_token` o cabecera `X-CSRF-Token`); si falta o no coincide, 422.
- **HTML idéntico**: las vistas ERB se portaron una a una (mismos ids, clases, textos, CSS y scripts inline). Los helpers
  de Rails (`number_with_precision`, `truncate`, …) se reimplementaron con las mismas salidas.
- **Flujos síncronos a propósito**: el Lab ejecuta por defecto solo estrategias gratuitas; las de pago son opt-in, se
  avisan en el formulario y tienen su propio tiempo de espera (`ESTIMATOR_COMPARE_TIMEOUT`).
- **Degradación**: sin base de datos el Lab calcula y muestra el resultado con un aviso; con la API caída la barra
  omite el indicador del modelo y cachea el fallo 15 s.

## ¿Dónde va mi código nuevo?

| Si añades… | Va en… |
|---|---|
| Un endpoint nuevo del servicio de IA | método en el cliente de su contexto (o un cliente nuevo si el contexto es nuevo), en `estimatorai` |
| Un error HTTP nuevo | `Kind` en `errors.go` + mapeo en `errorFor`/`detailErrorFor` (`base.go`) |
| Un campo nuevo en un schema de la API | campo en el contrato del contexto (`rag`, `ai`) y su lectura en `…FromDoc` |
| Una pantalla de un contexto | handler en `web`, plantilla en `web/templates/` registrada en `pageFiles`, enlace en el layout |
| Un dato persistido | tabla/consulta en el paquete del contexto, con el payload completo en JSONB |
| Una estrategia de chunking nueva | entrada en `rag.Catalog` (mismo nombre y orden que el servicio) |
| Un knob de modelo nuevo | entrada en `ai.Entries` (mismo nombre que `MODEL_KNOBS` del servicio) |

## Pruebas

`go test` + `httptest`: la API de IA es un servidor simulado por prueba (`harness_test.go`); nunca se llama a la real y
todo acceso no simulado falla la prueba. Las de persistencia usan PostgreSQL real (`web-db` efímero,
`TEST_DATABASE_URL`) y se ejecutan con `-p 1` porque comparten la base. `web-lint` = `gofmt -l` + `go vet`.
El layout se renderiza siempre sin el servicio levantado (hay pruebas que lo hacen caer para comprobar la degradación).
