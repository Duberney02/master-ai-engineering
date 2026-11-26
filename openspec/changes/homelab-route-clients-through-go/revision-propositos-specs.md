# Revisión de propósitos obsoletos de las especificaciones

Preparada para el paso de integración de deltas (archivado), que **no se ejecuta aquí**. No se ha modificado ninguna
especificación principal: este documento solo registra, por capacidad, qué propósito de `openspec/specs/estimator/*/spec.md`
queda obsoleto tras el cambio y la redacción propuesta para sustituirlo al integrar los deltas. Los requisitos los gobiernan
los once deltas de este cambio; solo cambia el texto de «Purpose».

| Capacidad | Propósito actual (obsoleto) | Redacción propuesta |
|---|---|---|
| `http-streaming` | «…que Streamlit y otros clientes consuman estimaciones progresivas…» | Permitir que Go, único cliente de la API de IA, reciba estimaciones progresivas mediante un contrato HTTP común y las intermedie hacia React sin sintetizar eventos ni reintentar. |
| `web-client` | «Ofrecer una aplicación web Rails (`estimator-web`)…» | Definir la frontera del cliente web: React, servido por Nginx, es el único cliente activo y habla solo con Go; el cliente Rails, el HTML de Go y Streamlit están retirados. |
| `web-backend-go` | «…servicio web en Go que sustituye al cliente Rails: debe ser funcionalmente equivalente…» | Definir el backend HTTP de aplicación en Go: API REST y SSE pública con rutas explícitas, frontera de autorización denegada por defecto, historial del Chunking Lab y desarrollo, pruebas y ejecución únicamente con Docker. No sirve HTML. |
| `prompt-preview` | «…para que clientes sin las plantillas (la web Rails) muestren el contexto del prompt como el cliente Streamlit.» | Exponer el prompt de sistema renderizado y sus ejemplos few-shot, a través de Go, para que React muestre el contexto informativo del prompt sin memoria de sesión. |
| `web-client-contexts` | «Organizar el cliente Rails por contextos…» | Organizar el backend Go por contextos independientes con una capa HTTP única, errores tipados y saneados y navegación por contexto en React. |
| `web-react-client` | «…con paridad funcional con la web Rails…» | Ofrecer el cliente web único (React), con la paridad funcional ya alcanzada, que consume solo la API pública de Go del mismo origen. |
| `structured-estimation` | «…contrato tipado y compartido entre clientes y servicio IA…» | Ofrecer un contrato tipado entre Go y el servicio IA para pedir estimaciones a partir de una descripción breve (el requisito exclusivo del cliente Streamlit se retira en el delta). |
| `deployment-stack` | «Arrancar el sistema completo con un único comando desde la raíz del repositorio.» | Sigue siendo válido; ampliar con la pila segmentada de integración y la publicación exclusiva de React en `127.0.0.1:3001`. |
| `web-ai-settings`, `web-chunking-lab` | «…desde la web…» | Siguen siendo válidos; precisar que se sirven mediante la API administrativa de Go, denegada por defecto en la composición normal. |

## Requisito obsoleto resuelto en el delta

En `web-backend-go`, «Seguridad de sesión, origen y administración» conservaba, hasta la retirada del HTML, la cookie firmada, los
avisos flash, la compactación de metadatos, el CSRF de formulario y «una cookie con firma inválida SHALL tratarse como sesión
vacía». Retirado el HTML, el delta establece que Go no emite cookies, que expira la cookie legada `_estimator_web_session` si el
navegador la envía, sin interpretarla, y que las mutaciones se protegen con la validación de origen (nuevo escenario «Cookie
legada», con prueba `TestLegacySessionCookieIsNeverIssuedAndIsExpiredWhenSent`). No cambia ningún otro requisito.

## Vigilar al integrar

- Los deltas `MODIFIED` de `web-client` y `structured-estimation` sustituyen requisitos que mencionan el cliente retirado: al
  archivar, comprobar que el texto final no conserva referencias activas a Streamlit ni a Rails.
- El historial de OpenSpec y los cambios archivados se conservan sin editar.
