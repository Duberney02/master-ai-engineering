# estimator-web-go

Servicio web del estimador en **Go**. Es el único punto de entrada de los navegadores al estimador: renderiza en servidor
(HTML) las pantallas de estimaciones, el Chunking Lab y los Ajustes, y habla por HTTP con la API de IA
([`estimador-cag`](../estimador-cag/README.md), Python/FastAPI), que no cambia. Sustituye al cliente Rails que existió
antes (cambio OpenSpec `migrar-backend-rails-a-go`); conserva sus rutas, HTML, mensajes y estados HTTP.

```
Navegador ──HTML──▶ estimator-web (Go, :3000) ──JSON/multipart──▶ estimador-cag (FastAPI, :8000)
                          └──▶ estimator-web-db (PostgreSQL): solo `chunking_comparisons`
```

Arquitectura, reglas y decisiones: [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Pantallas y rutas

| Ruta | Pantalla |
|---|---|
| `GET /` | Inicio: una tarjeta por contexto |
| `GET /estimations/new` · `POST /estimations` | Formulario (descripción, `.txt`, adjuntos PDF/Word) y envío |
| `GET /estimations` · `GET /estimations/{id}` | Historial y resultado de una estimación |
| `POST /conversation` | «Nueva conversación» |
| `GET /rag/chunking_comparisons[/new]` · `POST …` · `GET …/{id}` | Chunking Lab: formulario, ejecución, historial y detalle |
| `GET /ai_settings` · `PATCH\|PUT /ai_settings` | Modelos del LLM en tiempo de ejecución |
| `GET /up` | Sonda de salud (200 sin consultar nada) |

## Todo se ejecuta en Docker

Nada se instala en el host. Desde la raíz del repositorio:

```sh
docker compose -f docker-compose.verify.yml run --rm web-test               # go test -p 1 ./... (con PostgreSQL efímero)
docker compose -f docker-compose.verify.yml run --rm web-test ./internal/web/... -run Lab   # un subconjunto
docker compose -f docker-compose.verify.yml run --rm web-lint               # gofmt + go vet
docker compose -f docker-compose.verify.yml run --rm web-go mod tidy        # dependencias del módulo (go …)
docker compose up --build                                                    # stack completo (web en :3000)
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
| `SECRET_KEY_BASE` | aleatorio por proceso | firma de la cookie de sesión; defínelo para conservar las conversaciones entre reinicios |
| `PORT` | `3000` | puerto de escucha |

El servicio no recibe claves de proveedores: solo habla con la API de IA.

## Base de datos

Una sola tabla, `chunking_comparisons` (estrategias, consultas, `top_k`, corpus, respuesta completa en JSONB, duración).
Al arrancar se ejecuta `CREATE TABLE IF NOT EXISTS` con el mismo esquema que tenía Rails: un volumen existente se
reutiliza tal cual y uno vacío se inicializa. Si la base falla, el Lab muestra igualmente el resultado recién calculado
con un aviso y el resto de pantallas siguen funcionando.

## Diferencias respecto al cliente Rails

- La **cookie de sesión** ya no es la de Rails (cifrada con `SECRET_KEY_BASE`): ahora es JSON firmado con HMAC-SHA256.
  Tras el despliegue, las conversaciones abiertas se reinician una vez.
- Si la API cae justo al abrir la conversación de reemplazo tras una sesión caducada, Rails devolvía un 500; el servicio
  Go muestra el error saneado en el formulario (422).
- El *read timeout* se aplica a la espera de la respuesta completa de la API, no a cada lectura de socket.
- El resto (HTML, textos, estados, límites, formato de números y fechas) es equivalente; ver
  `openspec/changes/migrar-backend-rails-a-go/verification.md`.
