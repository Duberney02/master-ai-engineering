# Tasks

Todo se ejecuta en Docker desde la raíz: `docker compose -f docker-compose.verify.yml run --rm web-test` / `web-lint`.

## 1. Infraestructura

- [x] 1.1 `pg` y RuboCop omakase en el `Gemfile` (lock regenerado en contenedor), `config/database.yml`, `ApplicationRecord` y migración `chunking_comparisons`.
- [x] 1.2 `Dockerfile` con etapa `test`, `libpq` y entrypoint que prepara la base de datos; servicio `estimator-web-db` y volumen en Compose; `web-db`, `web-test` y `web-lint` en `docker-compose.verify.yml`; CI con PostgreSQL y RuboCop.
- [x] 1.3 Línea base: las 97 pruebas existentes en verde en el contenedor.

## 2. Capa HTTP por contextos

- [x] 2.1 `BaseClient` y la taxonomía de errores (un archivo por clase).
- [x] 2.2 `EstimationsClient`, `SessionsClient`, `EmbeddingsClient`, `ConfigClient` y `BudgetCorpus`; migrar controllers y suites de pruebas; eliminar `EstimatorApi`.

## 3. Contratos y persistencia

- [x] 3.1 Contratos `Rag::*` y `Ai::*`; `Rag::ChunkingComparison` (ActiveRecord).

## 4. Pantallas

- [x] 4.1 Panel de inicio, barra con sección activa e indicador del modelo primario; formulario de estimación en `/estimations/new`.
- [x] 4.2 Chunking Lab: formulario, ejecución con tiempo de espera propio, resultados (estadísticas, costes, playground) e historial.
- [x] 4.3 Ajustes: lectura, guardado parcial, reset y refresco del indicador.

## 5. Pruebas, documentación y verificación

- [x] 5.1 Pruebas de clientes, errores, contratos, helpers y controllers (incluido el mapeo de errores y el layout sin servicio).
- [x] 5.2 `ARCHITECTURE.md` y README del cliente y del repositorio.
- [x] 5.3 Comprobación de la imagen de producción con PostgreSQL y del stack completo de Compose.
- [x] 5.4 `verification.md`, `openspec validate --strict`, sincronizar specs y archivar.
