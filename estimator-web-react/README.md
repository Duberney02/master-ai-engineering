# estimator-web-react

Cliente web del estimador en React + TypeScript (capa 1). Solo habla HTTP con el backend de negocio
[`estimator-web-go`](../estimator-web-go/README.md) (capa 2, API JSON bajo `/api/`), que es el único cliente del servicio
de IA ([`estimador-cag`](../estimador-cag/README.md)). No tiene claves de proveedores ni conoce la dirección del servicio
de IA: el navegador habla solo con su propio origen y nginx reenvía `/api/` al backend, así que no hace falta CORS.

## Funcionalidad

- **Formulario** (`/`): descripción (20–80 000 caracteres) con contador, tipo de proyecto, nivel de detalle, formato de
  salida y versión de prompt. Admite cargar un `.txt` (UTF-8, máx. 400 KB) que sustituye a la descripción. Valida en el
  navegador (el backend repite la validación) y, al enviar, muestra un indicador de carga con temporizador. Si el backend
  falla conserva lo escrito.
- **Conversación con memoria**: al cargar la página abre una conversación (`POST /api/conversations`) y conserva su
  `conversation_id` en un contexto de React mientras la página siga abierta (una recarga abre otra conversación: el
  servicio de IA guarda las sesiones solo en memoria). Cada estimación va como `FormData` a
  `/api/conversations/{id}/estimations`. Permite **seleccionar varios adjuntos PDF o Word** (hasta 5 de 10 MB) y, con
  adjuntos, un mensaje corto. Si la conversación caduca abre otra, avisa y conserva lo escrito.
- **Barra lateral** a la izquierda: **metadatos del proyecto** con el botón **«Nueva conversación»**, prompt de sistema
  renderizado (`GET /api/prompt-preview`), ejemplos few-shot y métricas de la última llamada. En el formulario se actualiza
  al cambiar las opciones; se puede ocultar con «».
- **Historial** (`/estimations`): últimas 10 estimaciones. **Detalle** (`/estimations/:id`): resumen, confianza,
  duración, coste y tabla de fases; «No estimable» sin cifras con baja confianza.
- **Chunking Lab** (`/rag/chunking_comparisons`, `/new`, `/:id`): compara las ocho estrategias de chunking (las gratuitas
  vienen marcadas; las de pago avisan de su coste y de la clave que necesitan), con consultas predefinidas y propias y
  `top_k`. El resultado muestra estadísticas por estrategia, barras de coste y la recuperación por consulta; el historial
  (últimas 20) lo guarda el backend.
- **Ajustes** (`/ai_settings`): los siete modelos del LLM que se cambian en tiempo de ejecución (un valor vacío restablece
  el valor por defecto) y el modelo de embeddings, de solo lectura. La barra muestra el **modelo primario** vigente.
- **Errores saneados**: conexión o tiempo, 422 con el `detail` del backend, 404 y 5xx se traducen a mensajes en español,
  sin cuerpos crudos ni URLs internas.

## Estructura (`src/`)

| Módulo | Contenido |
|---|---|
| `components/Layout.tsx`, `WithSidebar.tsx` | cabecera con navegación e indicador del modelo primario; barra lateral |
| `pages/NewEstimationPage.tsx` + `components/EstimationForm.tsx` | formulario de estimación |
| `pages/HistoryPage.tsx`, `EstimationPage.tsx` | historial y detalle |
| `pages/ChunkingLabPage.tsx`, `ChunkingHistoryPage.tsx`, `ChunkingResultPage.tsx` + `components/ChunkingResult.tsx` | Chunking Lab |
| `pages/SettingsPage.tsx` + `hooks/usePrimaryModel.tsx` | Ajustes e indicador del modelo primario |
| `api/estimatorApi.ts` | único módulo con `fetch`: cliente del backend y errores saneados |
| `api/chunkingApi.ts`, `api/settingsApi.ts` | Chunking Lab y Ajustes |
| `lib/format.ts`, `lib/estimationForm.ts` | formato español y validación del formulario |

## Configuración

| Variable | Dónde | Por defecto | Uso |
|---|---|---|---|
| `API_UPSTREAM` | contenedor (nginx) | `http://estimator-web:3000` | dirección interna del backend Go |
| `ESTIMATOR_WEB_URL` | desarrollo (Vite) | `http://localhost:3000` | destino del proxy de `npm run dev` |

## Ejecución

Con todo el stack, desde la raíz del repositorio: `docker compose up --build` → <http://localhost:3001>.

Desarrollo local con el backend ya en marcha (Node 20.19 o posterior):

```bash
npm ci
npm run dev        # http://localhost:5173, con proxy de /api hacia ESTIMATOR_WEB_URL
```

Imagen aislada:

```bash
docker build -t estimator-web-react .
docker run --rm -p 3001:8080 -e API_UPSTREAM=http://host.docker.internal:3000 estimator-web-react
```

## Pruebas

Todo se ejecuta en Docker, desde la raíz del repositorio (`node_modules` vive en un volumen con nombre):

```bash
docker compose -f docker-compose.verify.yml run --rm web-react-test           # Vitest + Testing Library; fetch simulado
docker compose -f docker-compose.verify.yml run --rm web-react-test src/pages  # un subconjunto
docker compose -f docker-compose.verify.yml run --rm web-react-lint           # tsc --noEmit
```

Las pruebas no usan red ni claves: cubren las funciones puras de formato y validación, el cliente HTTP por código de
estado, los hooks, los componentes y las páginas completas con los escenarios de
`openspec/specs/estimator/web-react-client`, `web-chunking-lab` y `web-ai-settings`.
