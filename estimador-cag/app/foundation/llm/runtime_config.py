"""Modelos de LLM configurables en tiempo de ejecución, respaldados por Redis.

`Settings` (`.env`) sigue siendo la capa inmutable de *valores por defecto*; este almacén guarda *overrides* como
deltas en un hash de Redis. Se pueden cambiar los modelos sin editar `.env` ni reiniciar: los overrides
sobreviven a reinicios y se comparten entre procesos (Redis es la fuente de verdad y se lee en cada solicitud).

Semántica de fallos:
- La lectura degrada con elegancia: si Redis no responde, se usan los valores por defecto de `Settings`.
- La escritura propaga el fallo (`RuntimeConfigUnavailable`): un cambio que no se aplicó debe verse (HTTP 503).

El modelo de embeddings queda fuera a propósito: cambiarlo invalidaría todos los vectores guardados.

Cada solicitud resuelve los overrides **una vez** al empezar (`effective_settings`) y trabaja con esa copia hasta el
final: un borrador y su crítica, o una estimación y su caché, nunca mezclan dos modelos. Un cambio aplica a partir
de la siguiente solicitud; las que están en vuelo terminan con el modelo con el que empezaron.
"""

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import Settings

logger = structlog.get_logger(__name__)

HASH_KEY = "estimator:runtime_config"

# Knob configurable -> campo de `Settings` que sustituye (el valor por defecto).
MODEL_KNOBS: dict[str, str] = {
    "primary_model": "llm_model",
    "fallback_model": "fallback_model",
    "critic_model": "critic_model",
    "metadata_model": "metadata_model",
    "summary_model": "summary_model",
    "propositional_chunker_model": "propositional_chunker_model",
    "contextual_chunker_model": "contextual_chunker_model",
}

# Knobs cuyo valor por defecto, si no está configurado, es el modelo primario efectivo.
INHERITS_PRIMARY = frozenset({"critic_model", "metadata_model", "summary_model"})

# Proveedor de un modelo por el prefijo de su nombre, y el setting con la clave de cada proveedor.
PROVIDER_KEY_FIELDS = {"openai": "openai_api_key", "anthropic": "anthropic_api_key"}
_OPENAI_PREFIXES = ("gpt", "o1", "o3", "o4", "chatgpt")


class RuntimeConfigUnavailable(Exception):
    """Falló la escritura de un override (Redis inaccesible o sin configurar)."""


def provider_for_model(model: str, default: str) -> str:
    """`anthropic` para `claude*`, `openai` para la familia GPT/o-series y `default` si el nombre no lo indica."""
    name = model.lower()
    if name.startswith("claude"):
        return "anthropic"
    if name.startswith(_OPENAI_PREFIXES):
        return "openai"
    return default


def provider_key_configured(settings: Settings, provider: str) -> bool:
    field = PROVIDER_KEY_FIELDS.get(provider)
    return bool(field and getattr(settings, field))


class RuntimeModelConfig:
    """Almacén de overrides de los knobs de modelo. No guarda estado: cada operación abre su conexión."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _client(self) -> Redis:
        return Redis.from_url(
            self.settings.redis_url,
            decode_responses=True,
            socket_timeout=self.settings.cache_timeout,
            socket_connect_timeout=self.settings.cache_timeout,
        )

    async def overrides(self) -> dict[str, str]:
        """Overrides vigentes; vacío si no hay Redis o no responde."""
        if not self.settings.redis_url:
            return {}
        try:
            async with self._client() as client:
                stored = await client.hgetall(HASH_KEY)
        except (RedisError, OSError):
            logger.warning("runtime_config_read_failed")
            return {}
        return {key: value for key, value in stored.items() if key in MODEL_KNOBS and value}

    async def set_many(self, changes: dict[str, str | None]) -> None:
        """Aplica todos los cambios de golpe (transacción de Redis); `None` borra el override del knob."""
        if not self.settings.redis_url:
            raise RuntimeConfigUnavailable("redis_url is not configured")
        try:
            async with self._client() as client:
                async with client.pipeline(transaction=True) as pipe:
                    for knob, value in changes.items():
                        if value is None:
                            pipe.hdel(HASH_KEY, knob)
                        else:
                            pipe.hset(HASH_KEY, knob, value)
                    await pipe.execute()
        except (RedisError, OSError) as exc:
            raise RuntimeConfigUnavailable(type(exc).__name__) from exc

    def default(self, knob: str) -> str | None:
        """Valor de `Settings` para el knob; los de tarea sin modelo propio heredan el primario."""
        value = getattr(self.settings, MODEL_KNOBS[knob])
        if knob == "primary_model":
            return self.settings.effective_model()
        if value is None and knob in INHERITS_PRIMARY:
            return self.settings.effective_model()
        return value

    async def snapshot(self) -> dict[str, dict[str, str | bool | None]]:
        """Por knob: `effective`, `default` y si hay `overridden`."""
        overrides = await self.overrides()
        return {
            knob: {
                "effective": overrides.get(knob) or self.default(knob),
                "default": self.default(knob),
                "overridden": knob in overrides,
            }
            for knob in MODEL_KNOBS
        }


async def effective_settings(settings: Settings) -> Settings:
    """Copia de `settings` con los overrides vigentes aplicados (la misma instancia si no hay ninguno).

    Un override cuyo proveedor ya no tiene clave configurada se ignora con un aviso en lugar de romper la solicitud.
    """
    overrides = await RuntimeModelConfig(settings).overrides()
    if not overrides:
        return settings
    update: dict[str, str | None] = {}
    for knob, model in overrides.items():
        provider = provider_for_model(model, settings.llm_provider)
        if not provider_key_configured(settings, provider):
            logger.warning("runtime_config_override_ignored", key=knob, reason="provider_key_missing")
            continue
        update[MODEL_KNOBS[knob]] = model
        if knob == "primary_model":
            # Cambiar el primario cambia también el proveedor y suplanta al modelo de estimación fijado en `.env`.
            update["llm_provider"] = provider
            update["estimator_model"] = None
        elif knob == "fallback_model":
            update["fallback_provider"] = provider
    return settings.model_copy(update=update) if update else settings


async def task_model(settings: Settings, knob: str) -> str | None:
    """Modelo propio de una tarea (override o `Settings`); `None` si usa el modelo primario."""
    overrides = await RuntimeModelConfig(settings).overrides()
    override = overrides.get(knob)
    if override and provider_key_configured(settings, provider_for_model(override, settings.llm_provider)):
        return override
    return getattr(settings, MODEL_KNOBS[knob]) or None
