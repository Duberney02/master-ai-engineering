# Spec Delta

## Purpose

Arrancar el sistema completo con un único comando desde la raíz del repositorio.

## ADDED Requirements

### Requirement: Compose raíz con todos los servicios
El repositorio SHALL incluir un `docker-compose.yml` en su raíz que defina los servicios API (`estimador-cag`), chat Streamlit (`estimador-cag-chat`), aplicación web (`estimator-web`), Redis Stack (`redis`) y PostgreSQL (`postgres`) en una red compartida. La API SHALL recibir `REDIS_URL` y `DATABASE_URL` apuntando a los servicios internos y la web SHALL recibir `ESTIMATOR_API_URL` apuntando a la API. Solo la API (8000), el chat (8501) y la web (3000) SHALL publicar puertos; el chat SHALL recibir `ESTIMATOR_API_BASE_URL` y ninguna clave de proveedor.

#### Scenario: Configuración válida
- **WHEN** se ejecuta `docker compose config` en la raíz con `estimador-cag/.env` presente
- **THEN** la configuración es válida y contiene los cinco servicios y la red compartida.

#### Scenario: Arranque completo
- **WHEN** se ejecuta `docker compose up --build`
- **THEN** los servicios llegan a `healthy`, el chat responde en el puerto 8501 y la web puede consultar el historial de la API.

### Requirement: Volúmenes y healthchecks
PostgreSQL y Redis SHALL usar volúmenes con nombre para conservar sus datos. Cada servicio SHALL declarar un healthcheck (`pg_isready`, `redis-cli ping`, `/health` de la API, `/_stcore/health` del chat y `/up` de la web) y los servicios dependientes SHALL esperar con `depends_on` y `condition: service_healthy`.

#### Scenario: Orden de arranque
- **WHEN** arranca el stack
- **THEN** la API espera a PostgreSQL y Redis saludables, y la web y el chat esperan a la API saludable.

#### Scenario: Persistencia entre reinicios
- **WHEN** se reinicia el stack sin eliminar volúmenes
- **THEN** el historial de estimaciones sigue disponible.

### Requirement: Secretos fuera del repositorio
Las claves de proveedores SHALL leerse de `estimador-cag/.env` (ignorado por git) y SHALL NOT incluirse en la web ni en el chat. La contraseña de PostgreSQL SHALL parametrizarse con `POSTGRES_PASSWORD`.

#### Scenario: La web y el chat no reciben claves
- **WHEN** se inspecciona el entorno de los servicios `estimator-web` y `estimador-cag-chat`
- **THEN** ninguno contiene `OPENAI_API_KEY` ni `ANTHROPIC_API_KEY`.
