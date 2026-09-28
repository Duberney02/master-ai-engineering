"""Caché de coincidencia exacta de resultados LLM sobre Redis.

- Clave: `<prefijo>:v<versión>:llm:<sha256>` sobre una serialización JSON canónica
  (claves ordenadas, separadores fijos, UTF-8) de todo lo que afecta a la generación.
- Valor: JSON con versión de esquema; entradas corruptas o de otra versión se tratan
  como fallo de caché (y se borran de forma best-effort).
- Toda operación Redis tiene timeout acotado; ante error se registra, se devuelve
  estado `error` y la aplicación sigue sin caché. Tras un fallo se deja de consultar
  Redis durante `retry_after` segundos para no sumar latencia en cada petición.
"""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol, TypeVar

logger = logging.getLogger(__name__)

# Súbela si cambia el formato de la entrada o de la clave: invalida todo lo anterior.
CACHE_SCHEMA_VERSION = 1

T = TypeVar("T")
LookupStatus = Literal["hit", "miss", "disabled", "error"]


class RedisLike(Protocol):
    async def get(self, name: str) -> bytes | str | None: ...
    async def set(self, name: str, value: str, ex: int | None = None) -> Any: ...
    async def delete(self, *names: str) -> Any: ...
    async def ping(self) -> Any: ...
    async def aclose(self) -> None: ...


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class CachedCompletion:
    """Resultado completo y confirmado de una llamada, tal como se generó."""

    text: str
    provider: str
    model: str | None
    requested_model: str
    finish_reason: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    generated_at: datetime
    original_cost_usd: float | None
    fallback_used: bool

    def to_json(self) -> str:
        return canonical_json(
            {
                "schema": CACHE_SCHEMA_VERSION,
                "text": self.text,
                "provider": self.provider,
                "model": self.model,
                "requested_model": self.requested_model,
                "finish_reason": self.finish_reason,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "latency_ms": self.latency_ms,
                "generated_at": self.generated_at.isoformat(),
                "original_cost_usd": self.original_cost_usd,
                "fallback_used": self.fallback_used,
            }
        )

    @classmethod
    def from_json(cls, raw: bytes | str) -> "CachedCompletion":
        """Lanza ValueError si la entrada está corrupta o es de otra versión."""
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("schema") != CACHE_SCHEMA_VERSION:
                raise ValueError("incompatible schema")
            entry = cls(
                text=_typed(data["text"], str),
                provider=_typed(data["provider"], str),
                model=_optional(data["model"], str),
                requested_model=_typed(data["requested_model"], str),
                finish_reason=_typed(data["finish_reason"], str),
                input_tokens=_optional(data["input_tokens"], int),
                output_tokens=_optional(data["output_tokens"], int),
                latency_ms=_typed(data["latency_ms"], int),
                generated_at=datetime.fromisoformat(_typed(data["generated_at"], str)),
                original_cost_usd=_optional_number(data["original_cost_usd"]),
                fallback_used=_typed(data["fallback_used"], bool),
            )
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"corrupt cache entry: {type(exc).__name__}") from None
        if not entry.text.strip():
            raise ValueError("corrupt cache entry: empty text")
        return entry


def _typed(value: Any, kind: type) -> Any:
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise TypeError(kind.__name__)
    return value


def _optional(value: Any, kind: type) -> Any:
    return None if value is None else _typed(value, kind)


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("number")
    return float(value)


class ResultCache:
    def __init__(
        self,
        redis: RedisLike | None,
        *,
        enabled: bool = True,
        prefix: str = "estimador-cag",
        ttl_seconds: int = 86_400,
        op_timeout: float = 0.5,
        retry_after: float = 15.0,
        clock=time.monotonic,
    ):
        self._redis = redis
        self.enabled = enabled and redis is not None
        self._prefix = prefix
        self.ttl_seconds = ttl_seconds
        self._timeout = op_timeout
        self._retry_after = retry_after
        self._clock = clock
        self._down_until = 0.0

    def key_for(self, payload: dict[str, Any]) -> str:
        digest = hashlib.sha256(
            canonical_json({"schema": CACHE_SCHEMA_VERSION, **payload}).encode("utf-8")
        ).hexdigest()
        return f"{self._prefix}:v{CACHE_SCHEMA_VERSION}:llm:{digest}"

    async def get(self, key: str) -> tuple[CachedCompletion | None, LookupStatus]:
        if not self.enabled:
            return None, "disabled"
        if self._is_down():
            return None, "error"
        try:
            raw = await self._op(self._redis.get(key))
        except Exception as exc:  # noqa: BLE001 - Redis nunca debe romper la petición
            self._mark_down("get", exc)
            return None, "error"
        if raw is None:
            logger.info("cache_miss", extra={"cache_key": _short(key)})
            return None, "miss"
        try:
            entry = CachedCompletion.from_json(raw)
        except ValueError as exc:
            logger.warning("cache_corrupt_entry", extra={"cache_key": _short(key), "reason": str(exc)})
            await self._delete_quietly(key)
            return None, "miss"
        logger.info("cache_hit", extra={"cache_key": _short(key)})
        return entry, "hit"

    async def set(self, key: str, entry: CachedCompletion) -> bool:
        if not self.enabled or self._is_down():
            return False
        try:
            await self._op(self._redis.set(key, entry.to_json(), ex=self.ttl_seconds))
        except Exception as exc:  # noqa: BLE001
            self._mark_down("set", exc)
            return False
        logger.info("cache_store", extra={"cache_key": _short(key), "ttl_s": self.ttl_seconds})
        return True

    async def ping(self) -> bool | None:
        """True/False si Redis responde; None si la caché está desactivada."""
        if not self.enabled:
            return None
        try:
            await self._op(self._redis.ping())
            return True
        except Exception as exc:  # noqa: BLE001
            self._mark_down("ping", exc)
            return False

    async def aclose(self) -> None:
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:  # noqa: BLE001
                logger.debug("redis close failed")

    # --- internos -------------------------------------------------------------

    async def _op(self, awaitable: Awaitable[T]) -> T:
        return await asyncio.wait_for(awaitable, timeout=self._timeout)

    async def _delete_quietly(self, key: str) -> None:
        try:
            await self._op(self._redis.delete(key))
        except Exception:  # noqa: BLE001
            pass

    def _is_down(self) -> bool:
        return self._clock() < self._down_until

    def _mark_down(self, op: str, exc: Exception) -> None:
        self._down_until = self._clock() + self._retry_after
        # Solo el tipo de excepción: la URL de Redis podría incluir credenciales.
        logger.warning(
            "cache_error",
            extra={"op": op, "error_type": type(exc).__name__, "retry_after_s": self._retry_after},
        )


def _short(key: str) -> str:
    return key.rsplit(":", 1)[-1][:12]
