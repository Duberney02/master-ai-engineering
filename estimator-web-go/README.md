# estimator-web-go

Backend **Go** del estimador. Es la única puerta de los clientes de navegador (React) hacia la API de IA
([`estimador-cag`](../estimador-cag/README.md), Python/FastAPI): expone una API REST y SSE bajo `/api/`, aplica la
autorización administrativa y la validación de origen de las mutaciones, y guarda en su PostgreSQL el historial del
Chunking Lab. **No sirve HTML de aplicación**: el cliente Rails, y después el cliente HTML propio de Go, se retiraron
(cambios OpenSpec `migrar-backend-rails-a-go` y `homelab-route-clients-through-go`, tareas 10.1 y 10.2).

```
React (nginx) ──/api/*──▶ estimator-web (Go, :3000) ──JSON/multipart/SSE──▶ estimador-cag (FastAPI, :8000)
                                └──▶ estimator-web-db (PostgreSQL): solo `chunking_comparisons`
```

Arquitectura, reglas y decisiones: [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Rutas

| Ruta | Uso |
|---|---|
| `POST /api/v1/sessions` · `POST /api/v1/sessions/{session_id}/estimate` | Conversación: abrir sesión y enviar un turno (multipart con adjuntos o formulario) |
| `POST /api/v1/estimate` · `POST /api/v1/estimate/stream` · `POST /api/v1/transcription/estimate/stream` | Estimación JSON y flujos SSE |
| `GET /api/v1/prompts/estimation` · `GET /api/v1/estimations[/{estimation_id}]` | Vista previa del prompt, historial y detalle |
| `GET\|PUT /api/v1/ai/settings` · `GET /api/v1/ai/primary-model` | Ajustes de modelos (administrativo) e indicador del primario |
| `GET /api/v1/rag/chunking-comparisons[/options\|/{id}]` · `POST …` | Chunking Lab (administrativo): opciones, historial, detalle y ejecución |
| `GET /health` | Sonda de la API de IA a través de Go (503 saneado si no responde) |
| `GET /up` | Sonda local de Go: 200 `text/plain` sin consultar IA ni PostgreSQL (healthcheck de la imagen) |

Cualquier otra ruta, incluidas las del antiguo cliente HTML (`/`, `/estimations…`, `/conversation`, `/ai_settings`,
`/rag/chunking_comparisons…`, `/robots.txt`, `/404.html`…), responde `404` JSON sin llamar a IA. Las mutaciones del
navegador exigen un `Origin` igual a `ESTIMATOR_PUBLIC_ORIGIN` (o al `Host` recibido si no está definido); las llamadas
sin `Origin` de clientes HTTP no navegador se aceptan en las rutas sin autenticación ambiental. Las rutas administrativas
deniegan por defecto (403) hasta integrar identidad.

## Todo se ejecuta en Docker

Nada se instala en el host. Desde la raíz del repositorio:

```sh
docker compose -f docker-compose.verify.yml run --rm web-test               # go test -p 1 ./... (con PostgreSQL efímero)
docker compose -f docker-compose.verify.yml run --rm web-test ./internal/web/... -run Lab   # un subconjunto
docker compose -f docker-compose.verify.yml run --rm web-lint               # gofmt + go vet
docker compose -f docker-compose.verify.yml run --rm web-go mod tidy        # dependencias del módulo (go …)
docker compose up --build                                                    # stack completo (Go en :3000, React en :3001)
```

Las pruebas nunca llaman a la API real ni usan claves: la API de IA se simula con `httptest`. Las de persistencia usan
el PostgreSQL efímero `web-db` (variable `TEST_DATABASE_URL`).

Para construir solo la imagen de producción: `docker build -t estimator-web estimator-web-go` (distroless, usuario
`nonroot`, sin shell; el healthcheck lo hace el propio binario: `/estimator-web healthcheck`).

## Configuración

| Variable | Por defecto | Uso |
|---|---|---|
| `ESTIMATOR_API_URL` | `http://localhost:8000` | URL de la API de IA (en Compose, `http://estimador-cag:8000`) |
| `ESTIMATOR_OPEN_TIMEOUT` | `5` | segundos para conectar |
| `ESTIMATOR_READ_TIMEOUT` | `300` | segundos de espera global (estimaciones largas) |
| `ESTIMATOR_COMPARE_TIMEOUT` | `600` | segundos de espera **solo** de la comparación del Chunking Lab |
| `ESTIMATOR_BADGE_TIMEOUT` | `2` | segundos del indicador del modelo primario de la barra |
| `DATABASE_URL` | — | PostgreSQL del historial del Chunking Lab; sin ella, el Lab calcula pero no guarda |
| `ESTIMATOR_PUBLIC_ORIGIN` | — | origen canónico de las mutaciones del navegador (obligatorio tras un proxy que no conserva el `Host`) |
| `PORT` | `3000` | puerto de escucha |

El servicio no recibe claves de proveedores: solo habla con la API de IA. `SECRET_KEY_BASE` ya no existe: la cookie de sesión HTML se retiró y la variable, si el entorno aún la define, se ignora. Los plazos públicos y de streaming tienen sus propias variables `ESTIMATOR_*_TIMEOUT` (véase `internal/config/config.go`).

## Base de datos

Una sola tabla, `chunking_comparisons` (estrategias, consultas, `top_k`, corpus, respuesta completa en JSONB, duración).
Al arrancar se ejecuta `CREATE TABLE IF NOT EXISTS` con el mismo esquema que tenía Rails: un volumen existente se
reutiliza tal cual y uno vacío se inicializa. Los IDs son `bigint` y la API los devuelve como texto decimal. Si la base
falla, la API del Lab devuelve igualmente el resultado recién calculado con un aviso (ID y fecha nulos) y el resto de
rutas siguen funcionando.

## Retirada del cliente HTML

Se retiraron las plantillas y estáticos, las rutas HTML, `html/template`, el paquete de sesión (cookie firmada, avisos
flash y CSRF de formulario), `_method`, las funciones de presentación y `SECRET_KEY_BASE`. Se conservan los casos de uso,
las validaciones (`internal/estimation`), los adaptadores `internal/estimatorai`, el corpus, el repositorio PostgreSQL,
la recuperación de pánicos, el registro saneado, la validación de origen, los límites, `/up` y la propagación de
`FlushError`, `Unwrap` y los plazos de streaming. Si un navegador aún envía la cookie `_estimator_web_session`, el
servicio la expira (`Max-Age=0`) y no la lee. La correspondencia entre las pruebas HTML retiradas y la cobertura vigente
está en [`EVIDENCIA-RETIRADA-HTML.md`](./EVIDENCIA-RETIRADA-HTML.md).
