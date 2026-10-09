# estimator/development-tooling Specification

## Purpose
Verificar el proyecto con herramientas de desarrollo reproducibles que se ejecutan solo en contenedores.

## Requirements

### Requirement: Ruff como linter del proyecto
El proyecto SHALL incluir Ruff en las dependencias de desarrollo (no en las de producción) con su configuración en `pyproject.toml`, y el código de `app/`, `evals/` y `tests/` SHALL pasar la comprobación sin avisos.

#### Scenario: Lint limpio
- **WHEN** se ejecuta `ruff check .` en el contenedor de desarrollo
- **THEN** el resultado es «All checks passed!».

#### Scenario: Imagen de producción
- **WHEN** se construye la imagen de producción
- **THEN** no contiene Ruff ni FakeRedis.

### Requirement: Servicios Docker de verificación
El repositorio SHALL ofrecer servicios Docker Compose para ejecutar las pruebas, el lint, el runner de evaluación, `uv` y el CLI de OpenSpec, reutilizando la etapa `test` del Dockerfile existente, de modo que no sea necesario instalar Python, Node ni el CLI de OpenSpec en el host.

#### Scenario: Pruebas
- **WHEN** se ejecuta `docker compose -f docker-compose.verify.yml run --rm api-test`
- **THEN** se ejecuta la suite completa dentro del contenedor.

#### Scenario: Validación de OpenSpec
- **WHEN** se ejecuta `docker compose -f docker-compose.verify.yml run --rm openspec validate --all --strict`
- **THEN** se validan todas las especificaciones con la versión fijada del CLI.
