# Proposal

## Why

El servicio ya ofrece comparación de estrategias de chunking (`/embeddings/compare`) y modelos configurables en runtime (`/api/v1/config/models`), pero el cliente Rails no los expone, y su único servicio HTTP (`EstimatorApi`) mezcla estimaciones, sesiones y manejo de errores en un monolito. La referencia (`ai-engineering`, `session_07_live`) reorganiza el cliente por contextos con una capa HTTP única y añade el Chunking Lab y la pantalla de Ajustes. Sin esto, comparar chunkers o cambiar de modelo exige `curl`.

## What Changes

- **Capa HTTP única por contextos** (`app/services/estimator_ai/`): `BaseClient` con la taxonomía de errores tipados y saneados, y un cliente por contexto (`EstimationsClient`, `SessionsClient`, `EmbeddingsClient`, `ConfigClient`). Los controllers pasan a usarlos y se elimina el monolito `EstimatorApi`.
- **Contratos por contexto** (`app/models/rag/`, `app/models/ai/`) que reflejan los schemas del servicio.
- **Navegación por contexto**: panel de inicio (`/`) con una tarjeta por contexto y barra con la sección activa y el modelo primario vigente (tolerante a fallos, se refresca al guardar). El formulario de estimación pasa a `/estimations/new`.
- **Chunking Lab** (`/rag/chunking_comparisons`): formulario (estrategias con aviso de coste y de clave, las de pago opt-in; consultas predefinidas y propias; `top_k`), resultados (tabla de estadísticas, barras de coste, playground de recuperación con scores y padre/hijo), **historial persistido** y **tiempo de espera ampliado solo para esa llamada**.
- **Persistencia**: PostgreSQL propio del cliente (`estimator-web-db` en Compose, `DATABASE_URL`) para el historial del Lab; imagen con entrypoint que prepara la base de datos.
- **Ajustes** (`/ai_settings`): ver y cambiar los siete modelos del servicio en runtime (un select vacío restablece).
- **Entorno de pruebas en Docker**: servicios `web-db`, `web-test` y `web-lint` en `docker-compose.verify.yml` y etapa `test` en el `Dockerfile`; RuboCop omakase; CI con PostgreSQL.
- `ARCHITECTURE.md` del cliente con las cuatro reglas y la tabla «¿dónde va mi código nuevo?».

**No incluido**: paridad en `estimator-web-react` o Streamlit; trabajos en segundo plano para el Lab (síncrono a propósito); autenticación; migrar `EstimationForm` y la sesión de conversación a contratos por contexto.

## Capabilities

### New Capabilities
- `estimator/web-client-contexts`: capa HTTP única, errores tipados, contratos, navegación e inicio.
- `estimator/web-chunking-lab`: formulario, resultados, historial persistido y tiempo de espera del laboratorio.
- `estimator/web-ai-settings`: pantalla de modelos en runtime e indicador del modelo primario.

### Modified Capabilities
- Ninguna: los requisitos de `estimator/web-client` (formulario, resultado, barra lateral) se conservan; solo cambia la ruta del formulario (`/estimations/new`).

## Impact

- Código: `estimator-web/` casi entero (servicios, modelos, controllers, vistas, helpers, rutas, `Gemfile`/`Gemfile.lock` con `pg` y RuboCop, `Dockerfile`, `config/`), `docker-compose.yml` (servicio `estimator-web-db`, volumen), `docker-compose.verify.yml`, `.github/workflows/estimador-cag-ci.yml`.
- Las rutas y JSON del servicio no cambian. En el cliente, la raíz `/` deja de ser el formulario.
- Las pruebas usan WebMock y una base de datos efímera; nunca llaman a la API real. Se comprobó además la imagen de producción contra PostgreSQL y el stack completo de Compose.
