# Verification

Todo se ejecutó en Docker desde la raíz del repositorio, rama `session_07/refined`.

| Comando | Resultado |
|---|---|
| `docker compose -f docker-compose.verify.yml build web-test` | Imagen de pruebas con `pg` y RuboCop (lock regenerado en contenedor con `bundle lock`) |
| `docker compose -f docker-compose.verify.yml run --rm web-test` (línea base, antes de tocar el código) | 97 runs, 490 assertions, 0 failures |
| `docker compose -f docker-compose.verify.yml run --rm web-test` (tras el cambio) | **178 runs, 847 assertions, 0 failures, 0 errors** (+81 pruebas) |
| `docker compose -f docker-compose.verify.yml run --rm web-lint` | 69 files inspected, no offenses detected |
| `docker compose -f docker-compose.verify.yml run --rm openspec validate cliente-rails-por-contextos --strict` | Change is valid |
| `docker compose build estimator-web` + contenedor con PostgreSQL real | El entrypoint ejecuta `db:prepare`; `/up`, `/`, `/rag/chunking_comparisons`, `/rag/chunking_comparisons/new` y `/estimations/new` responden 200 con la API inexistente (barra sin indicador); `/ai_settings` responde 503 saneado |
| `docker compose up -d --build --wait` (stack completo) | Los 7 servicios healthy, incluido `estimator-web-db` |
| Stack completo: `PUT /api/v1/config/models` y la pantalla `/ai_settings` | Override del crítico visible en Rails, `422` ante un modelo fuera del catálogo y restablecimiento con `null`; la barra muestra `gpt-4o-mini` |
| Stack completo: Chunking Lab (POST con token CSRF, estrategias gratuitas, sin consultas) | `302` al resultado; tabla con `structural` 61 chunks (máx. 821, 1 obeso) y `recursive` 20 chunks, iguales a la CLI del servicio; historial con 2 ejecuciones guardadas en PostgreSQL |

El stack se detuvo con `docker compose down` y se eliminó solo el volumen `estimator_estimator_web_db_data` creado por esta verificación.

## Hallazgo de la verificación

La prueba de la imagen de producción detectó que `config.cache_store = :memory_store, { size: 4.megabytes }` fallaba al cargar el entorno (`production.rb` no carga las extensiones de `Numeric`); ninguna prueba lo cubre porque corren en `RAILS_ENV=test`. Corregido a `4 * 1024 * 1024`.

## Contraste con la spec

- **Capa HTTP y errores**: `test/services/estimator_ai/` (clientes de estimaciones, sesiones, embeddings y configuración, y `base_client_test` con la taxonomía, el saneado de cuerpos y URL, los `detail` y la ausencia de `EstimatorApi`). Las dos suites de `EstimatorApi` se movieron a los clientes cambiando solo nombres.
- **Contratos**: `test/models/rag` y `test/models/ai` (catálogo de estrategias, estadísticas, top-k con padre/hijo, costes, atributos desconocidos ignorados, filtrado de modelos por proveedor, persistencia JSONB).
- **Navegación**: `home_controller_test` (tarjetas, sección activa en las cinco pantallas, barra sin servicio, indicador) y `navigation_helper_test`.
- **Lab**: formulario (solo gratuitas marcadas, avisos de pago y de clave), envío con corpus/estrategias/consultas/`top_k`, tiempo de espera propio, 422/503/504/502 sin filtrar URL ni cuerpos, resultado guardado aunque falle la base de datos, resultados (estadísticas, barras de coste, playground y marca de padre/hijo), historial ordenado y degradado.
- **Ajustes**: lectura con override, selector vacío como reset, chunkers por proveedor, guardado parcial con `null`, knobs desconocidos ignorados, rechazos 400/422 con el detalle, 503 y refresco del indicador (`ai_settings_helper_test` cubre la caché y el fallo cacheado).

## Limitaciones declaradas

- El formulario del Lab usa JavaScript en línea (aviso de pago e indicador de carga); Minitest no lo ejecuta. Se comprueba que los elementos y los `data-paid` existen, no el comportamiento en un navegador.
- No se ejecutaron estrategias de pago ni consultas con embeddings contra proveedores reales (coste y claves del usuario); el flujo completo con estrategias gratuitas sí se verificó de extremo a extremo.
- La ruta del formulario de estimación cambió de `/` a `/estimations/new`; los tests que usaban `root_path` se actualizaron.
