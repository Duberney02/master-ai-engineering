# Tasks

## 1. Andamiaje del proyecto

- [x] 1.1 Crear `estimator-web-react/` con Vite + React + TypeScript (estricto), React Router, Vitest y Testing Library; verificar que `npm ci && npm run build && npm test` terminan sin errores.
- [x] 1.2 Configurar el proxy de desarrollo de Vite (`/api`, `/health` → `ESTIMATOR_API_URL`, por defecto `http://localhost:8000`); verificar con la API en marcha que `curl localhost:5173/api/v1/estimations` responde.
- [x] 1.3 Portar el CSS del layout Rails (variables, modo oscuro, rejilla, `@media (max-width:800px)`) a una hoja global y fijar `lang="es"` y el título; verificar visualmente en claro, oscuro y ancho estrecho.

## 2. Lógica pura y cliente HTTP

- [x] 2.1 Implementar `lib/format.ts` (`labelFor`, `formatCost`, `formatWeeks`, `formatUsd`, `formatTime`, `cacheSourceLabel`, `outOfScopeReason`, formato de miles) y sus pruebas con los casos de `ApplicationHelper` (`20.000,00 EUR`, `1,5 semanas`, `Sin tarifa`, fecha UTC); verificar que pasan.
- [x] 2.2 Implementar `lib/estimationForm.ts` (constantes de opciones y límites, `validateForm`, `readTxtFile` con extensión, 400 000 bytes y UTF-8 estricto sin BOM) y sus pruebas con los mensajes exactos de `EstimationForm`; verificar que pasan.
- [x] 2.3 Implementar `api/estimatorApi.ts` (`createEstimation`, `listEstimations`, `promptPreview`, `findEstimation`, `EstimatorApiError`) con tiempos de espera, validación de contrato y mensajes saneados; escribir pruebas por estado (200, 400, 404, 422, 503, 5xx, red caída, tiempo agotado, cuerpo no JSON, id inválido sin llamada) y verificar que ningún mensaje contiene cuerpos crudos ni URLs.
- [x] 2.4 Añadir los hooks `useElapsedSeconds` y `usePromptPreview` (cancelación de peticiones obsoletas, fallo silencioso) con pruebas usando temporizadores simulados; verificar que pasan.

## 3. Componentes de presentación

- [x] 3.1 Implementar `Layout`, `NavLink` de cabecera y `SidebarToggle` (`aria-controls`, `aria-expanded`, ««/»») con pruebas de navegación y de ocultar/mostrar la barra; verificar que pasan.
- [x] 3.2 Implementar `PromptSidebar` (prompt de solo lectura, few-shot, `LastCallMetrics`, estados «sin métricas» y «prompt no disponible») con pruebas de los tres estados; verificar que pasan.
- [x] 3.3 Implementar `EstimationResult` (`MetricCard`, `PhasesTable`, `OutOfScopeAlert`), `EstimationMeta` y `DescriptionCard` (truncado a 2 000 con total) con pruebas de resultado estimable, `out_of_scope` sin cifras y descripción larga; verificar que pasan.
- [x] 3.4 Implementar `Alert` (`role="alert"`) y `ErrorPage` con enlaces al historial y a nueva estimación, y la página 404 de rutas desconocidas; verificar con pruebas de render.

## 4. Páginas y flujos

- [x] 4.1 Implementar `EstimationForm` y `NewEstimationPage`: contador, carga de `.txt`, validación previa, indicador con temporizador (`role="status"`), botón deshabilitado y rehabilitado, conservación de datos tras error y barra lateral reactiva a las opciones; verificar con pruebas de los escenarios del spec (válida, archivo inválido, fuera de rango, guardrail 400, API caída).
- [x] 4.2 Implementar el flujo tras estimar: navegar a `/estimations/:id` con `estimation_id` y mostrar el resultado en línea sin él; verificar con pruebas de ambos escenarios.
- [x] 4.3 Implementar `EstimationPage` y `HistoryPage` (`HistoryTable`, vacío, 503 con aviso, `No estimable`, extracto de 90 caracteres, id inválido sin llamada); verificar con pruebas de los escenarios del spec.
- [x] 4.4 Revisión de accesibilidad y paridad: comparar textos, ids y roles con las pruebas `assert_select` de `estimator-web/test/controllers`, y ejecutar `npm run build` y `npm test` completos; verificar que no hay diferencias sin justificar.

## 5. Despliegue y documentación

- [x] 5.1 Crear `estimator-web-react/Dockerfile` multietapa y `nginx.conf.template` (SPA fallback, proxy `/api/` y `/health`, timeouts de 300 s, `client_max_body_size`, `/healthz`, usuario sin privilegios); verificar con `docker build` y `docker run` que `/healthz` y una ruta profunda responden 200.
- [x] 5.2 Añadir el servicio `estimator-web-react` a `docker-compose.yml` (3001:8080, `API_UPSTREAM`, `depends_on` con `service_healthy`, healthcheck, sin claves de proveedores) y actualizar su cabecera; verificar con `docker compose config` y que `docker compose up --build` deja el servicio en `healthy`.
- [x] 5.3 Escribir `estimator-web-react/README.md` (funcionalidad, equivalencias con Rails, variables, ejecución y pruebas) y actualizar el README raíz y el de `openspec/`; verificar que los comandos documentados se ejecutan tal cual.
- [x] 5.4 Verificación de integración: con el stack completo, estimar una transcripción de 80 000 caracteres desde `http://localhost:3001`, abrir el historial y el detalle, y comprobar que `openspec validate estimador-web-react --strict` pasa; registrar la evidencia en `verification.md`.
