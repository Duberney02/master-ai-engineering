## Context

Estado actual (verificado en el código el 2026-11-08):

```
estimator-web-react ──/api/ (nginx proxy_pass API_UPSTREAM)──▶ estimador-cag   (se salta la capa 2)
streamlit_app.py ────ESTIMATOR_API_BASE_URL (httpx)──────────▶ estimador-cag   (vive dentro de estimador-cag)
estimator-web-go (HTML + cookie + CSRF) ──internal/estimatorai─▶ estimador-cag
```

Objetivo:

```
Capa 1  estimator-web-react · estimator-streamlit      solo HTTP al backend
Capa 2  estimator-web-go (API JSON `/api/...` + /up)   único cliente del servicio IA
Capa 3  estimador-cag                                  sin cliente embebido
```

## Inventario: web Go vs React

Fuente: `estimator-web-go/internal/web` (rutas en `server.go`, plantillas en `templates/`) frente a
`estimator-web-react/src` (`App.tsx`, `pages/`, `api/`).

| Funcionalidad (web Go) | Ruta Go | ¿Existe en React? | Acción |
|---|---|---|---|
| Nueva estimación (formulario, contador, `.txt`, adjuntos, temporizador) | `GET /estimations/new`, `POST /estimations` | **Sí** (`/`, `NewEstimationPage`) | Solo repuntar el cliente HTTP al backend Go |
| Conversación con memoria, metadatos, «Nueva conversación», sesión caducada | `POST /conversation` | **Sí** (`useConversation`) | Ídem |
| Resultado de la estimación y flujo con/sin `estimation_id` | `GET /estimations/{id}` | **Sí** (`EstimationPage`, `EstimationResult`) | Ídem |
| Historial de estimaciones | `GET /estimations` | **Sí** (`HistoryPage`) | Ídem |
| Barra lateral: prompt, few-shot, métricas | (en cada vista) | **Sí** (`PromptSidebar`, `usePromptPreview`) | Ídem |
| Página de error / 404 | `/404.html` y plantilla de error | **Sí** (`ErrorPage`, `NotFoundPage`) | Ninguna |
| **Chunking Lab: formulario** (8 estrategias, avisos de coste, consultas, `top_k`) | `GET /rag/chunking_comparisons/new` | **No** | **Migrar** |
| **Chunking Lab: ejecutar comparación** y guardar en PostgreSQL | `POST /rag/chunking_comparisons` | **No** | **Migrar** (el guardado sigue en el backend Go) |
| **Chunking Lab: historial** (últimas 20) | `GET /rag/chunking_comparisons` | **No** | **Migrar** |
| **Chunking Lab: resultado** (tabla de estadísticas, barras de coste, playground top-k) | `GET /rag/chunking_comparisons/{id}` | **No** | **Migrar** |
| **Ajustes de IA** (7 knobs, catálogo, overrides, chunkers por proveedor) | `GET /ai_settings` | **No** | **Migrar** |
| **Guardar ajustes** (`null` = valor por defecto) | `PATCH/PUT /ai_settings` | **No** | **Migrar** |
| **Indicador del modelo primario** en la barra (caché 15 s, tolerante a fallos) | `badgeCache` | **No** | **Migrar** (el backend expone `GET /api/primary-model`) |
| Inicio: panel con una tarjeta por contexto | `GET /{$}` | No (en React `/` es el formulario) | **No migrar**: la barra de navegación de React enlaza los contextos; no se rediseña la UI |
| `robots.txt`, `404/422/500.html` | `public/` | n/a (SPA) | Se eliminan con el HTML del backend |

Lista exacta de lo migrado: Chunking Lab (formulario, ejecución, historial, resultado), Ajustes de IA (lectura y
guardado) e indicador del modelo primario. Rutas React nuevas: `/rag/chunking_comparisons`,
`/rag/chunking_comparisons/new`, `/rag/chunking_comparisons/:id` y `/ai_settings` (mismas URL que tenía el backend Go,
para no romper marcadores). Navegación: enlaces «Chunking Lab» y «Ajustes» en el `Layout`.

## Goals / Non-Goals

**Goals**

- Tres capas estrictas con la regla central: solo `estimator-web-go` llama a `estimador-cag`.
- Paridad funcional y de mensajes de lo migrado (validaciones, errores saneados, estados de carga).
- Streamlit totalmente desacoplado (carpeta, imagen, dependencias, tests).

**Non-Goals**

- Cambiar el contrato HTTP de `estimador-cag` o añadirle endpoints.
- Rediseñar la UI de React o Streamlit más allá de la paridad.
- Migrar a React lo que ya tiene.
- Cambiar el esquema de `chunking_comparisons` ni la base de datos del Lab.

## Decisions

### 1. Prefijo y contrato del backend: `/api/...` (sin `/v1`)

Se evita `/api/v1/...` a propósito: es el espacio de rutas de `estimador-cag` y los clientes no deben poder confundir
ambos contratos. El backend reexpone con **recursos propios**; los cuerpos de estimación reutilizan la forma JSON de la
API de IA (el backend la encapsula, no la rediseña) y los clientes solo dependen del contrato de este backend.

| Método y ruta | Cuerpo | Respuesta |
|---|---|---|
| `GET /up` | — | 200, sin consultar API ni BD |
| `POST /api/conversations` | — | 201 `{"conversation_id"}` |
| `POST /api/conversations/{id}/estimations` | multipart: `description`, `project_type`, `detail_level`, `output_format`, `prompt_version`, `upload` (.txt, opcional), `attachments` (0–5) | 200 con la estimación (`result`, `metrics`, `estimation_id`, `project_metadata`, …); 404 sesión caducada |
| `GET /api/estimations?limit=` | — | lista (10 por defecto) |
| `GET /api/estimations/{id}` | — | estimación o 404 |
| `GET /api/prompt-preview?prompt_version&project_type&detail_level&output_format` | — | `system_prompt` y ejemplos few-shot |
| `GET /api/chunking-comparisons/options` | — | estrategias (etiqueta, descripción, coste, clave requerida), seleccionadas por defecto, consultas predefinidas, `top_k` por defecto, `compare_timeout_seconds` |
| `POST /api/chunking-comparisons` | JSON `{strategies[], queries[], top_k}` | 201 comparación (`id`, estadísticas, top-k) |
| `GET /api/chunking-comparisons` | — | últimas 20 (más reciente primero) |
| `GET /api/chunking-comparisons/{id}` | — | comparación o 404 |
| `GET /api/ai-settings` | — | catálogo de los 7 knobs (valor por defecto, vigente, override, modelos del catálogo) |
| `PUT /api/ai-settings` | JSON `{"models": {knob: string\|null}}` | catálogo actualizado |
| `GET /api/primary-model` | — | `{"primary_model": ""\|"<modelo>"}` (caché 15 s; vacío si el servicio falla) |

Errores: JSON `{"detail": "<mensaje saneado en español>"}` con el estado HTTP que ya documenta
`estimator-web-go/ARCHITECTURE.md` («Mapeo de errores»): 422 entrada o rechazo, 404, 502, 503, 504. Nunca trazas, claves,
URLs internas ni cuerpos de proveedor (el detalle va al log con `slog`). Sin la base de datos del Lab, el historial
responde 503 con «El historial no está disponible en este momento.» y una comparación recién calculada se devuelve igualmente
(201 con `saved: false` y el aviso), como hoy.

### 2. API sin estado de navegador

La cookie firmada, el *flash* y el CSRF existían para renderizar HTML. Un API JSON consumido por una SPA del mismo
origen (nginx) y por Streamlit (servidor a servidor) no usa cookies, así que **no hay CSRF que proteger**: se elimina
`internal/session`. El cliente conserva el `conversation_id` (React en memoria de la página, Streamlit en
`st.session_state`), igual que ya hacían contra la API de IA. Los metadatos del proyecto vuelven en cada respuesta; no se
compactan para una cookie.

*Alternativa descartada*: conservar la cookie de sesión en el backend. Acopla el API a un navegador, obliga a Streamlit a
gestionar cookies y mantiene CSRF sin necesidad.

### 3. Validación en el backend, además de la del cliente

`internal/estimation` (reglas de descripción, `.txt`, adjuntos) se reutiliza en el handler de estimaciones: es la
fuente de verdad. React ya valida en el cliente (UX inmediata) y Streamlit valida con constantes locales
(20–80 000 caracteres, UTF-8, 400 000 bytes); si un cliente se salta la validación, el backend responde 422 con el mismo
mensaje.

### 4. Capa HTTP intacta

`internal/estimatorai` sigue siendo la única puerta a `estimador-cag` (regla de `archtest`). El paquete de transporte
`internal/web` se renombra a `internal/httpapi` para no sugerir HTML. Se conservan `internal/rag` (contratos,
estrategias, `PgStore`), `internal/ai`, `internal/estimation`, `internal/jsondoc` y el subcomando `healthcheck`. Se
elimina el resto de la parte web: `templates/`, `public/`, `format.go`, `html/template`, `embed`, `_method` override,
CSRF y `internal/session`.

### 5. React

- `src/api/estimatorApi.ts` pasa a llamar a las rutas `/api/...` del backend (mismos nombres de funciones y errores para
  no tocar a los consumidores) y se añaden `chunkingApi.ts` y `settingsApi.ts`.
- Nuevas páginas: `ChunkingLabPage` (formulario y ejecución), `ChunkingHistoryPage`, `ChunkingResultPage`,
  `SettingsPage`; componente `PrimaryModelBadge` en `Layout` (omite el indicador si falla).
- nginx: `API_UPSTREAM=http://estimator-web:3000`; `proxy_read_timeout` de 600 s para `/api/chunking-comparisons`
  (el Lab usa `ESTIMATOR_COMPARE_TIMEOUT`). `location = /health` (proxy al servicio IA) **se elimina**: React no debe
  tener ninguna referencia de red a `estimador-cag`.
- Pruebas: las existentes (Vitest, API simulada con `mockApi.ts`) se ajustan a las rutas nuevas y se añaden las de las
  pantallas migradas. Servicio `web-react-test` y `web-react-lint` (Docker, imagen Node) en `docker-compose.verify.yml`.

### 6. Streamlit: carpeta `estimator-streamlit/`

Se mantiene el nombre por defecto `estimator-streamlit/` (coherente con `estimator-web-go` y `estimator-web-react`).
Contenido: `streamlit_app.py`, `client.py` (HTTP con `httpx` hacia `ESTIMATOR_WEB_URL`; antes `streamlit_client.py`),
`support.py` (`decode_transcript`; antes `streamlit_support.py`), `models.py`, `Dockerfile`, `pyproject.toml`, `uv.lock`,
`README.md`, `.dockerignore`, `tests/`. Nada importa de `estimador-cag/app`:

- `app.domain.schemas` (enums, límites de descripción, `EstimationResult`, `ProjectMetadata`) → modelos Pydantic locales
  mínimos (`models.py`) que describen solo el contrato JSON del backend Go.
- `render_system_prompt` / `few_shot_examples` → `GET /api/prompt-preview` (el prompt lo renderiza el servicio IA a
  través del backend; Streamlit ya no necesita las plantillas Jinja).
- `ESTIMATOR_API_BASE_URL` → `ESTIMATOR_WEB_URL` (defecto `http://localhost:3000`).
- Se descartan `request_structured_estimation`, `stream_estimation`, `parse_sse`, `sync_secrets_to_env` e `iter_sync`:
  `streamlit_app.py` solo usa `create_session` y `request_session_estimation`. Sin código muerto.

Imagen propia (Python 3.11, uv), sin claves de proveedor. Servicios `streamlit-test` y `streamlit-lint` (`pytest`,
`ruff`) en `docker-compose.verify.yml`.

### 7. Compose

- `estimador-cag-chat`: `build: ./estimator-streamlit`, `ESTIMATOR_WEB_URL: http://estimator-web:3000`,
  `depends_on: estimator-web (healthy)`; sin `image: estimador-cag:latest`. Puerto 8501.
- `estimator-web-react`: `API_UPSTREAM: http://estimator-web:3000`, `depends_on: estimator-web (healthy)`.
- `estimator-web`: se retira `SECRET_KEY_BASE` de configuración y Compose (sin sesión no hay secreto).
- `estimador-cag/docker-compose.yml` (solo backend con recarga): se quita el servicio y el volumen de Streamlit.
- `estimador-cag/.env.example`: se retira la variable «solo Streamlit».

### 8. Verificación de la regla central

Pruebas automatizadas: `estimator-streamlit` sin imports de `app.`; test de configuración que impide referencias a
`estimador-cag` en nginx y Compose de los clientes. Comprobación manual con `docker compose config` y búsqueda de
`estimador-cag`, `:8000` y `/api/v1` en `estimator-web-react/` y `estimator-streamlit/`: cero referencias de red.

## Risks / Trade-offs

- **Dos saltos para adjuntos grandes** (cliente → backend → IA): límites alineados (nginx 55 MB, Go `maxBodyBytes`
  64 MB, adjuntos de 10 MB). Cubierto por pruebas del handler.
- **Streamlit pierde el render local del prompt**: pasa a depender del backend. Si falla, la barra lateral avisa y el
  resto sigue.
- **`web-client` queda sin requisitos**: documentaba el cliente Rails, ya retirado. Si `openspec archive` no admite una
  spec vacía, se elimina la carpeta de la capability al archivar.
- **Renombrar `internal/web` → `internal/httpapi`**: diff grande, pero evita un paquete `web` que ya no sirve web; la
  regla de `archtest` se actualiza a la vez.
- **Sin sesión de navegador**: un cliente que no guarde el `conversation_id` abre una conversación por visita; es el
  comportamiento que ya tienen React y Streamlit.

## Migration Plan

1. API JSON en Go junto a las rutas HTML (se prueba antes de borrar).
2. React migra a `/api/...` + pantallas nuevas; nginx → `estimator-web`.
3. Se borra la parte web de Go.
4. Streamlit nuevo (carpeta, imagen, tests) contra el backend.
5. Limpieza de `estimador-cag` (dependencia, Dockerfile, docs, `uv.lock`).
6. Compose, verificación E2E (`docker compose up --build`) y documentación.

Rollback: revertir el PR (el contrato de `estimador-cag` y la BD del Lab no cambian).

## Open Questions

- Ninguna que cambie el alcance. Decidido: el historial del Chunking Lab sigue en la base propia del backend Go
  (`estimator-web-db`, tabla `chunking_comparisons`, sin cambios de esquema).
