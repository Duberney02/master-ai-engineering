# Design

## Context

`EstimationCache` crea un cliente `redis.asyncio.Redis` por operación (`Redis.from_url(...)`) y degrada a «sin caché» ante cualquier error. `Settings` valida el proveedor y las claves pero deja `app_env` y `log_level` como `str`; `configure_logging` solo comprueba `environment == "production"` y cae a `INFO` si el nivel no existe.

## Decisions

**FakeRedis sin tocar el código de producción.** Las pruebas sustituyen `Redis.from_url` por una fábrica que devuelve `fakeredis.aioredis.FakeRedis` sobre un `FakeServer` compartido: cada operación del código crea su propio cliente (y lo cierra con `async with`), así que los datos deben vivir en el servidor y no en el cliente. Se comprueba la ida y vuelta (`set` → `get`), la serialización (JSON con caracteres no ASCII, valores no JSON y JSON que no es un objeto se tratan como fallo de lectura, nunca como excepción) y el TTL (`ttl` del servidor igual a `CACHE_TTL`, con caducidad real al avanzar el tiempo del servidor). `fakeredis` es dependencia de desarrollo.

**`Literal` con normalización previa.** `app_env` y `log_level` pasan a `Literal` con un validador `mode="before"` que normaliza (`strip`, minúsculas para el entorno, mayúsculas para el nivel) para no romper `.env` existentes escritos como `Production` o `debug`. Los valores válidos son los que el resto del código ya distingue: `production` activa el JSON y los niveles son los de `logging`. `WARN` y `FATAL` (alias legados de `logging`) no se admiten para tener un único nombre por nivel.

**Ruff mínimo.** Reglas `E`, `W`, `F`, `I` con longitud 120 (el código existente ya la sigue; las pruebas están exentas de `E501` porque contienen datos largos). Se aplicó `--fix` solo a ordenación de imports e imports sin usar y se acortaron las líneas largas restantes de la aplicación. No se activa `ruff format` para no reescribir archivos existentes.

**Servicios Docker de verificación en un Compose aparte** (`docker-compose.verify.yml`), reutilizando la etapa `test` de `estimador-cag/Dockerfile` con el código montado (sin reconstruir la imagen) y una imagen mínima de Node con el CLI de OpenSpec fijado a la versión documentada. El Compose de producción no cambia.

**Evaluación de librerías.** Se resume en `docs/evaluacion-instructor-litellm.md` con el criterio: aportar una ventaja medible sobre lo que ya hay sin duplicar caché, reintentos, fallback, costes ni errores saneados. Resultado: la primitiva propia basada en Pydantic (`generate_structured`) cubre los usos actuales; Instructor y LiteLLM no se adoptan ahora.
