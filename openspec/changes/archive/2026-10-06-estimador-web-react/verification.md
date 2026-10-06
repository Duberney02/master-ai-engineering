# Verificación: estimador-web-react

Fecha: 2026-10-06. Entorno: Windows 11, Node 24.14.1, Docker 29.3.1, API real con `gpt-4o-mini`.

## Resultados automáticos

| Comprobación | Resultado |
|---|---|
| `npm ci && npm run build` (tsc estricto + vite) | correcto |
| `npm test` (Vitest) | 6 archivos, 84 pruebas, todas pasan |
| `openspec validate estimador-web-react --strict` | válido |
| `docker build` de `estimator-web-react` | correcto |
| `docker compose config` | válido; 6 servicios; publican puertos solo API (8000), chat (8501), Rails (3000) y React (3001) |
| Entorno de `estimator-web-react`, `estimator-web` y `estimador-cag-chat` | sin ninguna variable `*_API_KEY` |

## Cobertura por requisito (`estimator/web-react-client`)

| Requisito | Evidencia |
|---|---|
| Rutas equivalentes | `components.test.tsx` (navegación), `pages.test.tsx` (404 y navegación historial → formulario) |
| Formulario con `.txt` | `estimationForm.test.ts` (mensajes, límites, UTF-8, BOM), `pages.test.tsx` (válida, archivo válido, tres archivos inválidos, fuera de rango, temporizador, conservación de datos tras error) |
| Visualización del resultado | `components.test.tsx` (estimable, `out_of_scope`, descripción truncada a 2 000), `format.test.ts` |
| Flujo tras estimar | `pages.test.tsx` (con y sin `estimation_id`) |
| Barra lateral | `components.test.tsx` (prompt, métricas, vacío, no disponible, ocultar), `pages.test.tsx` y `hooks.test.tsx` (cambio de opciones y descarte de respuestas obsoletas) |
| Historial | `pages.test.tsx` (listado, extracto de 90, vacío, 503, id inválido sin llamada) |
| Errores del cliente HTTP | `estimatorApi.test.ts` (200, 400 acotado a 300, 404, 422, 503, 5xx, red caída, tiempo agotado, cuerpo no JSON, sin `result`); ningún mensaje contiene cuerpos ni URLs |
| Presentación accesible | `role="alert"`, `role="status"`/`aria-live`, `lang="es"` y `aria-expanded` comprobados en pruebas; CSS de Rails portado |

## Comprobación manual con el stack real

- `docker compose up -d --build estimator-web-react` levanta API, Redis, PostgreSQL y la web React; los cuatro llegan a `healthy` y la API espera a Redis y PostgreSQL.
- `http://localhost:3001/health` y `/api/v1/estimations` responden a través del proxy nginx (sin CORS).
- Imagen aislada: `/healthz` 200, ruta profunda `/estimations/7` sirve `index.html`, proxy de `/api/` y `/health`, `POST` de 330 KB aceptado (límite de 1 MB), proceso con uid 101.
- Desde el navegador: transcripción de 80 000 caracteres → botón deshabilitado, indicador y temporizador activos, redirección a `/estimations/1`, resultado «No estimable» (confianza 20 %, el texto de prueba es repetitivo) con modelo `gpt-4o-mini-2024-07-18` en la barra. El historial lista la estimación con enlace al detalle.
- Ancho de 600 px: una columna y, tras añadir `.table-scroll`, sin scroll horizontal de página (la tabla del historial lo provocaba, igual que en el CSS de Rails).

## Límites de esta verificación

- La comprobación visual (tarea 1.3) se hizo en modo oscuro y en ancho estrecho; el modo claro no se revisó en pantalla (usa los mismos tokens de color que Rails).
- El arranque completo incluyó solo la API, sus dependencias y la web React; no se levantaron `estimator-web` ni el chat.
- La API devolvió «No estimable» para la transcripción de prueba, así que la tabla de fases con cifras se verificó con pruebas automáticas y no con una estimación real.
- Las pruebas Rails y Python no se ejecutaron: sus fuentes no cambian en este cambio.
