# Design

## Context

Hoy el modelo sale de `Settings` (`llm_model`, `fallback_model`, `critic_model`, `summary_model`, `metadata_model`, `estimator_model`), fijo al arrancar. La resolución del modelo está repartida: el módulo de LLM llama a `get_settings()` en cada función, el pipeline calcula la clave de caché con `effective_model()` y el crítico, el resumidor, el detector de anclas y el servicio de sesiones leen su campo de `Settings`. La referencia añade `RuntimeModelConfig` (hash de Redis) y consulta el almacén en cada llamada.

## Decisions

**`Settings` inmutable + overrides como deltas.** El almacén es un hash de Redis (`estimator:runtime_config`) con un campo por knob; `.env` sigue siendo el valor por defecto y un `null` borra el campo. Redis es la fuente de verdad: sobrevive a reinicios y se comparte entre procesos.

**Resolución una vez por solicitud, no por llamada.** La referencia consulta el almacén en cada llamada al LLM. Aquí `effective_settings(settings)` lee los overrides una vez al empezar la solicitud y devuelve una copia de `Settings` con ellos aplicados; todo lo que cuelga de la solicitud (clave de la caché exacta, filtro de la semántica, generación) usa esa copia. Motivos: (1) coherencia: un borrador y su crítica, o la clave de caché y el modelo que genera, no pueden mezclar dos modelos; (2) una lectura de Redis por solicitud en lugar de una por llamada. Coste asumido: una solicitud ya en vuelo termina con el modelo con el que empezó y el cambio aplica desde la siguiente. Las llamadas sueltas (`generate_from_messages` del crítico, por ejemplo) resuelven por su cuenta, por lo que una solicitud ACB larga puede ver el cambio entre iteraciones; es aceptable porque cada llamada sigue siendo coherente consigo misma.

**Misma copia hasta la generación.** `EstimationPipeline` resuelve una vez y pasa esa copia a `generate_from_prompts(settings=…)`, de modo que la clave de la caché exacta y el modelo usado coinciden aunque el override cambie en mitad de la solicitud.

**Proveedor inferido del modelo.** Un override del primario cambia también `llm_provider` (por prefijo: `claude*`→Anthropic, `gpt*`/`o1…`→OpenAI), y el del fallback, `fallback_provider`. El wrapper elige el SDK por el modelo de cada llamada, lo que permite un crítico de Anthropic con un primario de OpenAI; un nombre desconocido conserva el proveedor configurado, así que el comportamiento de `.env` no cambia. La referencia hace lo mismo con LiteLLM.

**Override del primario suplanta a `estimator_model`.** Si `.env` fija un modelo de estimación y el operador cambia el primario en runtime, gana el primario (el contrario sería un cambio sin efecto en el flujo de sesiones). Restablecer devuelve el valor de `.env`.

**Un override sin clave se ignora, no rompe.** Si entre el PUT y una solicitud desaparece la clave del proveedor (cambio de `.env`), el override se descarta con un aviso y la solicitud usa el valor por defecto.

**Fallback bajo un override.** El fallback es independiente: cuando el primario (efectivo) falla de forma reintentable se intenta el fallback efectivo (el configurado en `.env` o su override). Si el operador pone como primario el mismo modelo que el fallback, el «fallback» reintentará el mismo modelo; la API no lo prohíbe. Sin fallback configurado no hay segundo intento.

**Embeddings fuera de los knobs.** Cambiar `embedding_model` invalidaría todos los vectores (caché semántica, futuros índices de la Sesión 8). La API lo devuelve en solo lectura con una nota.

**Catálogo propio.** `available_models` (lista separada por comas, como `allowed_models`) es el catálogo de la pantalla de Ajustes; `allowed_models` sigue limitando el campo `model` de cada solicitud. Son conceptos distintos, no se fusionan. La API devuelve solo los modelos cuyo proveedor tiene clave.

**API.** Rutas nuevas y aditivas. Lectura: `{models: {knob: {effective, default, overridden}}, available_models, embedding_model, embedding_model_note}`. Escritura: parcial, validada entera antes de escribir y aplicada en una transacción de Redis (todo o nada); códigos 422/400/503 como la referencia, con mensajes en español y sin exponer claves ni la excepción del almacén. Los knobs usan los nombres de los settings en minúsculas (`primary_model`, …). Sin autenticación, como el resto de rutas del servicio.

**Caché semántica por modelo.** `model` pasa a ser un tag filtrable (como `prompt_version`). El modelo de la entrada es el que la generó (`entry.model`); la consulta filtra por el primario efectivo. El nombre del índice termina en `_by_model` porque el esquema cambia (un índice existente de redisvl no admite un campo nuevo): las entradas antiguas quedan huérfanas y caducan por TTL. La referencia lo resuelve añadiendo el modelo al nombre del bucket; aquí es un filtro, coherente con el diseño del repo. Si un fallback sirvió la respuesta, queda en el bucket del modelo fallback y no se sirve bajo el primario: es lo correcto.

**Diferencias con la referencia.** (1) Resolución por solicitud en lugar de por llamada. (2) Cliente `redis.asyncio` en lugar de síncrono. (3) El catálogo incluye `claude-haiku-4-5` sin sufijo de fecha, igual que `model_prices` del repo. (4) Validación adicional: los chunkers con LLM solo aceptan el proveedor que usan. (5) Un override sin clave se ignora en lugar de fallar.

## Risks / Trade-offs

- Una lectura de Redis por solicitud (timeout `cache_timeout`, 0,5 s por defecto); si Redis cae se usa `.env` sin error.
- Un cambio en mitad de una conversación mezcla modelos entre turnos (no dentro de uno); es el comportamiento buscado al comparar modelos.
- Sin autenticación, cualquiera con acceso a la API puede cambiar el modelo y, por tanto, el coste. Es coherente con el resto del servicio (sin autenticación) pero debe protegerse en despliegues reales con la red o un proxy.
