"""Idempotencia de `POST /v1/estimate/from-transcript` (Sesión 9).

Un cliente puede reintentar con la misma `idempotency_key` y recibir la estimación original sin volver a pagar el
pipeline del LLM. Dos backends tras el mismo contrato (`get` / `set`):

* **Redis** (cliente asíncrono) cuando hay `REDIS_URL`: sobrevive a reinicios, se comparte entre workers y caduca
  con el TTL nativo. Un fallo de Redis se registra y la operación cae al almacén en memoria: nunca rompe la petición.
* **Memoria del proceso** en otro caso, con caducidad manual: la funcionalidad sirve en pruebas y en desarrollo.
"""

import time
from collections.abc import Callable

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.generation.rag.schemas import Estimate

logger = structlog.get_logger(__name__)

KEY_PREFIX = "idempotency:estimate:"
# Tope de entradas del almacén en memoria: al superarlo se descartan las más antiguas.
MEMORY_MAX_ENTRIES = 1000


class IdempotencyStore:
    """Estimaciones guardadas por clave de idempotencia del cliente."""

    def __init__(self, *, ttl: int, redis_factory: Callable[[], Redis] | None = None) -> None:
        self._ttl = ttl
        self._redis_factory = redis_factory
        self._memory: dict[str, tuple[str, float]] = {}

    @property
    def backend(self) -> str:
        return "redis" if self._redis_factory else "memory"

    async def get(self, key: str) -> Estimate | None:
        """La estimación guardada para `key` o `None`; una entrada corrupta cuenta como ausencia."""
        raw = await self._get_raw(key)
        if raw is None:
            return None
        try:
            return Estimate.model_validate_json(raw)
        except ValueError:
            logger.warning("idempotency_entry_invalid")
            return None

    async def set(self, key: str, estimate: Estimate) -> None:
        raw = estimate.model_dump_json()
        if self._redis_factory is not None:
            try:
                async with self._redis_factory() as client:
                    await client.set(KEY_PREFIX + key, raw, ex=self._ttl)
                return
            except (RedisError, OSError) as exc:
                logger.warning("idempotency_redis_unavailable", error_type=type(exc).__name__)
        self._memory_set(key, raw)

    async def _get_raw(self, key: str) -> str | None:
        if self._redis_factory is not None:
            try:
                async with self._redis_factory() as client:
                    raw = await client.get(KEY_PREFIX + key)
                if raw is not None:
                    return raw
            except (RedisError, OSError) as exc:
                logger.warning("idempotency_redis_unavailable", error_type=type(exc).__name__)
        return self._memory_get(key)

    def _memory_get(self, key: str) -> str | None:
        entry = self._memory.get(key)
        if entry is None:
            return None
        raw, expires_at = entry
        if time.monotonic() >= expires_at:
            self._memory.pop(key, None)
            return None
        return raw

    def _memory_set(self, key: str, raw: str) -> None:
        now = time.monotonic()
        self._memory = {k: v for k, v in self._memory.items() if v[1] > now}
        while len(self._memory) >= MEMORY_MAX_ENTRIES:
            self._memory.pop(next(iter(self._memory)))
        self._memory[key] = (raw, now + self._ttl)
