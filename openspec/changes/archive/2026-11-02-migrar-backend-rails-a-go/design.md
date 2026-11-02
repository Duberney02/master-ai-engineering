# Design

## Context

### Arquitectura actual (observada)

```
Navegador ──HTTP/HTML──▶ estimator-web (Rails 8.1, :3000) ──HTTP/JSON──▶ estimador-cag (FastAPI, :8000) ──▶ Redis · PostgreSQL · LLMs
                              │
                              └──▶ estimator-web-db (PostgreSQL 17): solo `chunking_comparisons`

Navegador ──▶ estimator-web-react (nginx, :3001) ──/api/ proxy──▶ estimador-cag      (no pasa por Rails)
Navegador ──▶ estimador-cag-chat  (Streamlit, :8501) ──HTTP──▶ estimador-cag          (no pasa por Rails)
```

`estimator-web` **no es una API JSON**: es una aplicación Rails con renderizado en servidor (7 vistas ERB + parciales,
~1 800 líneas en total) que actúa de BFF/cliente de la API de IA. Responsabilidades observadas:

| Área | Rails | Comportamiento |
|---|---|---|
| Estimaciones | `EstimationsController`, `EstimationForm` | formulario (validación local, `.txt`, adjuntos), envío multipart a `/api/v1/sessions/{id}/estimate`, resultado, historial, barra lateral (prompt + métricas) |
| Conversación | `ConversationSession`, `ConversationsController` | `session_id` y metadatos en la cookie de sesión; «Nueva conversación»; sesión caducada |
| Chunking Lab | `Rag::ChunkingComparisonsController`, `Rag::*` | `POST /embeddings/compare` (600 s), historial en PostgreSQL (JSONB), fallos de BD tolerados |
| Ajustes | `AiSettingsController`, `Ai::*`, `AiSettingsHelper` | `GET/PUT /api/v1/config/models`, indicador del modelo primario cacheado 15 s |
| Transversal | `ApplicationController`, layout | CSRF de Rails, flash, `/up`, CSS/JS inline, páginas de error estáticas |

No hay autenticación ni autorización de usuarios (la aplicación es de uso interno); la única "seguridad" de
aplicación es la cookie firmada y el CSRF de Rails. Los **únicos consumidores** de este servicio son los navegadores;
ningún otro componente del repositorio lo llama (se verificó con `grep` sobre compose, React, Streamlit y la API: las
únicas menciones a Rails son comentarios en Python y la documentación). La base de datos es exclusiva del servicio.

### Arquitectura objetivo

```
Navegador ──HTTP/HTML──▶ estimator-web (Go, :3000) ──HTTP/JSON──▶ estimador-cag (FastAPI) ──▶ …
                              └──▶ estimator-web-db (PostgreSQL 17, misma tabla)
```

El nombre de servicio, el puerto, la ruta `/up` y las variables de entorno no cambian. La API Python no se toca.

### Sobre «migrar los clientes»

El enunciado pide que todos los clientes que consumen Rails pasen a consumir Go. En este repositorio el único cliente de
Rails es el navegador del usuario, que llega por `localhost:3000`. Como el servicio Go conserva nombre de servicio
(`estimator-web`), puerto y rutas, **no hay URLs que reconfigurar**: el cambio de backend es la sustitución del
contenedor tras ese mismo punto de entrada. La SPA React y el chat Streamlit nunca usaron Rails, así que no se modifican
(modificarlos violaría «no tocar componentes ajenos»). La verificación de «ningún cliente depende de Rails» es, por
tanto: (a) no hay servicio, imagen ni referencia de ejecución de Rails en Compose/CI/documentación; (b) el stack arranca
y se recorre sin Rails.

## Goals / Non-Goals

**Goals:**
- Equivalencia observable: mismas rutas, métodos, HTML (ids, textos, clases), estados HTTP, mensajes y reglas.
- Go idiomático con la menor superficie de dependencias; separación transporte / dominio / integraciones / datos.
- Todo el ciclo (compilar, probar, ejecutar) en Docker, con las mismas convenciones del repositorio.

**Non-Goals:**
- Funcionalidad nueva, rediseño visual o cambios de contrato con la API Python.
- Compatibilidad de la cookie de sesión de Rails (cifrada con `SECRET_KEY_BASE` por Rails): no es un contrato público.
- Migrar o reescribir la SPA React, Streamlit o la API.

## Decisions

### D1. Biblioteca estándar (`net/http`, `html/template`) sin framework web
Las rutas son ~14, sin middleware complejo; `net/http` de Go 1.22+ ya soporta métodos y comodines (`GET /estimations/{id}`).
`html/template` escapa por contexto (equivale al auto-escape de ERB). *Alternativas*: Gin/Echo/Chi (añaden una
dependencia y su propio modelo de contexto para ahorrar unas líneas de enrutado); descartadas por «evitar abstracciones
innecesarias».

### D2. PostgreSQL con `pgx/v5` (`pgxpool`), SQL directo, sin ORM
Una sola tabla con dos consultas (`INSERT`, `SELECT`). El ORM no aporta nada. `pgx` es el driver estándar de facto,
con soporte nativo de `jsonb`. *Es la única dependencia externa del módulo.* El esquema no cambia: al arrancar se ejecuta
`CREATE TABLE IF NOT EXISTS chunking_comparisons (...)` idéntico a `db/schema.rb`, de modo que un volumen creado por Rails
se reutiliza tal cual y uno vacío se inicializa. Si no hay `DATABASE_URL` o falla la conexión, el servicio arranca igual
y el Lab degrada (como Rails).

### D3. Sesión y CSRF propios sobre cookie firmada (HMAC-SHA256)
Rails guarda la sesión cifrada en la cookie; aquí se guarda JSON firmado con `SECRET_KEY_BASE` (no necesita
confidencialidad: contiene `session_id` de conversación, metadatos públicos del proyecto y el token CSRF). Mismo tope
de 4 KB mitigado con el mismo compactado de metadatos. El *flash* vive en la misma cookie y se consume en la siguiente
petición. CSRF: token aleatorio por sesión en la cookie, campo oculto `authenticity_token` y `<meta name="csrf-token">`;
comparación en tiempo constante; fallo → 422, como Rails. *Alternativa*: `gorilla/sessions` + `gorilla/csrf`: dos
dependencias para ~120 líneas de lógica auditable.

### D4. Capa HTTP `internal/estimatorai` con `net/http`
Un `BaseClient` (misma lógica de `handle`/`error_for`/`detail_error_for`/`parse` de Rails) y un cliente por contexto.
Errores: un único tipo `*Error{Kind, Message, Status}` con las 9 clases de Rails y la jerarquía (`RequestTimeout` ⊂
`ConnectionFailed`, `SessionExpired` ⊂ `NotFound`) expresada con `errors.As` + `Is(kind)`. Los payloads de estimaciones
(`result`, `phases`, `metrics`) se decodifican como `map[string]any` con `UseNumber` para conservar `70` vs `70.5` tal
como los imprime Rails; los contratos RAG/AI usan structs tipadas (los campos desconocidos se ignoran por defecto en
`encoding/json`). Tiempos: `open` → `net.Dialer.Timeout`; `read` → `ResponseHeaderTimeout` y `http.Client.Timeout`.
Diferencia aceptada: Faraday cuenta el *read timeout* por lectura de socket y Go por petición completa; con los tiempos
usados (300/600 s) y respuestas JSON, es indistinguible.

### D5. Estructura de paquetes espejo de los contextos de Rails
```
estimator-web-go/
├── cmd/server/            composición (config, pool, clientes, router, apagado ordenado, subcomando `healthcheck`)
├── internal/config/       variables de entorno → Config (mismos nombres y defectos que Rails)
├── internal/estimatorai/  CAPA HTTP: base, errores, clientes por contexto, corpus embebido
├── internal/rag/          contexto RAG: catálogo de estrategias, contratos, repositorio PostgreSQL
├── internal/ai/           contexto configuración: ModelConfig, Catalog
├── internal/estimation/   formulario de estimación (validación)
├── internal/session/      cookie firmada, flash, CSRF
└── internal/web/          TRANSPORTE: router, handlers, render, formato, plantillas embebidas
```
Reglas (se mantienen las 4 de `ARCHITECTURE.md` de Rails): solo `estimatorai` habla HTTP con la API; los contratos
reflejan los schemas; `rag` y `ai` no se importan entre sí; los handlers solo hacen transporte. Se verifica con una
prueba de dependencias de paquetes.

### D6. HTML idéntico, plantillas embebidas con `embed`
Se portan las vistas ERB una a una a `html/template` conservando ids, clases, textos, el CSS y los scripts inline. Los
helpers de formato de Rails (`number_with_precision`, `number_with_delimiter`, `truncate`, `format_time`…) se
reimplementan con las mismas salidas (separadores `.`/`,`, redondeo half-up). Las páginas de error (`public/404.html`,
`422.html`, `500.html`) se embeben. El binario es autocontenido (plantillas, corpus JSON y errores).

### D7. Docker
- `Dockerfile` multietapa: `test` (golang con el código montado, para `web-test`/`web-lint`), `build` (binario estático
  `CGO_ENABLED=0`) y `runtime` (`distroless/static:nonroot`, uid 65532, sin shell). El healthcheck usa el propio binario
  (`/estimator-web healthcheck` → `GET /up`), porque la imagen no tiene `curl`/`wget`.
- `docker-compose.yml`: el servicio `estimator-web` se construye desde `estimator-web-go/`; mismo puerto, `depends_on` y
  variables (`ESTIMATOR_API_URL`, `ESTIMATOR_*_TIMEOUT`, `DATABASE_URL`, `SECRET_KEY_BASE`).
- `docker-compose.verify.yml`: `web-db` efímera + `web-test` (`go test ./...`) + `web-lint` (`gofmt -l` y `go vet`),
  conservando los nombres que ya documenta `CLAUDE.md`.

### D8. Estrategia de validación y sustitución
1. Pruebas Go portadas de las 1 961 líneas de Minitest/WebMock (mismos escenarios) con `httptest` como API simulada.
2. Comparación contra Rails en vivo: se levantan ambos contra la misma API Python y la misma BD y se comparan los HTML
   (normalizados) de las pantallas que no requieren LLM; los flujos con LLM se cubren con la API simulada.
3. Solo entonces se conmuta el Compose y, en un commit separado, se retira `estimator-web/` (Rails).

## Risks / Trade-offs

- **Diferencias sutiles de HTML/formato respecto a ERB** (redondeos, escapes, `truncate`) → pruebas de formato con los
  valores de las pruebas Rails y la comparación en vivo de D8.
- **Sesión de Rails no portable** → las conversaciones abiertas se reinician una vez; documentado como cambio operativo.
- **Parseo de formularios con claves estilo Rails** (`models[primary_model]`, `strategies[]`, `estimation_form[...]`) →
  se leen directamente de `r.PostForm` con esas claves; pruebas de cada formulario.
- **Multipart y límites de subida** → `http.MaxBytesReader` y `ParseMultipartForm` acotados por encima de 5 × 10 MB para
  que los límites de validación (no un corte de red) produzcan el mensaje en español.
- **Tabla creada por Go sin metadatos de Rails (`schema_migrations`)** → irrelevante tras retirar Rails; el rollback a
  Rails con un volumen creado por Go requeriría `db:prepare` manual (documentado en la guía de despliegue).
- **No hay LLM real en la validación** → los flujos de estimación se validan contra la API simulada, no contra
  proveedores; no se declara verificado ningún comportamiento que dependa de un LLM real.

## Migration Plan

1. Implementar y probar `estimator-web-go/` junto a Rails (Rails sigue como referencia).
2. Conmutar `estimator-web` en el Compose al servicio Go; actualizar `web-test`/`web-lint`, CI, `.env.example`, docs.
3. Validar el stack completo sin Rails y comparar con Rails.
4. Retirar `estimator-web/` y sus restos de configuración en un commit aparte.
- **Rollback**: `git revert` del commit de retirada y del de conmutación restituye Rails; la tabla es la misma.
