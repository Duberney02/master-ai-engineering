# Design

## Context

El servicio `estimador-cag` ya tiene FastAPI, structlog, `pydantic-settings`, Docker Compose y un `OpenAIEmbedder` asíncrono para la caché semántica (`app/services/embeddings.py`). El ejercicio pide un pipeline independiente, síncrono por lotes y sin persistencia. Los nombres del enunciado se mapean así: el servicio de Compose es `estimador-cag` (el enunciado menciona `servicio_ia`), y los registros de log usan los campos permitidos por `app/logging_config.SAFE_FIELDS`.

## Decisions

**Paquete aparte.** `app/embedding_pipeline/` no importa de `app.services` ni de la ingesta de la sesión 6; sus modelos `Budget`/`BudgetComponent` son el contrato de entrada del endpoint (JSON normalizado), no los registros crudos del corpus.

**Contratos.** `Literal` solo donde se conocen todos los valores: no se conocen todos los de `complexity` ni `sector`, por lo que son `str` no vacío. Validadores explícitos: horas ≥ 0, año en rango razonable, identificadores no vacíos, `component_id` único dentro de un presupuesto y `budget_id` único dentro de la solicitud (el `chunk_id` `{budget_id}::{component_id}` debe ser único), y `budgets` con al menos un elemento. `IngestResponse.stats` es un `dict` con las cuatro claves pedidas.

**Chunker.** Un chunk por componente, texto con la plantilla del enunciado; los metadatos (`budget_id`, `component_id`, `client_sector`, `main_technology`, `year`, `complexity`, `estimated_hours`) viajan aparte y no se concatenan al texto. `token_count` con `tiktoken.encoding_for_model("text-embedding-3-small")` (se resuelve una vez por instancia). Sin overlap ni división de descripciones largas.

**Embedder síncrono.** `embed_one` y `embed_many` usan el cliente síncrono `openai.OpenAI` con `max_retries=0`: el SDK no reintenta por su cuenta, de modo que los únicos reintentos son los del enunciado (3 reintentos ante `RateLimitError`, esperas 1, 2 y 4 s; cualquier otro error se propaga). Los lotes son de 100 chunks (constante `BATCH_SIZE`); la respuesta se ordena por `index` para garantizar la correspondencia chunk–vector y se verifica que el número de vectores coincida. `model="text-embedding-3-small"` sin `dimensions`: la dimensión por defecto es 1536. El cliente se crea de forma perezosa con `OPENAI_API_KEY` de la configuración, de modo que importar el módulo no exige clave.

**Coste.** `PRICE_PER_MILLION_TOKENS_USD = 0.02`, constante de módulo marcada como variable en el tiempo (tarifa de referencia del enunciado). `estimated_cost_usd = total_tokens / 1_000_000 * precio`, calculado sobre los `token_count` locales; es una estimación, no la factura.

**Endpoint.** El handler es `def` (no `async`) porque el embedder es bloqueante: FastAPI lo ejecuta en su pool de hilos y no bloquea el bucle de eventos. El router no declara prefijo; `main.py` lo monta con `prefix="/embeddings"` y la ruta final es `/embeddings/ingest` (sin duplicar). `422` lo gestiona FastAPI/Pydantic; cualquier excepción del embedder se registra (tipo de error, sin contenido) y se responde `500` con un mensaje genérico. Chunker y embedder se inyectan con `Depends` para poder sustituirlos en pruebas.

**Logging.** Por lote: `chunks_count`, `total_tokens` y `latency_ms` (evento `embedding_batch_completed`); se añaden `chunks_count`, `total_budgets`, `total_chunks` y `estimated_cost_usd` a `SAFE_FIELDS`, que filtra todo lo demás.

**CLI.** `scripts/compare.py` añade la raíz del proyecto a `sys.path` (patrón de los demás scripts), construye `OpenAIEmbedder()`, obtiene ambos vectores y calcula `dot/(norm·norm)` con `math` (`math.fsum`, `math.sqrt`). Un vector de norma cero es un error explícito. Funciona con `docker compose exec estimador-cag ...` y con `uv run` en el host.

**Docker.** `tiktoken` se añade a `pyproject.toml` y se regenera `uv.lock` (el Dockerfile usa `--frozen`). Compose monta `./scripts` y `./data` en solo lectura junto a `./app`, para que la CLI y los datos estén disponibles en desarrollo sin reconstruir; la imagen de producción ya los copia. `tiktoken` descarga su vocabulario en el primer uso; el contenedor necesita red de salida y escribe la caché en el directorio temporal.

## Risks / Trade-offs

- La estimación de coste usa tokens locales y un precio fijo en código: puede divergir de la factura si OpenAI cambia la tarifa (de ahí la constante señalada).
- Una solicitud grande es una sola petición HTTP larga (lotes secuenciales); aceptable para el corpus de 15 presupuestos y fuera de alcance para cargas mayores.
- Los vectores solo existen en la respuesta; no hay caché ni persistencia.
