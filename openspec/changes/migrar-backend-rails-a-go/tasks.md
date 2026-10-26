# Tasks

## 1. Andamiaje Go y Docker

- [ ] 1.1 Crear `estimator-web-go/` con `go.mod`, `cmd/server/main.go` mínimo (`/up`), `Dockerfile` multietapa (test/build/runtime) y servicios `web-db`, `web-test`, `web-lint` en `docker-compose.verify.yml`; verificar que `docker compose -f docker-compose.verify.yml run --rm web-test` compila y pasa y que `web-lint` queda limpio.
- [ ] 1.2 Implementar `internal/config` (variables y defectos de Rails) con pruebas unitarias; verificar con `web-test`.

## 2. Capa HTTP hacia la API de IA (`internal/estimatorai`)

- [ ] 2.1 Implementar errores tipados y `BaseClient` (mapeo de estados, `detail`, guardrail, timeouts, multipart/JSON) con pruebas contra `httptest` portadas de `base_client_test.rb`; verificar con `web-test`.
- [ ] 2.2 Implementar clientes de estimaciones, sesiones (multipart con adjuntos), embeddings y configuración, y el corpus embebido; verificar con las pruebas portadas de los cuatro `*_client_test.rb`.

## 3. Contextos y dominio

- [ ] 3.1 Implementar `internal/rag` (catálogo de estrategias, contratos, `ComparisonResponse`) y `internal/ai` (`ModelConfig`, `Catalog`) con pruebas portadas de `contracts_test.rb`, `catalog_test.rb`.
- [ ] 3.2 Implementar el repositorio PostgreSQL de `chunking_comparisons` (migración idempotente, insertar, listar 20, buscar) con pruebas de persistencia contra PostgreSQL real; verificar con `web-test`.
- [ ] 3.3 Implementar `internal/estimation` (validación del formulario, `.txt`, adjuntos) con pruebas portadas de `estimation_form*_test.rb`.
- [ ] 3.4 Implementar `internal/session` (cookie firmada, flash, CSRF, compactado de metadatos) con pruebas (firma manipulada, tamaño, flash de un solo uso, CSRF).

## 4. Transporte HTTP y vistas

- [ ] 4.1 Implementar helpers de formato (`number_with_precision`, delimitadores, `truncate`, `format_time`, etiquetas) y el motor de plantillas con layout, barra de navegación e indicador del modelo primario (caché 15 s) con pruebas portadas de `ai_settings_helper_test.rb` y `navigation_helper_test.rb`.
- [ ] 4.2 Portar inicio, `/up`, errores 404/422/500 y la sección de estimaciones (formulario, resultado, historial, barra lateral, conversación) con pruebas de endpoints portadas de `home_controller_test.rb`, `estimations_controller_test.rb` y `conversation_test.rb`.
- [ ] 4.3 Portar el Chunking Lab (formulario, ejecución, detalle, historial) con pruebas portadas de `chunking_comparisons_controller_test.rb`, incluido el fallo de BD.
- [ ] 4.4 Portar Ajustes con pruebas portadas de `ai_settings_controller_test.rb`; añadir pruebas de CSRF y de `_method` para todos los formularios.
- [ ] 4.5 Prueba de dependencias de paquetes (solo `estimatorai` importa `net/http` para hablar con la API; `rag` y `ai` no se importan) y prueba de integración de extremo a extremo con la API simulada (navegación completa sin Rails).

## 5. Integración Docker y conmutación

- [ ] 5.1 Sustituir el servicio `estimator-web` del `docker-compose.yml` raíz por el build de `estimator-web-go/` (mismo nombre, puerto, healthcheck y variables); verificar con `docker compose config` y que el servicio llega a `healthy`.
- [ ] 5.2 Actualizar `.env.example`, el workflow de CI (`go test`, `gofmt`, `go vet`, humo con `curl`), `README.md` y `CLAUDE.md`; verificar `openspec validate --all --strict`.

## 6. Validación y sustitución

- [ ] 6.1 Levantar el stack completo y recorrer los flujos principales (inicio, formulario, historial, Lab con estrategias gratuitas y persistencia, Ajustes con cambio de modelo y reinicio) contra la API Python real; registrar resultados.
- [ ] 6.2 Comparar HTML de Go y Rails (misma API y misma BD) para las pantallas sin LLM y documentar las diferencias en `verification.md`.
- [ ] 6.3 Ejecutar `api-test`, `api-lint`, `web-test`, `web-lint` y la validación de OpenSpec; verificar que todo está en verde y que el stack funciona sin Rails.
- [ ] 6.4 Retirar el código y la configuración de ejecución de Rails (`estimator-web/`, referencias residuales) en un commit aparte; verificar con `grep` que no quedan referencias de ejecución y que el stack sigue arrancando.
- [ ] 6.5 Documentar el servicio (`estimator-web-go/README.md` y `ARCHITECTURE.md`: compilar, ejecutar, probar y desarrollar con Docker) y el resumen técnico final con tareas completadas, pendientes y limitaciones.
