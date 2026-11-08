## MODIFIED Requirements

### Requirement: Servicios Docker de verificación
El repositorio SHALL ofrecer servicios Docker Compose para ejecutar las pruebas y el lint de cada proyecto (`api-test`, `api-lint`, `web-test`, `web-lint`, `web-react-test`, `web-react-lint`, `streamlit-test`, `streamlit-lint`), el runner de evaluación, `uv` y el CLI de OpenSpec, de modo que no sea necesario instalar Python, Go, Node ni el CLI de OpenSpec en el host. Los servicios de la API reutilizan la etapa `test` del Dockerfile de `estimador-cag`; los de Streamlit y React usan su propio Dockerfile o imagen.

#### Scenario: Pruebas
- **WHEN** se ejecuta `docker compose -f docker-compose.verify.yml run --rm api-test`
- **THEN** se ejecuta la suite completa dentro del contenedor.

#### Scenario: Clientes
- **WHEN** se ejecutan `web-react-test`, `web-react-lint`, `streamlit-test` y `streamlit-lint`
- **THEN** pasan dentro de sus contenedores sin dependencias del host.

#### Scenario: Validación de OpenSpec
- **WHEN** se ejecuta `docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict`
- **THEN** se validan todas las especificaciones con la versión fijada del CLI.
