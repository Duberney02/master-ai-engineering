# Design

## Context

El repo tiene `embedding-pipeline-minimo` (chunking estructural, embedder síncrono, `/embeddings/ingest` y `scripts/compare.py`). La referencia lo amplía con siete estrategias, un comparador, un endpoint y una CLI. Aquí se implementa el mismo *qué* con las convenciones del repo: SDK asíncronos, errores saneados, settings en minúsculas, español y pruebas sin claves.

## Decisions

**Async de extremo a extremo.** `Chunker.chunk` es `async`, igual que el embedder y el comparador. La referencia usa SDK síncronos (`OpenAI`, `anthropic.Anthropic`) en handlers `def`; el repo exige SDK asíncronos y no bloquear el event loop. Beneficio añadido: las estrategias con LLM llaman en paralelo (semáforo de 8) y no secuencialmente (la referencia tardó ~3 min por estrategia).

**Sin LangChain.** La referencia envuelve `RecursiveCharacterTextSplitter` y `SemanticChunker` de LangChain. Aquí se implementan en ~60 líneas cada uno sobre `tiktoken` y el embedder del proyecto: menos dependencias pesadas, async nativo y pruebas con un embedder falso. El troceo recursivo sigue el mismo algoritmo (separadores de grueso a fino, fusión hasta N tokens con solapamiento). El semántico embebe cada frase junto a sus vecinas, mide la distancia coseno entre consecutivas y corta por encima del percentil 95.

**NLTK Punkt, descargado al construir la imagen.** `sentence_window` y `semantic` necesitan separar frases. Se usa Punkt (como la referencia) pero la descarga se hace en el `Dockerfile` (etapas `builder` y `test`, `NLTK_DATA=/opt/nltk_data`) y se copia al runtime; en ejecución no se descarga nada ni se escribe en disco, y si faltan los datos el error es explícito. Alternativa descartada: un separador por expresión regular, que parte mal abreviaturas.

**Por defecto, solo estrategias gratuitas.** La referencia ejecuta *todas* las estrategias si `strategies` va vacío (incluidas las de pago, ~0,15 USD y varios minutos). Aquí vacío significa las cinco gratuitas; `semantic`, `propositional` y `contextual_retrieval` son opt-in por nombre. Es un cambio deliberado de la regla de coste.

**Errores diferenciados y saneados.** 400 estrategia desconocida; 503 cuando falta la clave del proveedor (el mensaje nombra la variable, nunca su valor) o cuando se piden consultas sin `OPENAI_API_KEY`; 500 genérico ante un fallo de cómputo (el detalle va al log). La referencia devuelve 500 con el texto de la excepción en el caso de clave ausente; aquí 503 es más exacto (servicio no configurado) y no filtra nada.

**Proveedor del modelo configurable validado.** `propositional_chunker_model` debe ser de OpenAI y `contextual_chunker_model` de Anthropic (usa `cache_control`); si el modelo configurado no encaja con la estrategia se informa como estrategia no disponible (503) en vez de fallar en mitad de la comparación.

**Costes.** `pricing.py` toma el precio de `Settings.model_prices` si existe y, si no, de una tabla por defecto; el prompt caching se valora con los factores de Anthropic (escritura ×1,25, lectura ×0,10). Los precios son una estimación declarada variable en el tiempo.

**Contexto del chunk contextual.** Para que la caché del prompt se escriba antes de leerse, la primera llamada de cada presupuesto va sola y las demás en paralelo.

**Campos aditivos en `TopChunk`** (`level`, `parent_chunk_id`) para que el cliente muestre padre/hijo sin deducirlo del `chunk_id`.

**Corpus.** Los 15 presupuestos existentes no producen casos degenerados (la descripción más larga mide 165 caracteres). `data/budgets_stress_cases.json` añade tres presupuestos propios: un monolito con un componente de >800 tokens (obeso), un backlog de tareas mínimas (huérfanos) y descripciones de varias frases. La CLI usa ambos archivos; los tests existentes siguen usando solo `budgets_sample.json`.

**Qué no cambia.** `POST /embeddings/ingest` conserva ruta y JSON (el handler pasa a `async`). `scripts/compare.py` se mantiene y reutiliza el coseno de `analysis/similarity.py`. Las dimensiones solo se comparan por CLI (`--dimensions`), no por el endpoint, como en la referencia.

## Risks / Trade-offs

- Los precios por defecto envejecen; el coste reportado es una estimación y así se declara.
- Las estrategias con LLM no se han ejecutado contra proveedores reales en esta rama (sin claves); se prueban con clientes falsos. El informe versionado incluye solo las gratuitas.
- Punkt separa mal abreviaturas inglesas como «e.g.»; es una limitación conocida del tokenizador y afecta solo a `sentence_window` y `semantic`.
