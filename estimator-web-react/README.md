# estimator-web-react

Versión React + TypeScript de la web del [estimador](../estimador-cag/README.md), con la misma funcionalidad que la
[web Rails](../estimator-web/README.md) (que se conserva). No tiene claves de proveedores: el navegador habla solo con
su propio origen y nginx reenvía `/api/` y `/health` a la API, así que no hace falta CORS ni exponer la URL de la API.

## Funcionalidad

- **Formulario** (`/`): descripción (20–80 000 caracteres) con contador, tipo de proyecto, nivel de detalle, formato de
  salida y versión de prompt. Admite cargar un `.txt` (UTF-8, máx. 400 KB) que sustituye a la descripción. Valida en el
  navegador con los mismos mensajes que Rails y, al enviar, muestra un indicador de carga con temporizador. Si la API
  falla conserva lo escrito.
- **Conversación con memoria**: al cargar la página crea una sesión (`POST /api/v1/sessions`) y conserva su
  `session_id` en un contexto de React mientras la página siga abierta (una recarga abre otra conversación: la API guarda
  las sesiones solo en memoria). Cada estimación va como `FormData` a `/api/v1/sessions/{id}/estimate`. Permite
  **seleccionar varios adjuntos PDF o Word** (hasta 5 de 10 MB; la API extrae su texto) y, con adjuntos, un mensaje corto.
  Si la API pierde la sesión abre otra, avisa y conserva lo escrito.
- **Barra lateral** a la izquierda: **metadatos del proyecto** de la conversación con el botón **«Nueva conversación»**
  (crea otra sesión y reinicia el formulario), prompt de sistema renderizado, ejemplos few-shot y métricas de la última
  llamada. En el formulario se actualiza al cambiar las opciones; se puede ocultar con «».
- **Historial** (`/estimations`): últimas 10 estimaciones. **Detalle** (`/estimations/:id`): resumen, confianza,
  duración, coste y tabla de fases; «No estimable» sin cifras con baja confianza.
- **Errores saneados**: conexión o tiempo, 400 de guardrails, 422, 404 y 5xx se traducen a mensajes en español, sin
  cuerpos crudos ni URLs internas.

## Equivalencias con Rails

| Rails (`estimator-web`) | React (`src/`) |
|---|---|
| `layouts/application.html.erb` | `components/Layout.tsx`, `components/WithSidebar.tsx` (botón « de la barra) |
| `estimations/new` + script en línea | `pages/NewEstimationPage.tsx`, `components/EstimationForm.tsx`, `hooks/useElapsedSeconds.ts` |
| `estimations/_sidebar` | `components/PromptSidebar.tsx`, `hooks/usePromptPreview.ts` |
| `estimations/_result` | `components/EstimationResult.tsx` |
| `estimations/show` | `pages/EstimationPage.tsx`, `components/EstimationDetail.tsx` |
| `estimations/index` | `pages/HistoryPage.tsx` |
| `estimations/error` | `components/ErrorPage.tsx` (y `NotFoundPage`) |
| `ApplicationHelper` | `lib/format.ts` |
| `EstimationForm` (modelo) | `lib/estimationForm.ts` |
| `EstimatorApi` (Faraday) | `api/estimatorApi.ts` |

## Configuración

| Variable | Dónde | Por defecto | Uso |
|---|---|---|---|
| `API_UPSTREAM` | contenedor (nginx) | `http://estimador-cag:8000` | dirección interna de la API |
| `ESTIMATOR_API_URL` | desarrollo (Vite) | `http://localhost:8000` | destino del proxy de `npm run dev` |

## Ejecución

Con todo el stack, desde la raíz del repositorio: `docker compose up --build` → <http://localhost:3001>.

Desarrollo local con una API ya en marcha (Node 20.19 o posterior):

```bash
npm ci
npm run dev        # http://localhost:5173, con proxy de /api hacia ESTIMATOR_API_URL
```

Imagen aislada:

```bash
docker build -t estimator-web-react .
docker run --rm -p 3001:8080 -e API_UPSTREAM=http://host.docker.internal:8000 estimator-web-react
```

## Pruebas

```bash
npm test           # Vitest + Testing Library; sin red ni claves (fetch simulado)
npm run build      # comprueba tipos (tsc) y compila
```

Sin Node local, en Docker (con `node_modules` en un volumen, sin escribir en el directorio del proyecto):

```bash
docker run --rm -v "$PWD:/src:ro" -v react_nm:/app/node_modules -w /app node:22-alpine sh -c \
  "cp -r /src/package.json /src/package-lock.json /src/tsconfig.json /src/vite.config.ts /src/index.html /src/src . && npm ci && npm test && npm run build"
```

Las pruebas cubren las funciones puras de formato y validación, el cliente HTTP por código de estado, los hooks, los
componentes y las páginas completas con los escenarios de `openspec/specs/estimator/web-react-client`.
