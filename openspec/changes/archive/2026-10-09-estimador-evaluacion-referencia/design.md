# Design

## Context

La evaluación estructural previa (`evaluate_estimation`) trabaja sobre Markdown. El flujo estructurado devuelve `EstimationResult` (resumen, confianza, fases, totales). Los endpoints de sesión y `estimate-acb` ya existen y son el punto de entrada natural: ejercitan guardrails, memoria, audiencia y, en modo `acb`, el crítico.

## Goals / Non-Goals

**Goals:** casos de referencia repetibles; métricas deterministas y baratas; ejecutar contra la API real (en proceso o por HTTP); salida legible por máquina y código de salida usable en pipelines.

**Non-Goals:** juez LLM, métricas de redacción, CI con claves reales.

## Decisions

**Paquete `evals/` fuera de `app/`.** Es herramienta de desarrollo: no se despliega ni se copia a la imagen runtime (el Dockerfile solo copia `app/`). Se ejecuta con `python -m evals.runner` en el contenedor de desarrollo (`api-eval`). La evaluación previa se queda en `app/services/evaluation.py`.

**Dataset en JSON versionado.** `evals/datasets/reference_v1.json` con `version`, `description` y `cases`; se valida con modelos Pydantic (`EvalDataset`, `EvalCase`, `Expectations`) para que un caso mal formado falle al cargar, no a mitad de una ejecución. Los 16 casos son dos por categoría (`saas`, `mobile`, `internal_tool`, `data_pipeline`, `vague`, `adversarial`, `regulatory`, `tight_deadline`). Los requisitos y tecnologías esperados son palabras clave con alternativas separadas por `|` (por ejemplo `rgpd|gdpr|protección de datos`), insensibles a mayúsculas y acentos. Los rangos son `[mín, máx]` y opcionales: una entrada vaga no los define. Un caso puede declarar `expect_out_of_scope` (el estimador debe negarse a dar cifras) o `expect_rejection` (los guardrails deben rechazar la entrada con esa razón: caso adversarial de inyección).

**Métricas puras** (`metrics.py`): cada una devuelve `MetricResult(name, score 0–1, passed, details)`.
- `schema_adherence`: reutiliza las reglas de negocio de `app.services.validation` (suma de costes, prefijo fuera de alcance) y añade coherencia de duraciones (la total no es menor que la fase más larga ni mayor que la suma), nombres de fase únicos, forma del resultado fuera de alcance (una fase marcadora con coste 0) y número de fases dentro del rango del caso. La puntuación es la fracción de comprobaciones superadas.
- `cost_bounds`: compara coste y duración totales con los rangos del caso y comprueba que `out_of_scope` coincide con lo esperado (una estimación fuera de alcance no se evalúa contra rangos).
- `content_recall`: fracción de requisitos y tecnologías esperados presentes en el resumen y las fases; aprueba con al menos `min_recall` (0,6 por defecto). Sin expectativas aprueba con puntuación 1.
Un caso se aprueba solo si aprueban las tres métricas.

**Runner sobre HTTP.** Usa el contrato público: `POST /api/v1/sessions` y después `POST /sessions/{id}/estimate` o `estimate-acb`, con una sesión nueva por caso (sin contaminación entre casos). Recibe un cliente con interfaz `httpx` (`post`/`get`): `fastapi.testclient.TestClient` en proceso (dentro de `with`, para compartir el bucle de eventos y ejecutar el ciclo de vida) o `httpx.Client(base_url=...)` contra una URL. Así el mismo código mide el servicio local y uno desplegado, y las pruebas inyectan un cliente con proveedores simulados.

**Códigos de salida.** `0` si todos los casos evaluados aprueban; `1` si alguno falla o da error; `2` para uso incorrecto (argumentos, dataset ilegible o ningún caso seleccionado). Un error de un caso (HTTP, red, JSON) se registra en el reporte y no interrumpe el resto.

**Reporte.** `--output ruta.json` escribe `{dataset, mode, prompt_version, started_at, totals{evaluated,passed,failed,errors}, cases[]}`; cada caso lleva `id`, `category`, `status`, `passed`, `latency_ms`, `metrics`, `estimation` (resumen acotado, cifras y fases), `prompt_version`, `acb_final_decision`, `http_status` y `error`. No incluye la transcripción completa ni claves.

## Risks / Trade-offs

- Las palabras clave penalizan sinónimos legítimos; las alternativas con `|` y `min_recall` lo mitigan, y se documenta que las métricas son un termómetro, no un juez.
- Los rangos de coste dependen de la tarifa del prompt (60 EUR/h) y del criterio del dataset; se revisan al versionar un dataset nuevo en vez de editar el publicado.
- Ejecutar el dataset contra un proveedor real tiene coste (16 casos; el modo `acb` multiplica las llamadas).
