# estimator-web-go

Backend de negocio del estimador en **Go** (capa 2). Es un **API JSON** (`/api/...` más `GET /up`) sin HTML ni sesión de
navegador, y el **único cliente** del servicio de IA ([`estimador-cag`](../estimador-cag/README.md), Python/FastAPI), que
no cambia. Lo consumen los frontends: [`estimator-web-react`](../estimator-web-react/README.md) y
[`estimator-streamlit`](../estimator-streamlit/README.md).

```
React (:3001) ─┐
               ├──HTTP /api──▶ estimator-web (Go, :3000) ──JSON/multipart──▶ estimador-cag (FastAPI, :8000)
Streamlit (:8501) ┘                  └──▶ estimator-web-db (PostgreSQL): solo `chunking_comparisons`
```

Arquitectura, reglas y decisiones: [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## API

Todas las respuestas son JSON; los errores son `{"detail": "<mensaje saneado en español>"}` (nunca trazas, claves, URLs
internas ni cuerpos de proveedor). No hay cookies ni CSRF: el cliente conserva su `conversation_id`.

| Ruta | Uso |
|---|---|
| `GET /up` | Sonda de salud (200 sin consultar nada) |
| `POST /api/conversations` | Abre una conversación: `201 {"conversation_id"}` |
| `POST /api/conversations/{id}/estimations` | Estimación (multipart: `description`, `project_type`, `detail_level`, `output_format`, `prompt_version`, `upload` `.txt`, `attachments` PDF/Word). 422 entrada inválida, 404 conversación caducada |
| `GET /api/estimations?limit=` · `GET /api/estimations/{id}` | Historial (10 por defecto, máx. 50) y detalle |
| `GET /api/prompt-preview?prompt_version&project_type&detail_level&output_format` | Prompt de sistema y ejemplos few-shot |
| `GET /api/chunking-comparisons/options` | Catálogo de estrategias, selección por defecto, consultas predefinidas, `top_k` y tiempo de espera |
| `POST /api/chunking-comparisons` | Ejecuta y guarda una comparación (JSON `strategies`, `queries`, `top_k`): `201`, con `saved:false` y `notice` si no pudo guardarse |
| `GET /api/chunking-comparisons` · `GET /api/chunking-comparisons/{id}` | Últimas 20 (más reciente primero) y detalle (con la respuesta completa); 503 si no hay base de datos |
| `GET /api/ai-settings` · `PUT /api/ai-settings` | Los siete modelos del LLM en tiempo de ejecución (`{"models": {knob: string\|null}}`; `null` restablece) |
| `GET /api/primary-model` | `{"primary_model"}` vigente (caché 15 s; vacío si el servicio falla) |

## Todo se ejecuta en Docker

Nada se instala en el host. Desde la raíz del repositorio:

```sh
docker compose -f docker-compose.verify.yml run --rm web-test               # go test -p 1 ./... (con PostgreSQL efímero)
docker compose -f docker-compose.verify.yml run --rm web-test ./internal/httpapi/... -run Lab   # un subconjunto
docker compose -f docker-compose.verify.yml run --rm web-lint               # gofmt + go vet
docker compose -f docker-compose.verify.yml run --rm web-go mod tidy        # dependencias del módulo (go …)
docker compose up --build                                                    # stack completo (backend en :3000)
```

Las pruebas nunca llaman a la API real ni usan claves: la API de IA se simula con `httptest`. Las de persistencia usan
el PostgreSQL efímero `web-db` (variable `TEST_DATABASE_URL`).

Para construir solo la imagen de producción: `docker build -t estimator-web estimator-web-go` (distroless, usuario
`nonroot`, sin shell; el healthcheck lo hace el propio binario: `/estimator-web healthcheck`).

## Configuración

| Variable | Por defecto | Uso |
|---|---|---|
| `ESTIMATOR_API_URL` | `http://localhost:8000` | URL del servicio de IA (en Compose, `http://estimador-cag:8000`); **solo este servicio la recibe** |
| `ESTIMATOR_OPEN_TIMEOUT` | `5` | segundos para conectar |
| `ESTIMATOR_READ_TIMEOUT` | `300` | segundos de espera global (estimaciones largas) |
| `ESTIMATOR_COMPARE_TIMEOUT` | `600` | segundos de espera **solo** de la comparación del Chunking Lab |
| `ESTIMATOR_BADGE_TIMEOUT` | `2` | segundos de la consulta del modelo primario |
| `DATABASE_URL` | — | PostgreSQL del historial del Chunking Lab; sin ella, el Lab calcula pero no guarda |
| `PORT` | `3000` | puerto de escucha |

El servicio no recibe claves de proveedores: solo habla con el servicio de IA.

## Base de datos

Una sola tabla, `chunking_comparisons` (estrategias, consultas, `top_k`, corpus, respuesta completa en JSONB, duración).
Al arrancar se ejecuta `CREATE TABLE IF NOT EXISTS`: un volumen existente se reutiliza tal cual y uno vacío se
inicializa. Si la base falla, el Lab devuelve igualmente el resultado recién calculado (`saved:false`) y el resto de
endpoints siguen funcionando.
