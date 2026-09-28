"""`LLMClient`: interfaz uniforme, tipada y asíncrona para generación normal y streaming.

Responsabilidades: seleccionar el adaptador según el proveedor real de cada modelo,
aplicar timeout por intento, reintentos acotados con backoff exponencial, fallback
ordenado (el primario siempre primero), métricas/costes, caché de coincidencia exacta
y deduplicación de peticiones idénticas concurrentes.

Reglas de streaming:
- Reintentos y fallback solo **antes** del primer fragmento de contenido. Si el
  proveedor falla después, se lanza `LLMStreamInterruptedError` (nunca se mezcla
  la salida de dos intentos o proveedores).
- Solo se escribe en caché cuando el stream termina con un motivo de finalización
  que confirma una respuesta completa; un stream interrumpido no deja entrada.
- Un acierto de caché se emite con el mismo contrato (deltas + `StreamFinal`).
"""

import asyncio
import dataclasses
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import datetime, timezone

from app.cache.result_cache import CachedCompletion, ResultCache
from app.llm.errors import (
    LLMEmptyResponseError,
    LLMError,
    LLMProviderError,
    LLMStreamInterruptedError,
    LLMTimeoutError,
    ModelSelectionError,
)
from app.llm.pricing import PricingTable
from app.llm.providers.base import ProviderAdapter
from app.llm.routing import ModelRef, ModelRoute
from app.llm.types import (
    COMPLETE_FINISH_REASONS,
    CacheStatus,
    LLMRequest,
    LLMResult,
    ProviderCompletion,
    ProviderDelta,
    ProviderStreamEnd,
    StreamDelta,
    StreamFinal,
)

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]
_MAX_BACKOFF_SECONDS = 10.0


class LLMClient:
    def __init__(
        self,
        providers: Mapping[str, ProviderAdapter],
        cache: ResultCache,
        pricing: PricingTable,
        *,
        timeout: float = 60.0,
        max_retries: int = 2,
        backoff: float = 0.5,
        inflight_wait: float = 120.0,
        sleep: Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._providers = dict(providers)
        self._cache = cache
        self._pricing = pricing
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff = backoff
        self._inflight_wait = inflight_wait
        self._sleep = sleep
        self._clock = clock
        self._inflight: dict[str, asyncio.Future[LLMResult | None]] = {}

    @property
    def cache(self) -> ResultCache:
        return self._cache

    @property
    def pricing(self) -> PricingTable:
        return self._pricing

    # ------------------------------------------------------------------ API pública

    def cache_key(self, request: LLMRequest, route: ModelRoute) -> str:
        """Todo lo que afecta a la generación: prompt completo, mensaje, límite de salida,
        política de modelos (candidatos en orden) y parámetros fijos de cada adaptador."""
        self._check_route(route)
        return self._cache.key_for(
            {
                "kind": "completion",
                "system": request.system,
                "user": request.user,
                "max_tokens": request.max_tokens,
                "route": [
                    {
                        "provider": c.provider,
                        "model": c.name,
                        "params": self._providers[c.provider].generation_params(),
                    }
                    for c in route.candidates
                ],
            }
        )

    async def complete(self, request: LLMRequest, route: ModelRoute) -> LLMResult:
        key = self.cache_key(request, route)
        start = self._clock()
        self._log_start(request, route, key, streaming=False)

        shared = await self._join_inflight(key, start)
        if shared is not None:
            self._log_done(request, shared)
            return shared

        future = self._register(key)
        result: LLMResult | None = None
        try:
            entry, status = await self._cache.get(key)
            if entry is not None:
                result = self._from_cache(entry, start)
            else:
                result = await self._complete_with_policy(request, route, status, start)
                await self._maybe_store(key, result)
            self._log_done(request, result)
            return result
        finally:
            self._resolve(key, future, result)

    async def stream(
        self, request: LLMRequest, route: ModelRoute
    ) -> AsyncIterator[StreamDelta | StreamFinal]:
        key = self.cache_key(request, route)
        start = self._clock()
        self._log_start(request, route, key, streaming=True)

        shared = await self._join_inflight(key, start)
        if shared is not None:
            self._log_done(request, shared)
            yield StreamDelta(shared.text)
            yield StreamFinal(shared)
            return

        future = self._register(key)
        result: LLMResult | None = None
        try:
            entry, status = await self._cache.get(key)
            if entry is not None:
                result = self._from_cache(entry, start)
                self._log_done(request, result)
                yield StreamDelta(result.text)
                yield StreamFinal(result)
                return
            source = self._stream_with_policy(request, route, status, start)
            try:
                async for event in source:
                    if isinstance(event, StreamFinal):
                        result = event.result
                        await self._maybe_store(key, result)
                        self._log_done(request, result)
                    yield event
            finally:
                # Cierre explícito: si el consumidor se desconecta, `async for` no cierra
                # el generador interno y el stream del proveedor quedaría abierto.
                await source.aclose()
        finally:
            self._resolve(key, future, result)

    async def aclose(self) -> None:
        for provider in self._providers.values():
            try:
                await provider.aclose()
            except Exception:  # noqa: BLE001 - cierre best-effort
                logger.debug("provider close failed", extra={"provider": provider.name})

    # ------------------------------------------------------------------ política

    async def _complete_with_policy(
        self, request: LLMRequest, route: ModelRoute, lookup: CacheStatus, start: float
    ) -> LLMResult:
        attempts = 0
        last_error: LLMError | None = None
        for index, candidate in enumerate(route.candidates):
            provider = self._providers[candidate.provider]
            for attempt in range(self._max_retries + 1):
                attempts += 1
                try:
                    async with asyncio.timeout(self._timeout):
                        completion = await provider.complete(candidate.name, request)
                    if not completion.text.strip():
                        raise LLMEmptyResponseError(provider=candidate.provider, model=candidate.name)
                except TimeoutError:
                    error: LLMError = LLMTimeoutError(provider=candidate.provider, model=candidate.name)
                except LLMError as exc:
                    error = exc
                except Exception as exc:  # noqa: BLE001 - adaptador/fake inesperado
                    error = LLMProviderError(type(exc).__name__, provider=candidate.provider,
                                             model=candidate.name)
                else:
                    return self._fresh_result(
                        completion, candidate, index, attempts, lookup, start
                    )
                last_error = error
                if not await self._should_retry(error, candidate, attempt, request):
                    break
            if last_error is None or not self._should_fallback(last_error, route, index, request):
                break
        assert last_error is not None
        raise last_error

    async def _stream_with_policy(
        self, request: LLMRequest, route: ModelRoute, lookup: CacheStatus, start: float
    ) -> AsyncIterator[StreamDelta | StreamFinal]:
        attempts = 0
        last_error: LLMError | None = None
        for index, candidate in enumerate(route.candidates):
            provider = self._providers[candidate.provider]
            for attempt in range(self._max_retries + 1):
                attempts += 1
                parts: list[str] = []
                end: ProviderStreamEnd | None = None
                error: LLMError | None = None
                first_token_at: float | None = None
                source = provider.stream(candidate.name, request)
                try:
                    while True:
                        try:
                            async with asyncio.timeout(self._timeout):  # timeout de inactividad
                                event = await anext(source)
                        except StopAsyncIteration:
                            break
                        except TimeoutError:
                            raise LLMTimeoutError(
                                provider=candidate.provider, model=candidate.name
                            ) from None
                        if isinstance(event, ProviderDelta):
                            if event.text:
                                if first_token_at is None:
                                    first_token_at = self._clock()
                                parts.append(event.text)
                                yield StreamDelta(event.text)
                        elif isinstance(event, ProviderStreamEnd):
                            end = event
                except LLMError as exc:
                    error = exc
                except Exception as exc:  # noqa: BLE001
                    error = LLMProviderError(type(exc).__name__, provider=candidate.provider,
                                             model=candidate.name)
                finally:
                    await _aclose_quietly(source)

                text = "".join(parts).strip()
                if error is None and end is None:
                    error = LLMProviderError("stream ended without metadata",
                                             provider=candidate.provider, model=candidate.name)
                if error is None and not text:
                    error = LLMEmptyResponseError(provider=candidate.provider, model=candidate.name)
                if error is None:
                    assert end is not None
                    completion = ProviderCompletion(
                        text=text,
                        model=end.model,
                        finish_reason=end.finish_reason,
                        input_tokens=end.input_tokens,
                        output_tokens=end.output_tokens,
                    )
                    if first_token_at is not None:
                        logger.debug(
                            "llm_first_token",
                            extra={"ttft_ms": _ms(first_token_at - start), "provider": candidate.provider},
                        )
                    yield StreamFinal(
                        self._fresh_result(completion, candidate, index, attempts, lookup, start)
                    )
                    return
                if parts:
                    # Ya se emitió contenido: ni reintento ni fallback.
                    logger.warning(
                        "llm_stream_interrupted",
                        extra={"provider": candidate.provider, "model": candidate.name,
                               "error_kind": error.kind, "emitted_chars": len("".join(parts))},
                    )
                    raise LLMStreamInterruptedError(error)
                last_error = error
                if not await self._should_retry(error, candidate, attempt, request):
                    break
            if last_error is None or not self._should_fallback(last_error, route, index, request):
                break
        assert last_error is not None
        raise last_error

    async def _should_retry(
        self, error: LLMError, candidate: ModelRef, attempt: int, request: LLMRequest
    ) -> bool:
        will_retry = error.retryable and attempt < self._max_retries
        logger.warning(
            "llm_attempt_failed",
            extra={
                "purpose": request.purpose,
                "provider": candidate.provider,
                "model": candidate.name,
                "attempt": attempt + 1,
                "error_kind": error.kind,
                "will_retry": will_retry,
            },
        )
        if will_retry:
            await self._sleep(min(self._backoff * (2**attempt), _MAX_BACKOFF_SECONDS))
        return will_retry

    def _should_fallback(
        self, error: LLMError, route: ModelRoute, index: int, request: LLMRequest
    ) -> bool:
        if index + 1 >= len(route.candidates) or not error.fallback_allowed:
            return False
        logger.warning(
            "llm_fallback",
            extra={
                "purpose": request.purpose,
                "from_model": str(route.candidates[index]),
                "to_model": str(route.candidates[index + 1]),
                "reason": error.kind,
            },
        )
        return True

    # ------------------------------------------------------------------ resultados

    def _fresh_result(
        self,
        completion: ProviderCompletion,
        candidate: ModelRef,
        index: int,
        attempts: int,
        lookup: CacheStatus,
        start: float,
    ) -> LLMResult:
        if completion.model is None:
            logger.warning("llm_model_unreported", extra={"provider": candidate.provider})
        cost = self._pricing.cost(
            candidate.provider, completion.model, completion.input_tokens, completion.output_tokens
        )
        latency = _ms(self._clock() - start)
        return LLMResult(
            text=completion.text.strip(),
            provider=candidate.provider,
            model=completion.model,
            requested_model=candidate.name,
            finish_reason=completion.finish_reason,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            latency_ms=latency,
            cache_status=lookup,
            fallback_used=index > 0,
            attempts=attempts,
            original_cost_usd=cost,
            # Los intentos fallidos se consideran no facturados (ver README, «Costes»).
            incurred_cost_usd=cost,
            generated_at=datetime.now(tz=timezone.utc),
            original_latency_ms=latency,
        )

    def _from_cache(self, entry: CachedCompletion, start: float) -> LLMResult:
        return LLMResult(
            text=entry.text,
            provider=entry.provider,
            model=entry.model,
            requested_model=entry.requested_model,
            finish_reason=entry.finish_reason,
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            latency_ms=_ms(self._clock() - start),
            cache_status="hit",
            fallback_used=entry.fallback_used,
            attempts=0,
            original_cost_usd=entry.original_cost_usd,
            incurred_cost_usd=0.0,
            generated_at=entry.generated_at,
            original_latency_ms=entry.latency_ms,
        )

    async def _maybe_store(self, key: str, result: LLMResult) -> None:
        if result.cache_status != "miss":
            return  # desactivada, Redis caído o resultado reutilizado
        if not result.text.strip() or result.finish_reason not in COMPLETE_FINISH_REASONS:
            logger.info(
                "cache_skip_store",
                extra={"reason": "incomplete_generation", "finish_reason": result.finish_reason},
            )
            return
        await self._cache.set(
            key,
            CachedCompletion(
                text=result.text,
                provider=result.provider,
                model=result.model,
                requested_model=result.requested_model,
                finish_reason=result.finish_reason,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.original_latency_ms or result.latency_ms,
                generated_at=result.generated_at or datetime.now(tz=timezone.utc),
                original_cost_usd=result.original_cost_usd,
                fallback_used=result.fallback_used,
            ),
        )

    # ------------------------------------------------------------------ concurrencia

    def _register(self, key: str) -> "asyncio.Future[LLMResult | None]":
        future: asyncio.Future[LLMResult | None] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        return future

    def _resolve(self, key: str, future: "asyncio.Future[LLMResult | None]", result: LLMResult | None) -> None:
        if not future.done():
            future.set_result(result)
        if self._inflight.get(key) is future:
            del self._inflight[key]

    async def _join_inflight(self, key: str, start: float) -> LLMResult | None:
        """Espera (acotadamente) a una petición idéntica en curso y reutiliza su resultado.
        Si falla, se interrumpe o tarda demasiado, el llamador genera por su cuenta."""
        future = self._inflight.get(key)
        if future is None:
            return None
        logger.info("llm_inflight_join", extra={"cache_key": key.rsplit(":", 1)[-1][:12]})
        try:
            leader = await asyncio.wait_for(asyncio.shield(future), timeout=self._inflight_wait)
        except TimeoutError:
            logger.warning("llm_inflight_wait_timeout", extra={"wait_s": self._inflight_wait})
            return None
        if leader is None:
            return None
        return dataclasses.replace(
            leader,
            cache_status="hit" if leader.cache_status == "hit" else "shared",
            latency_ms=_ms(self._clock() - start),
            attempts=0,
            incurred_cost_usd=0.0,
        )

    # ------------------------------------------------------------------ utilidades

    def _check_route(self, route: ModelRoute) -> None:
        for candidate in route.candidates:
            if candidate.provider not in self._providers:
                raise ModelSelectionError("The provider of the requested model is not configured")

    def _log_start(self, request: LLMRequest, route: ModelRoute, key: str, *, streaming: bool) -> None:
        logger.info(
            "llm_call_started",
            extra={
                "purpose": request.purpose,
                "route": route.describe(),
                "streaming": streaming,
                "max_tokens": request.max_tokens,
                "cache_key": key.rsplit(":", 1)[-1][:12],
            },
        )

    def _log_done(self, request: LLMRequest, result: LLMResult) -> None:
        logger.info(
            "llm_call_completed",
            extra={
                "purpose": request.purpose,
                "provider": result.provider,
                "model": result.model,
                "requested_model": result.requested_model,
                "cache_status": result.cache_status,
                "fallback_used": result.fallback_used,
                "attempts": result.attempts,
                "finish_reason": result.finish_reason,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "latency_ms": result.latency_ms,
                "incurred_cost_usd": result.incurred_cost_usd,
            },
        )


async def _aclose_quietly(source: AsyncIterator) -> None:
    aclose = getattr(source, "aclose", None)
    if aclose is None:
        return
    try:
        await aclose()
    except Exception:  # noqa: BLE001
        logger.debug("provider stream close failed")


def _ms(seconds: float) -> int:
    return max(0, int(seconds * 1000))
