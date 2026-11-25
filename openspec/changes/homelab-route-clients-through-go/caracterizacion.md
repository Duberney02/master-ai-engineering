# Referencia del Bloque 1

Base de código `307a8b9`. Los nombres de las pruebas permiten reproducir los recorridos con las mismas respuestas simuladas durante el corte.

## 1.1 Operaciones públicas de estimación

Las rutas de aplicación de esta tabla se sirven hoy en FastAPI. React llega a Python mediante Vite o Nginx. Los consumidores React de la tabla usan `estimator-web-react/src/api/estimatorApi.ts` y los adaptadores Go están en `estimator-web-go/internal/estimatorai/clients.go`. El formulario de ambas interfaces usa E1 y E2. El objetivo es exponer las nueve operaciones a través de Go y preservar los contratos observables.

| Caso | Método y ruta | Consumidor y referencia | Entrada y comprobaciones de referencia |
|---|---|---|---|
| E1 | POST `/api/v1/sessions` | React, HTML Go y Streamlit; `app/api/sessions.py`, `test_sessions_api.py` | Sin cuerpo. 201 JSON con solo `session_id`, UUID v4 distinto por alta. Memoria volátil, caducidad por defecto de 6 h. |
| E2 | POST `/api/v1/sessions/{session_id}/estimate` | React, HTML Go y Streamlit; `sessions.py`, `domain/schemas/sessions.py`, `test_sessions_api.py`, `test_history_conversation.py` | Multipart repetible `attachments` PDF/DOCX (hasta 5 archivos de 10 MiB), o URL-encoded si solo hay texto. El texto combinado admite 20–80 000 caracteres. `project_type` obligatorio, `transcript=""`, `detail_level=medium`, `output_format=phases_table`. `reference_projects` opcional como lista JSON en texto, versión opcional de hasta 10 caracteres (conversación v4 por defecto) y `tier` opcional (`executive`, `pm`, `developer`, `default`; vacío delega en las reglas). 200 con campos de E6 y `session_id`, `project_metadata`, `turn_count`, `max_turns`; `audience` y `audience_rule` anulables en el esquema. 400 guardrail, 404 desconocida/caducada, 413 límites, 415 tipo de archivo, 422 opciones, texto corto o documento ilegible; 502 si se agota la validación de salida. |
| E3 | GET `/api/v1/prompts/estimation` | React y HTML Go; `app/api/prompts.py`, `test_history.py`, `estimations_test.go` | Query `prompt_version=v3` (≤10), `project_type=mobile_app`, `detail_level=medium`, `output_format=phases_table`. 200 con `prompt_version`, `system_prompt`, `examples[{title,description}]`, libre de memoria y datos del turno. 422 para opciones o versión inválidas. |
| E4 | GET `/api/v1/estimations` | React y HTML Go; `app/api/history.py`, `domain/schemas/history.py`, `test_history.py`, `test_history_postgres.py` | Query `limit=10`, entero 1–50. 200 array reciente primero, con ID, fecha, opciones, versión, caché, cifras, `out_of_scope` y extracto de hasta 200 caracteres. La descripción completa, métricas y memoria se omiten. 422 límite inválido, 503 historial indisponible. |
| E5 | GET `/api/v1/estimations/{estimation_id}` | React y HTML Go; mismos archivos de E4 | ID entero. 200 con fechas de solicitud y finalización, descripción, opciones, resultado, versión, caché, modelo y proveedor. `metrics`, `conversation_id`, `metadata_snapshot` y referencias en opciones pueden ser nulos. 404 registro ausente, 422 ID no convertible en Python (404 en HTML Go), 503 almacén indisponible. |
| E6 | POST `/api/v1/estimate` | API estructurada, Postman y adaptadores de compatibilidad Go y React; `app/api/project_estimations.py`, `domain/schemas/project_estimation.py`, `test_project_estimations.py` | JSON y query según el detalle de E6/E7 debajo. 200 con resultado tipado, versión, procedencia de caché, ID y métricas; 400 por guardrail, 422 por validación y 502 si se agota la validación del resultado; los fallos de proveedor se traducen en el SDK interno. |
| E7 | POST `/api/v1/estimate/stream` | API estructurada SSE y función auxiliar `request_structured_estimation` de `app/streamlit_client.py`; mismos archivos de E6 | Misma entrada. 400/422 JSON antes de abrir. 200 SSE: `result` → `metadata` → `done`; metadatos planos de llamada, versión, fuente de caché e ID anulable. Ante fallo tras abrir, `error{status_code,message}` terminal. |
| E8 | POST `/api/v1/transcription/estimate/stream` | Demo Python, API SSE y función auxiliar `stream_estimation` de `app/streamlit_client.py`; `app/api/estimations.py`, `domain/schemas/estimation.py`, `test_sse_and_options.py` | JSON `transcription` de 20–50 000; `preprocessing=none`, `example_format=markdown`, `num_examples=2`, `use_examples=true`, `evaluate=true`, `include_project_costs=false`, tarifas 62,5 y 50, `model` anulable (1–100 caracteres con patrón de identificador y catálogo), `max_tokens` anulable (1–16 000) y `thinking_budget` anulable (1024–15 000, requiere Anthropic compatible). `num_examples` admite 0 hasta el tamaño del catálogo y las tarifas son positivas, finitas y ≤10 000. Sin query de versión. 422 JSON por cuerpo u opciones inválidas antes del stream. 200 SSE: cero o más `token{text}` → `metadata` con uso por fase y campos de costes, evaluación y requisitos según opciones → `done`; `error` terminal ante fallo. |
| E9 | GET `/health` | Sondas y proxy; `app/main.py`, `test_main.py`, `nginx.conf.template`, `internal/web/server.go` | Sin entrada. Python 200 con `status="healthy"`, `environment`, `provider` y `model`. El 503 `status=unavailable` por fallo upstream corresponde a la futura sonda de Go. `GET /up` es local en Go y `GET /healthz` local en Nginx. |

### Detalle de la estimación estructurada (E6 y E7)

| Campo de entrada | Tipo, valor inicial y restricciones observadas |
|---|---|
| `description` | Cadena obligatoria, 20–80 000 caracteres, sin valor por defecto. |
| `project_type` | Obligatorio, sin valor por defecto. `mobile_app`, `web_saas`, `internal_tool` o `data_pipeline`. |
| `detail_level` | Obligatorio, sin valor por defecto. `summary`, `medium` o `detailed`. |
| `output_format` | Obligatorio, sin valor por defecto. `phases_table`, `line_items` o `narrative`. |
| `reference_projects` | Lista opcional de hasta cinco elementos. Omitida o explícitamente nula equivale a `null`. Cada elemento requiere `name` (1–120 caracteres), `description` (1–500) y `actual_hours` (número finito, mayor que 0 y ≤100 000). |
| `attachments_chars` | Campo interno de observabilidad del esquema (entero ≥0, por defecto 0, excluido al serializar). El formulario de sesión lo calcula a partir de adjuntos. |
| `prompt_version` | Query opcional, por defecto `v3`, máximo 10 caracteres y restringida a versiones disponibles en el loader (v1 a v4 en esta base). |

En E6, el JSON 200 contiene `result`, `prompt_version`, `cached` (por defecto `false` en el esquema), `cache_source` (`none` por defecto, `exact` o `semantic`), `estimation_id` y `metrics` anulables. El resultado incluye resumen de 1–2000 caracteres, confianza entera 0–100, 1–30 fases, duración total mayor que 0 y ≤2600 semanas, y coste total de 0 a 100 millones de euros. Cada fase incluye nombre de 1–120 caracteres, descripción de hasta 1000 (vacía por defecto), duración mayor que 0 y ≤520 semanas y coste de 0 a 100 millones. Duraciones y costes deben ser finitos. `out_of_scope` se calcula con confianza inferior a 30. Las métricas incluyen modelo, proveedor, motivo de fin, tokens, latencia, indicador de caché y costes anulables. E7 emite el mismo resultado en `result`; el evento `metadata` contiene las métricas en plano, más versión, fuente de caché e ID anulable. El primer evento de éxito se emite después del intento de guardado.

El guardrail devuelve 400 con `{reason,message}`. Un cuerpo inválido devuelve 422 con `detail` de validación y una versión desconocida devuelve 422 con `detail` de texto. En E7 esos errores se devuelven antes de abrir SSE. La capa LLM traduce fallos de proveedor a 400 con `detail` por rechazo, 429 por cuota, 504 por espera agotada o 502 por autenticación u otros fallos, según el error final tras las políticas del proveedor. E6 entrega esos códigos como HTTP. Tras abrir E7, las excepciones HTTP saneadas se representan en `error` y los fallos inesperados producen `error` con código 502.

Éxitos REST y errores previos a SSE usan JSON. SSE declara `text/event-stream`, `Cache-Control: no-cache` y `X-Accel-Buffering: no`; `done` lleva `status=complete`. El parser legado comprueba metadatos y rechaza un flujo incompleto. La referencia de desconexión ASGI cancela la estructurada durante la generación, antes del primer evento, y la transcripción tras el primer token. Las garantías de cierre a través de Nginx y Go, la liberación del SDK real y la ausencia de escritura parcial en ambos recorridos completos requieren sus pruebas de integración posteriores.

## 1.1 Operaciones adicionales de Ajustes y Lab

Los consumidores objetivo son React Ajustes, barra de navegación y Lab. Los GET carecen de cuerpo y query. Las mutaciones objetivo usan JSON. Todas las respuestas objetivo usan JSON, con `detail` saneado en fallos y 403 administrativo o de origen donde aplica. La capa futura comprueba también 404/405, 400 por JSON malformado, 413, 415 y 422 según el transporte.

| Caso | Método y ruta objetivo | Consumidor y referencia actual | Comprobaciones |
|---|---|---|---|
| A1 | GET `/api/v1/ai/settings` | Ajustes; GET HTML `/ai_settings` → `ConfigClient.Models` → GET Python `/api/v1/config/models`; `settings_test.go`, `test_config_api.py` | HTML 200 con catálogo filtrado por campo, o 422/503/502 con aviso. Objetivo 200 con catálogo filtrado por campo, `available_models`, `models.{effective,default,overridden}` con valores anulables para los dos primeros, y `embedding_model` y nota de solo lectura. Objetivo añade metadatos `fields`; 422 rechazo, 503 indisponible, 504 plazo, 502 fallo/contrato inválido. |
| A2 | PUT `/api/v1/ai/settings` | Ajustes; PATCH/PUT HTML y POST con `_method` y token CSRF → `ConfigClient.UpdateModels` → PUT Python `/api/v1/config/models`; mismos tests de A1 | Cuerpo `{models:{campo:string|null}}`. Omitido conserva, nulo restablece, vacío del formulario se convierte en nulo, se filtran desconocidos y sin campos válidos se rechaza antes de llamar. HTML devuelve 302 con aviso al guardar o si no llegaron campos válidos; el segundo caso evita el PUT a Python. Python devuelve 400 si falta la clave del proveedor, 422 por modelo/campo/proveedor inválido y 503 si falla la escritura. HTML traduce errores a 422/503/502. Objetivo 200 con A1 o 422/503/504/502 y actualiza indicador. |
| A3 | GET `/api/v1/ai/primary-model` | Barra React; badge HTML de `internal/web/server.go`; `home_test.go`, `settings_test.go` | 200 objetivo con solo `{model:string|null}`; plazo corto 2 s por defecto, caché de valor o ausencia 15 s, invalidada al guardar. HTML omite indicador si falla. |
| A4 | GET `/api/v1/rag/chunking-comparisons/options` | Nuevo Lab; GET HTML `/rag/chunking_comparisons/new`; `rag/strategy.go`, `estimatorai/corpus.go`, `lab_test.go` | HTML 200 con formulario, selección inicial y consultas predefinidas. El JSON objetivo devuelve 200 con `strategies[{name,label,description,cost_tier,cost_label,key_name,default_checked}]` (`key_name` anulable), `sample_queries`, `top_k:{default:3,min:1,max:10}` y `compare_timeout_seconds` (600 s por defecto). |
| A5 | POST `/api/v1/rag/chunking-comparisons` | Lab; POST HTML `/rag/chunking_comparisons` → `EmbeddingsClient.CompareChunking` → POST Python `/embeddings/compare`; `lab_test.go`, `pg_test.go` | `strategies` conocidas/únicas y no vacías, `queries` y `custom_queries` opcionales y normalizadas, `top_k` acotado 1–10; objetivo 3 omitido. Corpus propio y plazo largo. HTML 302 al guardar o 200 resultado con aviso si falla PostgreSQL. Objetivo 201 con `Location` e ID decimal textual o 200 con ID y fecha nulos. 422 selección/rechazo, 503 clave o conexión, 504 plazo, 502 servidor/contrato inválido. |
| A6 | GET `/api/v1/rag/chunking-comparisons` | Historial Lab; GET HTML `/rag/chunking_comparisons` → `Store.Recent`; `lab_test.go`, `pgstore_test.go` | Máximo 20, fecha e ID descendentes, sin recalcular. HTML devuelve 200 con listado o historial vacío con aviso al fallar el repositorio. El JSON objetivo devuelve 200 `{items,warning}` con aviso anulable y lista vacía si falla el repositorio. Cada resumen incluye ID textual, estrategias, consultas, `top_k`, corpus, duración anulable, fecha y coste. |
| A7 | GET `/api/v1/rag/chunking-comparisons/{id}` | Detalle Lab; GET HTML `/rag/chunking_comparisons/{id}` → `Store.Find`; `lab_test.go`, `pg_test.go`, `pgstore_test.go` | ID decimal de 64 bits, 404 inválido/ausente, 500 fallo de lectura. HTML 200 con tabla, costes y resultados. El JSON objetivo añade `result` y `warning` anulable al resumen; payload histórico incluye estadísticas por estrategia y top-k por consulta con similitud, extracto, nivel y padre anulables. |

Ajustes edita `primary_model`, `fallback_model`, `critic_model`, `metadata_model`, `summary_model`, `propositional_chunker_model` (OpenAI) y `contextual_chunker_model` (Anthropic). Python valida antes de persistir cambios, con rechazo de modelos, proveedores o claves incompatibles. El catálogo del Lab ofrece `structural`, `fixed_size`, `recursive`, `sentence_window`, `hierarchical`, `semantic`, `propositional` y `contextual_retrieval`; las primeras tres vienen marcadas. Las dos estrategias OpenAI que requieren clave son semántica y proposicional; contextual requiere Anthropic. Los resultados muestran distribución min/p50/p95/max, huérfanos, obesos, llamadas extra, duración, barras de coste y parentesco padre/hijo; sin consultas se muestra solo estadísticas.

## 1.2 Consumidores y previsión de retirada

| Recurso | Retirada prevista | Consumidor o comportamiento a conservar |
|---|---|---|
| `internal/web/server.go`, `estimations.go`, `settings.go`, `lab.go` | Raíz, `/estimations/new`, GET/POST `/estimations`, GET `/estimations/{id}`, POST `/conversation`, GET/PATCH/PUT `/ai_settings`, GET/POST Lab, GET nuevo/detalle y fallback HTML. | `templates/layout.html` y formularios son los consumidores actuales; conservar ciclo conversacional, errores, redirección equivalente, `/up`, casos de uso y adaptadores `internal/estimatorai`. |
| `internal/web/templates/*.html`, `templates.go`, `public/*` | Layout/inicio, estilos y scripts inline, vistas estadística/estimación/ajustes/Lab y páginas 404/422/500 embebidas. | Migrar componentes de resultado, sidebar, costes, consultas y navegación a los recorridos React; revisar política de `robots.txt` en el nuevo origen. `server.go` registra estos estáticos y uso de embeds. |
| `internal/session`, `internal/config/config.go`, `cmd/server/main.go` | Cookie firmada, flash, compactación, CSRF de formulario, `_method`, `SECRET_KEY_BASE` y `html/template` cuando desaparezca el último consumidor HTML. | `security_test.go` y `session_test.go` fijan el comportamiento transitorio. Mantener recuperación, logging y sonda, y verificar los futuros límites y origen en la frontera. |
| `internal/web/*_test.go`, `internal/rag`, `internal/estimatorai`, `internal/archtest` | Migrar expectativas HTML de inicio, estimación, conversación, ajustes, Lab, seguridad y funciones de presentación. | Preservar fakes reutilizables de `harness_test.go`, contratos de clientes, corpus, reglas, esquema, persistencia PostgreSQL y límites de importación. |
| `streamlit_app.py`, `app/streamlit_client.py`, `app/streamlit_support.py` | Chat, sidebar contextual local y sus pruebas exclusivas `test_streamlit_app.py` y `test_streamlit_support.py`. | `test_sse_and_options.py` y `test_project_estimations.py` importan el parser; conservar casos de servicio y trasladar parser de referencia. Renderizado, schemas, adjuntos, `httpx` y `python-multipart` sirven también al backend, pruebas o scripts. |
| `app/static/sse_demo.html` y montaje en `app/main.py` | Demo y montaje exclusivo `/static`. | La demo consume E8. Mantener las dos rutas SSE y sus pruebas. |
| `pyproject.toml`, `uv.lock`, Dockerfile Python, Compose raíz/secundario, `.env.example` Python | Dependencia Streamlit y transitivas exclusivas, copia, servicio chat, sonda, 8501 y `ESTIMATOR_API_BASE_URL`. | Mantener dependencias del servicio y del pipeline de pruebas. `test_project_structure.py` revisa empaquetado. React conserva Vite/Nginx y Go conserva su imagen y healthcheck. |
| `.github/workflows/estimador-cag-ci.yml`, `docker-compose.verify.yml`, Dockerfiles y utilidades | Adaptar sonda CI en localhost:8000 y acceso del perfil de estrés por host gateway para la futura frontera. | Mantener suites, scripts Python de migración/evaluación/ingesta y sus consumidores, servicios de verificación y diagnóstico. |
| README raíz y de servicios, arquitecturas, `docs/resilience-and-streaming.md`, `AGENTS.md`, `CLAUDE.md`, `openspec/config.yaml` | Actualizar referencias activas a clientes, puertos, secretos y montaje al ejecutar las tareas de retirada y documentación. | Mantener importación de la guía, datos históricos y archivo OpenSpec. Las menciones en trazas, informes de estrés y presupuestos históricos pueden ser datos del proyecto. |

## Diferencias observadas y criterios de paridad

- El historial del Lab usa `bigint` y enlaces HTML con dígitos decimales exactos. DA-27 añade la representación JSON textual para los IDs; el fixture comprueba tipo y datos históricos originales.
- La redacción de la matriz del diseño admite confusión sobre las opciones de E6/E7. La referencia comprobada en FastAPI exige los tres campos de opciones y hace opcional la lista de referencias. El esquema del turno E2 exige metadatos y contadores y permite nulos en los dos campos de audiencia.
- Go HTML conserva la sesión entre recargas mediante cookie, mientras React conserva el UUID en la SPA. La referencia HTML cubre reinicio, expiración con borrador y aviso, adjuntos, estado activo, error de vista previa, resultado inline sin ID, redirección al detalle con ID y resultado no estimable sin cifras. React ya tiene fixtures de transporte y navegación en `src/test/mockApi.ts`, `src/api/*.test.ts` y `src/pages/*.test.tsx`.
- Los futuros límites de transporte, plazos, autorización, mapeo de errores y propagación de cancelación entre servicios son criterios de las etapas de implementación correspondientes.

## Referencias de CI, utilidades y empaquetado

| Referencia | Alcance y tratamiento previsto |
|---|---|
| `.github/workflows/estimador-cag-ci.yml`, jobs `specs`, `test`, `web` y `web-react` | Conservar OpenSpec 1.13.2, Ruff, Pytest, gofmt, go vet, Go y Vitest/compilación React. Los jobs Python y Go usan bases de CI independientes. Actualizar la referencia a `test_streamlit_app.py` al retirar sus casos exclusivos y conservar las pruebas mixtas de SSE. |
| Mismo workflow, jobs `docker` y `stack` | Conservar la comprobación de imagen Python sin privilegios y la salud local. Los smoke checks usan FastAPI publicado en 8000, Go en 3000 (`/up`, historial HTML, Lab y Ajustes) y React en 3001 (`/healthz`, historial JSON y shell de la SPA). Retirar expectativas HTML y reemplazar el acceso directo desde el host a FastAPI por sondas internas o comprobaciones por la frontera Go según el propósito. |
| `estimador-cag/Dockerfile`, `estimador-cag/.dockerignore`, Compose raíz/secundario y `estimador-cag/.env.example` | Retirar en su etapa la copia y el montaje de `streamlit_app.py`, ejecución de Streamlit, publicación 8501, sonda `/_stcore/health` y variable del servicio chat. Conservar las etapas de test y runtime, prompt y datos de aplicación, scripts empaquetados, Alembic, Punkt y la sonda interna de FastAPI. |
| `estimator-web-go/Dockerfile`, `cmd/server/main.go`, `internal/config/config.go` y `estimator-web-react/Dockerfile`, `nginx.conf.template`, `vite.config.ts` | Conservar la imagen Go, su healthcheck `/up` y los contratos de almacenamiento y cliente de IA. Retirar la configuración de cookie HTML al desaparecer su consumidor. Conservar la compilación de la SPA en Node y Nginx sin privilegios con `/healthz`; cambiar el upstream de Vite y Nginx en la etapa de comunicaciones. |
| `estimador-cag/pyproject.toml` y `uv.lock` | Retirar Streamlit y regenerar el lock en su etapa; eliminar transitivas solo si el lock confirma que carecen de consumidores. Conservar `httpx` para scripts, SDK y pruebas ASGI, `python-multipart` para formularios de sesión, y los extractores y el renderizado de prompts compartidos. |
| `estimador-cag/scripts/preflight_s06.py`, `docker-compose.verify.yml` (`api-stress`) y `estimador-cag/postman/` | Preflight consulta `/health`; el perfil de estrés tiene acceso explícito al host por `host.docker.internal:8000`; Postman y cURL incluyen estimación estructurada y transcripción. Conservar diagnósticos y ejemplos de contratos con destino acorde al perímetro. El POST de transcripción sin SSE sigue como contrato interno de Python. |
| `estimador-cag/scripts/{ingest_corpus,build_task_corpus,build_contradictions_s11,query_examples}.py` | Los tres primeros usan `/embeddings/ingest` y el último `/search`. Preservar su ejecución interna y el parámetro de URL base. `ESTIMATOR_API_BASE_URL` también tiene estos consumidores, por lo que retirar su inyección al chat es independiente de su uso en utilidades. |

## Trazabilidad de aceptación del Bloque 1

Los nombres siguientes identifican pruebas de referencia disponibles para la Parte C. La revisión estática confirma la existencia y el alcance de los casos. Los resultados de ejecución figuran en la sección de la Parte C.

| Tarea y casos | Criterio | Evidencia de referencia |
|---|---|---|
| 1.1, E1–E2 | 201 UUID, conservación de sesión, parámetros y adjuntos del turno, metadatos y errores | `test_sessions_api.py` (`test_create_session_returns_a_uuid_v4_and_distinct_ids`, `test_estimate_returns_a_validated_result_with_session_state`, pruebas de adjuntos, campos, caducidad y guardrails); `clients_test.go` (`TestSessionEstimationSendsMultipartEvenWithoutAttachments`); `sessionApi.test.ts`. |
| 1.1, E3–E5 | Prompt y defaults, historial con límites, campos anulables, ID inválido, ausente e indisponibilidad | `test_history.py` (vista previa, límites, persistencia, detalle 404 y 503); `test_history_postgres.py`; `test_history_conversation.py` (metadatos y sesión persistidos); `estimations_test.go`, `estimatorApi.test.ts` y `pages.test.tsx` para consumidores. El 422 del parámetro de ruta no entero de FastAPI se identifica en la firma tipada de `history.py`; Go HTML y React cubren el rechazo local. |
| 1.1, E6–E9 | JSON estructurado y validación, flujos SSE completos o interrumpidos, y sondas | `test_project_estimations.py`, `test_sse_and_options.py` y `test_stream_disconnect.py` (orden, error terminal, rechazo previo y cierre ASGI); `test_main.py` para `/health`; `security_test.go::TestTheHealthProbeAnswers200WithoutCallingAnyone` para `/up`; smoke de CI para `/healthz`. |
| 1.1, A1–A7 | Método, consumidor, entrada, salida y errores | Referencias estáticas en las siete filas A1–A7. Sus equivalentes HTML o internos se ejercitan con las pruebas de 2.2 y 2.3. Las rutas JSON objetivo se verifican en las etapas 7 y 8. |
| 1.2 | Lista de retirada y conservación con consumidores identificados | Registro de rutas en `internal/web/server.go`, embeds, inventario de scripts, CI y empaquetado. `security_test.go`, `session_test.go` y `test_project_structure.py` cubren comportamientos y archivos del legado. |
| 2.1 | Base aislada y casos OK, sin ID, no estimable, expiración, error, adjuntos, vista previa, métricas y navegación | Configuración `docker-compose.verify.yml` + `compose.caracterizacion.yml`; en Python, E1–E9. En Go, `conversation_test.go`, `estimations_test.go` y `home_test.go`. En React, `src/pages/conversation.test.tsx`, `src/pages/pages.test.tsx` y fixtures de `src/test/mockApi.ts`. La Parte B debe confirmar el aislamiento efectivo. |
| 2.2, A1–A3 | Siete campos, catálogo, primario, restablecimiento y fallos | `test_config_api.py` (overrides parciales, atomicidad, validación y embeddings de solo lectura); `settings_test.go` y `home_test.go` (formulario, indicador, caducidad e invalidación). |
| 2.2, A4–A7 | Ocho estrategias, consultas, coste, top-k, resultados jerárquicos, historial y fallos de persistencia | `lab_test.go` (incluido `TestLegacyLabPostWithoutTopKUsesOne`), `rag/contracts_test.go`, `clients_test.go::TestCompareChunkingSendsCorpusAndReturnsPayload` y `pg_test.go` (guardado, detalle e historial con IA simulada). |
| 2.3, A6–A7 | IDs históricos exactos, orden, fechas y payload reutilizable en el corte | `pgstore_test.go::TestStoreReadsLegacyComparisonsWithoutChangingIDsOrPayload` siembra tres `int64` superiores a 2⁵³−1, verifica orden cronológico y desempate y compara por igualdad JSONB tanto el valor de la tabla como el payload devuelto por `Find` frente al fixture. |

## Desviaciones preexistentes y límites de la referencia

- El formulario HTML del Lab preselecciona 3, pero el decodificador del POST devuelve 1 si falta `top_k`. Es una inconsistencia histórica del formulario. DA-28 exige 3 para la futura API JSON.
- El adaptador Go de E6 usa `map[string]string` y por ello no expresa una lista de referencias. El helper React de E6 tiene pruebas de transporte con HTTP simulado, incluida una solicitud incompleta que FastAPI rechazaría. Para validar el esquema real se toma como referencia la suite Python, y para los formularios activos se toma el turno E2.
- Los casos de desconexión se limitan a ASGI 2.3 y a trabajo simulado. La aserción compara los bytes SSE con el flujo esperado y tolera un cuerpo de cierre vacío. El recorrido entre intermediarios y la liberación del recurso de proveedor requieren la verificación posterior.

## Entorno de caracterización preparado en la Parte B

El complemento se usa desde la raíz junto con `docker-compose.verify.yml`. El modelo efectivo tiene dos redes internas independientes con gateway de puente aislado. Cada una conecta únicamente la suite y su PostgreSQL de prueba. Lint y Vitest usan `network_mode: none`. Las bases usan `tmpfs`, y el modelo carece de volúmenes nombrados, puertos publicados, socket Docker y servicios heredados con acceso al host. Las cinco etiquetas de imagen pertenecen al proyecto. Lint reutiliza las imágenes de prueba.

`preparar-fuentes.py` crea o verifica `.block1/` a partir del árbol Git aprobado `307a8b9` y de los tres archivos de prueba revisados. Los montajes Python y Go son de solo lectura; los contextos para una eventual reconstrucción usan esas mismas copias. El entorno Compose no lee el `.env` del proyecto y el cliente Docker usa una configuración vacía para evitar heredar proxies y helpers de credenciales. La imagen de React incluye fuentes y dependencias; su árbol de fuentes se comprobó frente a la copia aprobada.

Los dos contenedores detenidos de la primera ejecución y la red `homelab-block1-307a8b9_default` quedan fuera del modelo efectivo. Los nuevos servicios se llaman `block1-api-db` y `block1-web-db`. Mantener desactivada la eliminación de huérfanos. Cualquier retirada de recursos residuales requiere aprobación explícita.

### Reproducción de la Parte C

Desde la raíz del repositorio. El vocabulario público `cl100k_base` se prepara en el host y se monta como un solo archivo de solo lectura. Los procesos de prueba siguen sin salida a Internet.

```bash
cache=.block1-evidencias/parte-c/cl100k_base.tiktoken
mkdir -p .block1-evidencias/parte-c
if [ ! -f "$cache" ]; then
  curl --fail --silent --show-error --max-time 20 \
    https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken -o "$cache"
fi
printf '%s  %s\n' 223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7 "$cache" | sha256sum -c -
```

Ejecutar cada fase en orden tras comprobar el almacenamiento y el hash. Inspeccionar cada base antes de ejecutar la suite, identificando el contenedor mediante `compose ps -q <servicio>`. Comprobar la etiqueta de proyecto y servicio, el estado saludable, la red, el montaje de datos en `tmpfs` y la ausencia de puertos publicados. Ante un error, registrar la salida, detener la base creada y comprobar el almacenamiento antes de continuar.

```bash
d=openspec/changes/homelab-route-clients-through-go
python3 "$d/preparar-fuentes.py"
export COMPOSE_REMOVE_ORPHANS=false
c=(docker --config .block1/docker-config --host unix:///var/run/docker.sock compose
   --env-file /dev/null -p homelab-block1-307a8b9
   -f docker-compose.verify.yml -f "$d/compose.caracterizacion.yml")

"${c[@]}" up -d --no-build --pull never --wait --wait-timeout 60 block1-api-db
"${c[@]}" run --rm --no-deps --pull never -T api-test -v \
  tests/test_main.py tests/test_sessions_api.py tests/test_project_estimations.py \
  tests/test_history.py tests/test_history_conversation.py tests/test_history_postgres.py \
  tests/test_config_api.py tests/test_sse_and_options.py tests/test_llm_service_streaming.py \
  tests/test_stream_disconnect.py
"${c[@]}" run --rm --no-deps --pull never -T api-lint check tests/test_stream_disconnect.py
"${c[@]}" stop block1-api-db
"${c[@]}" rm -f block1-api-db

"${c[@]}" up -d --no-build --pull never --wait --wait-timeout 60 block1-web-db
"${c[@]}" run --rm --no-deps --pull never -T web-test -count=1 -json ./...
"${c[@]}" stop block1-web-db
"${c[@]}" rm -f block1-web-db
"${c[@]}" run --rm --no-deps --pull never -T --entrypoint sh web-lint -ec \
  'go version; pending=$(gofmt -l .); test -z "$pending" || { printf "%s\n" "$pending"; exit 1; }'
"${c[@]}" run --rm --no-deps --pull never -T --entrypoint go web-lint vet ./...
"${c[@]}" run --rm --no-deps --pull never -T react-test npm test -- --maxWorkers=1 --reporter=verbose
```

Registrar el código y la salida de cada ejecución fuera de `/tmp` antes de pasar a la siguiente. Confirmar que los casos de persistencia se ejecutan y revisar cualquier error antes de continuar. Verificar titularidad y montajes de cada nueva base al iniciarla. La comprobación de paridad y el cierre de tareas dependen de la evidencia de la Parte C.

### Resultados de la Parte C

Ejecución final de las suites el 25 de noviembre de 2026, de 22:49:12 a 22:51:03 UTC. Los registros locales en `.block1-evidencias/parte-c/` conservan comandos completos, fecha, duración de la operación Docker y códigos de retorno, con los intentos Python previos en subdirectorios separados.

| Operación | Inicio UTC | Duración Docker | Código | Resultado |
|---|---|---:|---:|---|
| Pytest 9.1.1, Python 3.11.18 | 22:49:12 | 12 s | 0 | 155 aprobadas, 0 fallidas, 0 omitidas. 9.03 s en Pytest y una advertencia de deprecación de Starlette/AnyIO. |
| Ruff 0.16.10 según `uv.lock` | 22:49:24 | 1 s | 0 | `check tests/test_stream_disconnect.py` pasó. |
| `go test -p 1 -count=1 -json ./...`, Go 1.25.14 | 22:49:53 | 28 s | 0 | 190 eventos de prueba o subprueba aprobados, 0 fallidos, 0 omitidos. Nueve paquetes aprobados y `cmd/server` sin archivos de prueba. |
| `gofmt -l .`, Go 1.25.14 | 22:50:21 | 1 s | 0 | Sin archivos pendientes de formato. |
| `go vet ./...`, Go 1.25.14 | 22:50:22 | 6 s | 0 | Sin diagnósticos. |
| Vitest 5.0.3, Node 22.23.5 | 22:50:54 | 9 s | 0 | 9 archivos, 113 aprobadas, 0 fallidas y 0 omitidas. 7.29 s en Vitest. |

Vitest ejecutó ambos archivos de API, `components.test.tsx`, `hooks.test.tsx`, `attachments.test.ts`, `estimationForm.test.ts`, `format.test.ts`, `conversation.test.tsx` y `pages.test.tsx`. Imágenes reutilizadas (IDs abreviados), API `4062b6ded3c1`, Go `45171af038d7`, React `483dc26b02bd`, pgvector `b513c48566e4` y PostgreSQL Go `f9cf3e1f0066`. Docker Engine 29.10.0 y Compose 5.8.0.

El primer intento Python arrojó 6 errores de recolección (código 2) porque faltaba el vocabulario de tiktoken en la imagen y DNS estaba bloqueado. Ruff devolvió 2 porque la versión instalada requiere un booleano textual en `RUFF_NO_CACHE`. Se corrigió el entorno con el vocabulario estático verificado en solo lectura y `RUFF_NO_CACHE=true`. El segundo intento dio 154 aprobadas y una fallida (código 1). El doble de la estimación SSE estructurada rechazaba los argumentos del pipeline, lo que generaba un evento `error` 502 por `TypeError`. Se corrigió la firma del doble y se repitió la suite con las mismas aserciones de desconexión.

| Tarea | Evidencia de aceptación |
|---|---|
| 1.1 | Las matrices E1–E9 y A1–A7 quedan trazadas a métodos, rutas, consumidores, schemas y referencias de prueba. |
| 1.2 | El inventario identifica consumidores, retirada o conservación y recursos compartidos, incluidas referencias de CI y empaquetado. |
| 2.1 | Las dos bases arrancaron sanas, con `tmpfs`, sin puertos y en su red aislada. Pasaron el round-trip de historial Python con PostgreSQL y ambos casos de desconexión SSE. Pytest y los recorridos HTML y React corroboran estimación válida, no estimable, sin ID, expiración, adjuntos, métricas, errores y navegación. |
| 2.2 | Pasaron los casos HTML de Ajustes y Lab con IA simulada, incluidos siete campos, catálogo, indicador, ocho estrategias, consultas, jerarquía, fallo de persistencia y `TestLegacyLabPostWithoutTopKUsesOne`. |
| 2.3 | Pasaron `TestStoreReadsLegacyComparisonsWithoutChangingIDsOrPayload`, `TestLabEndToEndWithPostgreSQL` y `TestLabHistoryPersistsAcrossServerInstances`. El fixture verificó fechas, orden y desempate, tres IDs exactos superiores a 2⁵³−1, tipo `bigint` e igualdad semántica del JSONB almacenado y devuelto por `Find`. |

El contador `errors_count` de EXT4 en `/dev/sda2` permaneció en 0 y la consulta del kernel desde el cierre de la Parte B no encontró incidencias nuevas de SATA, EXT4 o E/S. Se retiraron las bases y los contenedores efímeros de la Parte C. El inventario final no muestra contenedores activos ni volúmenes del proyecto de pruebas. PostgreSQL y Open WebUI siguen saludables, Ollama sigue activo y `ai-network` conserva su ID y sus tres endpoints. En el cierre formal se retiraron los dos contenedores detenidos de la ejecución interrumpida y la red residual `homelab-block1-307a8b9_default` tras verificar su titularidad y que la red estaba vacía. Se conservaron las dos redes de caracterización y las imágenes reutilizables.
