# estimator/deployment-stack Specification

## Purpose
Arrancar el sistema completo con un único comando desde la raíz del repositorio.

## Requirements

### Requirement: Compose raíz con todos los servicios
El repositorio SHALL incluir un `docker-compose.yml` en su raíz que defina los servicios API (`estimador-cag`), chat Streamlit (`estimador-cag-chat`), aplicación web Rails (`estimator-web`), aplicación web React (`estimator-web-react`), Redis Stack (`redis`) y PostgreSQL (`postgres`) en una red compartida. La API SHALL recibir `REDIS_URL` y `DATABASE_URL` apuntando a los servicios internos y la web Rails SHALL recibir `ESTIMATOR_API_URL` apuntando a la API. La web React SHALL recibir la dirección interna de la API para su proxy inverso. Solo la API (8000), el chat (8501), la web Rails (3000) y la web React (3001) SHALL publicar puertos; el chat SHALL recibir `ESTIMATOR_API_BASE_URL` y ninguna clave de proveedor.

#### Scenario: Configuración válida
- **WHEN** se ejecuta `docker compose config` en la raíz con `estimador-cag/.env` presente
- **THEN** la configuración es válida y contiene los seis servicios y la red compartida.

#### Scenario: Arranque completo
- **WHEN** se ejecuta `docker compose up --build`
- **THEN** los servicios llegan a `healthy`, el chat responde en el puerto 8501 y las webs Rails (3000) y React (3001) pueden consultar el historial de la API.

#### Scenario: Web React tras el proxy
- **WHEN** se abre `http://localhost:3001/estimations`
- **THEN** la aplicación se sirve desde su propio origen y sus llamadas a `/api/v1/...` llegan a la API sin exponer la dirección interna ni requerir CORS.

### Requirement: Volúmenes y healthchecks
PostgreSQL y Redis SHALL usar volúmenes con nombre para conservar sus datos. Cada servicio SHALL declarar un healthcheck (`pg_isready`, `redis-cli ping`, `/health` de la API, `/_stcore/health` del chat, `/up` de la web Rails y `/healthz` de la web React) y los servicios dependientes SHALL esperar con `depends_on` y `condition: service_healthy`.

#### Scenario: Orden de arranque
- **WHEN** arranca el stack
- **THEN** la API espera a PostgreSQL y Redis saludables, y las webs y el chat esperan a la API saludable.

#### Scenario: Persistencia entre reinicios
- **WHEN** se reinicia el stack sin eliminar volúmenes
- **THEN** el historial de estimaciones sigue disponible.

### Requirement: Secretos fuera del repositorio
Las claves de proveedores SHALL leerse de `estimador-cag/.env` (ignorado por git) y SHALL NOT incluirse en las webs ni en el chat. La contraseña de PostgreSQL SHALL parametrizarse con `POSTGRES_PASSWORD`.

#### Scenario: La web y el chat no reciben claves
- **WHEN** se inspecciona el entorno de los servicios `estimator-web` y `estimador-cag-chat`
- **THEN** ninguno contiene `OPENAI_API_KEY` ni `ANTHROPIC_API_KEY`.

#### Scenario: La web React no recibe claves
- **WHEN** se inspecciona el entorno del servicio `estimator-web-react`
- **THEN** no contiene `OPENAI_API_KEY` ni `ANTHROPIC_API_KEY`.
