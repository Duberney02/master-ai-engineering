## MODIFIED Requirements

### Requirement: Compose raíz con todos los servicios
El repositorio SHALL incluir un `docker-compose.yml` en su raíz que defina los servicios API (`estimador-cag`), chat Streamlit (`estimador-cag-chat`, construido desde `estimator-streamlit/`), backend en Go (`estimator-web`), su base de datos (`estimator-web-db`), aplicación web React (`estimator-web-react`), Redis Stack (`redis`) y PostgreSQL (`postgres`) en una red compartida. La API SHALL recibir `REDIS_URL` y `DATABASE_URL` apuntando a los servicios internos. Solo `estimator-web` SHALL recibir `ESTIMATOR_API_URL` apuntando a la API. La web React SHALL recibir `API_UPSTREAM` y el chat `ESTIMATOR_WEB_URL`, ambos apuntando a `estimator-web`, y ambos SHALL depender de `estimator-web` saludable y no de la API. Solo la API (8000), el chat (8501), el backend Go (3000) y la web React (3001) SHALL publicar puertos; ni la web React ni el chat SHALL recibir claves de proveedor ni referencias a la API. El Compose SHALL NOT definir ningún servicio Rails.

#### Scenario: Configuración válida
- **WHEN** se ejecuta `docker compose config` en la raíz con `estimador-cag/.env` presente
- **THEN** la configuración es válida y contiene los siete servicios y la red compartida.

#### Scenario: Arranque completo
- **WHEN** se ejecuta `docker compose up --build`
- **THEN** los servicios llegan a `healthy`, el chat responde en el puerto 8501, la web React en 3001 y el backend Go en 3000.

#### Scenario: Clientes solo contra el backend
- **WHEN** se inspeccionan las variables de `estimator-web-react` y `estimador-cag-chat`
- **THEN** ambas apuntan a `http://estimator-web:3000` y ninguna a `http://estimador-cag:8000`.

#### Scenario: Web React tras el proxy
- **WHEN** se abre `http://localhost:3001/estimations`
- **THEN** la aplicación se sirve desde su propio origen y sus llamadas a `/api/...` llegan al backend Go sin exponer la dirección interna ni requerir CORS.
