# Proposal

## Why

El servicio web del estimador (`estimator-web`) está construido en Ruby on Rails, mientras que el resto del stack
operativo (API de IA en Python, SPA React con nginx) no comparte con él lenguaje, toolchain ni imagen. Se decide
reemplazarlo por un servicio en Go: un único binario estático sin intérprete ni gemas nativas, imagen mínima, arranque
inmediato y un coste de mantenimiento menor para lo que en realidad es una capa fina de transporte sobre la API de IA.
Es una migración **tecnológica**: el producto no cambia.

## What Changes

- Nuevo servicio `estimator-web-go/` en Go que reimplementa, con el mismo comportamiento observable, todo lo que hoy
  hace el backend Rails: las mismas rutas, métodos, formularios, HTML, estados HTTP, mensajes en español, sesión de
  conversación por cookie, protección CSRF, historial del Chunking Lab en PostgreSQL y el indicador del modelo primario.
- La capa HTTP hacia la API de IA (`/api/v1/*`, `/embeddings/compare`) se reimplementa con los mismos contratos,
  tiempos de espera y errores saneados. El servicio de IA en Python **no cambia**.
- El servicio `estimator-web` del `docker-compose.yml` raíz pasa a construirse desde `estimator-web-go/`; conserva
  nombre, puerto 3000, `/up` y variables de entorno, de modo que los navegadores y el resto del stack siguen
  apuntando al mismo sitio. No quedan servicios Rails en el Compose.
- `web-test` y `web-lint` del `docker-compose.verify.yml` ejecutan las pruebas (`go test`) y el lint (`gofmt` + `go vet`)
  del nuevo servicio con PostgreSQL efímero; se actualiza el CI.
- Una vez validada la equivalencia, se retira el código y la configuración de ejecución de Rails (`estimator-web/`).
- **BREAKING (solo operativo)**: la cookie de sesión de Rails deja de ser válida; las conversaciones abiertas se
  reinician una vez al desplegar. Las rutas, los HTML y la base de datos no cambian.

Fuera de alcance: nuevas funcionalidades, cambios en la API Python, en la SPA React o en el chat Streamlit.

## Capabilities

### New Capabilities
- `estimator/web-backend-go`: el servicio web en Go como único backend de cliente: equivalencia funcional con el servicio Rails,
  contrato de rutas, sesión y CSRF, límites de la frontera con la API de IA y operación en Docker.

### Modified Capabilities
- `estimator/deployment-stack`: el servicio `estimator-web` del Compose raíz es el servicio Go (mismo nombre, puerto y `/up`).
- `estimator/web-client-contexts`: la capa HTTP única, los errores tipados y el entorno de pruebas se expresan para el servicio Go.
- `estimator/web-client`: el manejo de errores del cliente HTTP deja de nombrar a Faraday.

## Impact

- **Código nuevo**: `estimator-web-go/` (cmd, internal, plantillas, Dockerfile, documentación).
- **Configuración**: `docker-compose.yml`, `docker-compose.verify.yml`, `.env.example`, `.github/workflows/estimador-cag-ci.yml`,
  `CLAUDE.md`, `README.md`.
- **Retirado al final**: `estimator-web/` (Rails). Se conserva en el historial de git.
- **Clientes**: los navegadores son el único consumidor de este servicio; la SPA React (`:3001`) y el chat Streamlit
  (`:8501`) hablan directamente con la API de IA y no dependen de Rails (ver `design.md`). Sin cambios en ellos.
- **Datos**: la tabla `chunking_comparisons` no cambia; el servicio Go la reutiliza (`CREATE TABLE IF NOT EXISTS`).
