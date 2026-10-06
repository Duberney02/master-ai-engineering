# Design

## Context

La web Rails (`estimator-web/`) es un cliente HTTP sin base de datos: un controlador (`EstimationsController`), un modelo de formulario (`EstimationForm`), un servicio (`EstimatorApi`), un helper de formato (`ApplicationHelper`) y cinco vistas ERB (`new`, `show`, `index`, `error`, parciales `_result` y `_sidebar`), con CSS y JavaScript en línea en el layout. Rails actúa además de BFF: la API no tiene CORS ni autenticación y los errores se saneaban en el servidor. Ver proposal.md para la motivación.

La nueva SPA corre en el navegador, así que esa frontera de saneado debe reproducirse en el cliente y la API debe seguir siendo inalcanzable por URL interna.

## Goals / Non-Goals

**Goals:**
- Paridad funcional y de textos con la web Rails, componente a componente.
- Cero cambios en la API y en la web Rails.
- Lógica pura (validación, formato, traducción de errores) aislada de los componentes y probada con Vitest sin red.

**Non-Goals:**
- Retirar la web Rails o redirigir su tráfico.
- Estado global (Redux, etc.), SSR, autenticación o internacionalización a otros idiomas.
- Streaming SSE del estimador (la web Rails tampoco lo usa).

## Decisions

**1. React + TypeScript + Vite, React Router, sin librería de estado ni de UI.** La app tiene tres pantallas y estado local; `useState`/`useEffect` bastan. Alternativas: Next.js (SSR innecesario y añade un servidor Node), CRA (obsoleto). El CSS del layout Rails se porta tal cual a una hoja global con las mismas variables y media queries, lo que garantiza paridad visual.

**2. Mismo origen mediante proxy inverso nginx, no CORS.** El contenedor sirve `dist/` y proxifica `/api/` y `/health` a `ESTIMATOR_API_URL` (plantilla nginx con `envsubst`), con `proxy_read_timeout 300s` y `client_max_body_size` ≥ 1 MB (80 000 caracteres de JSON). Alternativas: habilitar CORS en FastAPI (cambia la API, expone la API a cualquier origen y obliga a publicar su URL en el bundle) y un BFF Node (otro servicio que mantener). nginx se ejecuta sin privilegios (puerto 8080 interno publicado como 3001), con `/healthz` propio. En desarrollo, el proxy de Vite (`server.proxy`) cumple el mismo papel.

**3. Equivalencia de componentes Rails → React.**

| Rails | React |
|---|---|
| `layouts/application.html.erb` (+ script de la barra) | `Layout` (cabecera con `NavLink`, rejilla, `Outlet`) y `SidebarToggle` |
| `estimations/new` + script en línea | `NewEstimationPage`, `EstimationForm`, `LoadingIndicator` (spinner + temporizador), hook `useElapsedSeconds` |
| `_sidebar` | `PromptSidebar` (`SystemPrompt`, `FewShotExamples`, `LastCallMetrics`) |
| `_result` | `EstimationResult` (`MetricCard`, `PhasesTable`, `OutOfScopeAlert`) |
| `show` | `EstimationPage` (+ `EstimationMeta`, `DescriptionCard`) |
| `index` | `HistoryPage` (`HistoryTable`) |
| `error` | `ErrorPage` y `Alert` reutilizable (`role="alert"`) |
| `ApplicationHelper` | `lib/format.ts` (`labelFor`, `formatCost`, `formatWeeks`, `formatUsd`, `formatTime`, `cacheSourceLabel`, `outOfScopeReason`) con `Intl`/lógica explícita para el formato español |
| `EstimationForm` (modelo) | `lib/estimationForm.ts` (constantes, `validateForm`, `readTxtFile`) |
| `EstimatorApi` (Faraday) | `api/estimatorApi.ts` (`fetch` + `AbortController`, clase `EstimatorApiError{status}`) |
| `EstimationsController#load_sidebar` | hook `usePromptPreview(options)` (con descarte de respuestas obsoletas) |

**4. Paridad de formato sin depender del ICU del navegador.** Se prueban con casos fijos (`20.000,00 EUR`, `1,5 semanas`, `20/05/2026 10:00 UTC`); `formatTime` formatea con `getUTC*`, nunca con la zona local.

**5. Saneado en el cliente.** `estimatorApi.ts` es el único módulo que usa `fetch`. Convierte cualquier fallo en `EstimatorApiError` con los mismos mensajes que `EstimatorApi`; de un 400 solo toma `message` si es `string` no vacío (acotado a 300). Los componentes nunca ven `Response` ni cuerpos crudos. Los errores de red (`TypeError`) y el aborto por tiempo se mapean a «No se pudo conectar…».

**6. Lectura del `.txt` en el cliente.** Se valida extensión y tamaño antes de leer y se decodifica con `TextDecoder('utf-8', { fatal: true })`, quitando el BOM; esto reproduce los errores de `EstimationForm#load_upload` sin subir el archivo. Como Rails, el contenido sustituye al texto escrito. El envío es JSON (no multipart); la API ya recibe JSON desde Rails.

**7. Estado tras estimar.** Con `estimation_id` se navega a `/estimations/:id`; sin él, `NewEstimationPage` renderiza la vista de resultado en línea con los datos enviados (equivale al `render :show` de Rails). Los datos del formulario se conservan en el estado de la página, así que un error no los pierde (a diferencia de recargar).

**8. Pruebas.** Vitest + Testing Library + `vi.fn()` sobre `fetch` (sin red ni claves reales). Capas: funciones puras, cliente HTTP por códigos de estado, componentes y páginas (con temporizador simulado con `vi.useFakeTimers`). Los criterios `assert_select` de las pruebas Rails se trasladan a consultas por rol/etiqueta, conservando los `id` clave (`#cost`, `#phases`, `#timer`, `#last-call`) como `data-testid`/`id` para facilitar la comparación.

**9. Despliegue.** Dockerfile multietapa (`node:22-alpine` para `npm ci && npm run build`; `nginxinc/nginx-unprivileged` como runtime), servicio `estimator-web-react` en el compose raíz (3001:8080), `depends_on` la API saludable y healthcheck contra `/healthz`. Sin claves de proveedores.

## Risks / Trade-offs

- [El proxy nginx corta peticiones largas] → `proxy_read_timeout`/`send_timeout` de 300 s y prueba manual con una transcripción de 80 000 caracteres; el cliente usa el mismo límite.
- [Divergencia de textos o formatos con Rails] → mensajes y casos de formato copiados de las pruebas Rails a pruebas Vitest; revisión cruzada en la verificación.
- [Doble mantenimiento Rails/React] → fuera de alcance retirar Rails; se documenta en ambos README y queda como decisión posterior.
- [La barra lateral dispara una petición por cada cambio de opción] → `usePromptPreview` cancela la anterior con `AbortController`, y falla en silencio con el aviso, como `load_sidebar`.
- [`TextDecoder` con `fatal` y archivos de 400 KB] → es síncrono y rápido a este tamaño; sin riesgo de bloqueo apreciable.
- [Dependencias de npm nuevas] → versiones fijadas con `package-lock.json` y confinadas a `estimator-web-react/`.
