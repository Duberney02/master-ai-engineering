## Why

Hoy los clientes se saltan la capa de negocio: `estimator-web-react` (nginx `proxy_pass` de `/api/`) y Streamlit hablan
directamente con `estimador-cag`, y Streamlit vive dentro del servicio de IA (código, dependencia `streamlit`,
`COPY streamlit_app.py` en su `Dockerfile`, imports de `app.domain.schemas` y `app.foundation.prompts`). Además
`estimator-web-go` mezcla dos responsabilidades: un cliente web HTML (plantillas, cookie de sesión, CSRF) y el único
cliente de la API de IA. El diagnóstico de la Sesión 09 (`arquitectura-actual.md`) propone tres capas estrictas:
**frontends → backend de negocio → servicio IA**. Este cambio las implanta.

## What Changes

- `estimator-web-go` pasa a ser un **API JSON (BFF)** bajo el prefijo `/api/...` más `GET /up`: encapsula y reexpone las
  operaciones de estimación, conversación, historial, contexto del prompt, Chunking Lab (con su historial en PostgreSQL)
  y ajustes de modelos, llamando a `estimador-cag` solo mediante `internal/estimatorai`.
- `estimator-web-react` migra lo que le falta respecto a la web Go (Chunking Lab, ajustes de IA, indicador del modelo
  primario y navegación a esas pantallas), y todas sus llamadas pasan a `/api/...` del backend Go. El `proxy_pass` de
  nginx (`API_UPSTREAM`) y el Compose apuntan a `estimator-web`.
- Se elimina de `estimator-web-go` la parte web: `internal/web/templates`, `internal/web/public`, `html/template`,
  `embed` de assets, formato HTML, cookie de sesión firmada, flash y CSRF.
- Streamlit se extrae a una carpeta nueva `estimator-streamlit/` (Dockerfile, `pyproject.toml`/`uv.lock`, README,
  `.dockerignore`, tests) que no importa nada de `estimador-cag` y solo habla HTTP con `estimator-web-go`
  (`ESTIMATOR_WEB_URL`). `estimador-cag` pierde `streamlit`, `streamlit_app.py`, `app/streamlit_client.py`,
  `app/streamlit_support.py` y sus tests.
- Compose: `estimador-cag-chat` se construye desde `estimator-streamlit/`, depende de `estimator-web` (healthy) y no de
  `estimador-cag`; `estimator-web-react` también depende de `estimator-web`. `docker-compose.verify.yml` añade los
  servicios de test/lint de Streamlit y de React.
- Documentación (`CLAUDE.md`, READMEs, `ARCHITECTURE.md`) actualizada.

### BREAKING

- Se eliminan las rutas HTML del backend Go (`/`, `/estimations/new`, `/estimations`, `/estimations/{id}`,
  `/conversation`, `/rag/chunking_comparisons...`, `/ai_settings`, `/robots.txt`, `/404.html`, `/422.html`,
  `/500.html`). Las pantallas viven ahora solo en React (puerto 3001) y Streamlit (8501); el puerto 3000 sirve JSON.
- El chat Streamlit deja de vivir en `estimador-cag`: la imagen `estimador-cag:latest` ya no lo sirve ni lo incluye.
- React y Streamlit dejan de llamar a `/api/v1/...` de `estimador-cag`; sus variables (`API_UPSTREAM`,
  `ESTIMATOR_API_BASE_URL`) se sustituyen por la URL del backend Go. `ESTIMATOR_API_BASE_URL` desaparece.
- El contrato HTTP de `estimador-cag` **no cambia** (los endpoints nuevos viven en el backend Go).

## Capabilities

### New Capabilities

- `estimator/streamlit-client`: cliente Streamlit independiente que solo consume el backend Go.

### Modified Capabilities

- `estimator/web-backend-go`: de cliente HTML a API JSON sin sesión de navegador.
- `estimator/web-react-client`: nuevas pantallas (Chunking Lab, Ajustes), consumo del backend Go.
- `estimator/web-chunking-lab`: contrato JSON en lugar de pantallas HTML; el cliente es React.
- `estimator/web-ai-settings`: ídem; indicador del modelo primario en React.
- `estimator/web-client`: se retiran sus requisitos (cliente Rails obsoleto, sustituido por Go y luego React).
- `estimator/deployment-stack`: nuevo reparto de servicios, dependencias y variables.
- `estimator/layered-architecture`: Streamlit deja de estar «fuera de las capas».
- `estimator/development-tooling`: servicios de verificación para Streamlit y React.

## Impact

- Código: `estimator-web-go` (API JSON, borrado de plantillas/assets/sesión), `estimator-web-react` (pantallas, cliente
  HTTP, nginx), `estimator-streamlit/` (nuevo), `estimador-cag` (limpieza de Streamlit, `uv.lock`, `Dockerfile`).
- Operación: `docker-compose.yml`, `docker-compose.verify.yml`, puertos sin cambios (8000, 3000, 3001, 8501).
- Riesgos: paridad de validaciones y mensajes al trasladar el cliente Streamlit (que hoy valida con Pydantic) al
  contrato JSON del backend; transcripciones y adjuntos grandes a través de dos saltos (límites de cuerpo en nginx y Go).
- Sin cambios en el contrato de `estimador-cag` ni en la base de datos del Chunking Lab.
