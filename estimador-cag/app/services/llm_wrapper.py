"""Políticas comunes; los adaptadores SDK se inyectan y permanecen asíncronos."""

import structlog
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.config import Settings
from app.services.cache import EstimationCache, make_key

logger = structlog.get_logger(__name__)
SUCCESS_REASONS = {"stop", "end_turn", "stop_sequence"}


class ProviderFailure(HTTPException):
    def __init__(self, status_code: int, detail: str, *, retryable: bool = False):
        super().__init__(status_code=status_code, detail=detail)
        self.retryable = retryable


class Completion(BaseModel):
    text: str = ""
    model: str = ""
    provider: str = ""
    finish_reason: str = "unknown"
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    usage_available: bool = True
    latency_ms: int = 0
    cache_hit: bool = False
    estimated_cost_usd: float | None = None
    request_cost_usd: float | None = None


def total_cost(values: list[float | None]) -> float | None:
    return None if any(v is None for v in values) else round(sum(values), 9)


def estimate_cost(settings: Settings, result: Completion) -> float | None:
    price = settings.model_prices.get(result.model)
    if price is None or not result.usage_available:
        return None
    return round((result.input_tokens * price.input + result.output_tokens * price.output) / 1e6, 9)


class LLMWrapper:
    def __init__(self, settings: Settings, cache: EstimationCache | None = None):
        self.settings = settings
        self.cache = cache or EstimationCache(settings)

    def targets(self, model: str, allow_fallback: bool):
        yield self.settings.llm_provider, model
        if allow_fallback and self.settings.fallback_provider:
            yield self.settings.fallback_provider, self.settings.fallback_model

    def key(self, system: str, user: str, model: str, max_tokens: int | None,
            thinking_budget: int | None, allow_fallback: bool) -> str:
        return make_key(
            system=system, user=user, targets=list(self.targets(model, allow_fallback)),
            max_tokens=max_tokens, thinking_budget=thinking_budget,
            temperature=0.3 if self.settings.llm_provider == "openai" else None,
        )

    async def _cached(self, key: str) -> Completion | None:
        raw = await self.cache.get(key)
        if raw is None:
            return None
        try:
            required = {"text", "model", "provider", "finish_reason", "input_tokens",
                        "output_tokens", "usage_available"}
            if not required.issubset(raw):
                return None
            result = Completion.model_validate(raw, strict=True)
            if not self._cacheable(result):
                return None
            result.cache_hit = True
            result.latency_ms = 0
            # Recalculate using the current configured tariff, never a stale cached price.
            result.estimated_cost_usd = estimate_cost(self.settings, result)
            result.request_cost_usd = 0.0
            logger.info("cache_hit", model=result.model, provider=result.provider, cache_hit=True)
            return result
        except (ValidationError, TypeError, ValueError):
            logger.warning("cache_payload_invalid")
            return None

    @staticmethod
    def _cacheable(result: Completion) -> bool:
        return bool(result.text.strip() and result.model and result.provider in {"openai", "anthropic"}
                    and result.finish_reason in SUCCESS_REASONS and result.usage_available)

    async def _finish(self, key: str, result: Completion, started: float) -> Completion:
        result.latency_ms = int((time.monotonic() - started) * 1000)
        result.estimated_cost_usd = estimate_cost(self.settings, result)
        result.request_cost_usd = result.estimated_cost_usd
        if self._cacheable(result):
            await self.cache.set(key, result.model_dump())
        logger.info(
            "llm_completed", provider=result.provider, model=result.model,
            input_tokens=result.input_tokens, output_tokens=result.output_tokens,
            cost_usd=result.request_cost_usd, latency_ms=result.latency_ms,
            finish_reason=result.finish_reason, cache_hit=False,
        )
        return result

    async def complete(self, system: str, user: str, model: str, max_tokens: int | None,
                       thinking_budget: int | None, allow_fallback: bool,
                       call: Callable[[str, str], Awaitable[Completion]]) -> Completion:
        key = self.key(system, user, model, max_tokens, thinking_budget, allow_fallback)
        cached = await self._cached(key)
        if cached is not None:
            return cached
        started = time.monotonic()
        targets = list(self.targets(model, allow_fallback))
        for index, (provider, target_model) in enumerate(targets):
            try:
                result = await call(provider, target_model)
                result.provider = provider
                return await self._finish(key, result, started)
            except ProviderFailure as exc:
                if not exc.retryable or index == len(targets) - 1:
                    raise
                logger.warning("llm_fallback", provider=provider, model=target_model)
        raise RuntimeError("No provider configured")

    async def stream(self, system: str, user: str, model: str, max_tokens: int | None,
                     thinking_budget: int | None, allow_fallback: bool, result: Completion,
                     call: Callable[[str, str, Completion], AsyncIterator[str]]) -> AsyncIterator[str]:
        key = self.key(system, user, model, max_tokens, thinking_budget, allow_fallback)
        cached = await self._cached(key)
        if cached is not None:
            result.__dict__.update(cached.__dict__)
            yield result.text
            return
        started = time.monotonic()
        targets = list(self.targets(model, allow_fallback))
        for index, (provider, target_model) in enumerate(targets):
            attempt = Completion(provider=provider, model=target_model, usage_available=False)
            chunks: list[str] = []
            try:
                async with aclosing(call(provider, target_model, attempt)) as source:
                    async for chunk in source:
                        chunks.append(chunk)
                        yield chunk
                attempt.text = "".join(chunks)
                if not attempt.text.strip():
                    raise ProviderFailure(502, "LLM returned an empty response")
                await self._finish(key, attempt, started)
                result.__dict__.update(attempt.__dict__)
                return
            except ProviderFailure as exc:
                if chunks or not exc.retryable or index == len(targets) - 1:
                    raise
                logger.warning("llm_fallback", provider=provider, model=target_model)
