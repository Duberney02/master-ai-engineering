"""Almacén Redis de pares clave/valor JSON para la caché de completions y la de resultados.

Es fontanería sin opinión de dominio: las claves y su contenido los decide quien llama
(`generation/cag/exact.py` para resultados validados; el wrapper del LLM para completions).
Cualquier fallo de Redis se registra y se trata como ausencia, nunca como error de la solicitud.
"""

import hashlib
import json

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import Settings

logger = structlog.get_logger(__name__)


def digest(payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def make_key(**payload) -> str:
    return "estimation:v1:" + digest(payload)


class EstimationCache:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _client(self):
        return Redis.from_url(
            self.settings.redis_url,
            decode_responses=True,
            socket_timeout=self.settings.cache_timeout,
            socket_connect_timeout=self.settings.cache_timeout,
        )

    async def get(self, key: str) -> dict | None:
        if not self.settings.redis_url:
            return None
        try:
            async with self._client() as client:
                raw = await client.get(key)
            value = json.loads(raw) if raw else None
            return value if isinstance(value, dict) else None
        except (RedisError, OSError, ValueError, TypeError):
            logger.warning("cache_read_unavailable")
            return None

    async def set(self, key: str, value: dict) -> None:
        if not self.settings.redis_url:
            return
        try:
            async with self._client() as client:
                await client.setex(key, self.settings.cache_ttl, json.dumps(value))
        except (RedisError, OSError, ValueError, TypeError):
            logger.warning("cache_write_unavailable")
