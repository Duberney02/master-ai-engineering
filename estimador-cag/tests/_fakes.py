"""Dobles de prueba: proveedores LLM, Redis, SDK y construcción de apps/servicios.

Ninguna prueba realiza llamadas reales (ni facturables) a proveedores ni a Redis.
"""

import asyncio
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import AppResources, build_resources
from app.llm.errors import LLMError
from app.llm.providers.anthropic_provider import AnthropicAdapter
from app.llm.providers.openai_provider import OpenAIAdapter
from app.llm.types import LLMRequest, ProviderCompletion, ProviderDelta, ProviderStreamEnd
from app.main import create_app

LONG_TRANSCRIPTION = "Transcripción suficientemente larga para ser válida en el test"


# --------------------------------------------------------------------------- ajustes


def openai_settings(**kw) -> Settings:
    kw.setdefault("cache_enabled", False)
    return Settings(llm_provider="openai", openai_api_key="sk-test", _env_file=None, **kw)


def anthropic_settings(**kw) -> Settings:
    kw.setdefault("cache_enabled", False)
    return Settings(llm_provider="anthropic", anthropic_api_key="sk-ant-test", _env_file=None, **kw)


def both_settings(**kw) -> Settings:
    kw.setdefault("cache_enabled", False)
    return Settings(
        llm_provider="openai",
        openai_api_key="sk-test",
        anthropic_api_key="sk-ant-test",
        _env_file=None,
        **kw,
    )


# --------------------------------------------------------------------------- proveedor falso


def completion(
    text: str = "## Estimación: Demo",
    *,
    model: str | None = "gpt-4o-mini",
    finish_reason: str = "stop",
    input_tokens: int | None = 100,
    output_tokens: int | None = 50,
) -> ProviderCompletion:
    return ProviderCompletion(text, model, finish_reason, input_tokens, output_tokens)


class StreamScript:
    """Guion de un stream: deltas, fin (o error tras N deltas) y pausas opcionales."""

    def __init__(
        self,
        deltas: list[str],
        *,
        model: str | None = "gpt-4o-mini",
        finish_reason: str = "stop",
        input_tokens: int | None = 100,
        output_tokens: int | None = 50,
        error: Exception | None = None,
        error_after: int | None = None,
        delay: float = 0.0,
        delays: list[float] | None = None,
        end: bool = True,
    ):
        self.deltas = deltas
        self.end = (
            ProviderStreamEnd(model, finish_reason, input_tokens, output_tokens) if end else None
        )
        self.error = error
        self.error_after = error_after
        self.delay = delay
        self.delays = delays


class FakeProvider:
    """Cumple `ProviderAdapter`. Cada llamada consume el siguiente resultado del guion:
    `ProviderCompletion`/`StreamScript`, una excepción o una corrutina async."""

    def __init__(self, name: str = "openai", outcomes: list | None = None, *, delay: float = 0.0):
        self.name = name
        self.outcomes = list(outcomes or [])
        self.delay = delay
        self.calls: list[tuple[str, LLMRequest, str]] = []
        self.closed = False
        self.stream_closed = 0

    def generation_params(self) -> dict[str, Any]:
        return {"fake": self.name}

    def _next(self):
        if not self.outcomes:
            raise AssertionError(f"FakeProvider[{self.name}] called more times than scripted")
        return self.outcomes.pop(0)

    async def complete(self, model: str, request: LLMRequest) -> ProviderCompletion:
        self.calls.append((model, request, "complete"))
        if self.delay:
            await asyncio.sleep(self.delay)
        outcome = self._next()
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return await outcome()
        if isinstance(outcome, StreamScript):
            text = "".join(outcome.deltas)
            end = outcome.end
            return ProviderCompletion(text, end.model, end.finish_reason, end.input_tokens, end.output_tokens)
        return outcome

    async def stream(self, model: str, request: LLMRequest):
        self.calls.append((model, request, "stream"))
        outcome = self._next()
        try:
            if isinstance(outcome, BaseException):
                raise outcome
            if isinstance(outcome, ProviderCompletion):
                outcome = StreamScript(
                    [outcome.text], model=outcome.model, finish_reason=outcome.finish_reason,
                    input_tokens=outcome.input_tokens, output_tokens=outcome.output_tokens,
                )
            for i, delta in enumerate(outcome.deltas):
                if outcome.error is not None and outcome.error_after == i:
                    raise outcome.error
                pause = outcome.delays[i] if outcome.delays else outcome.delay
                if pause:
                    await asyncio.sleep(pause)
                yield ProviderDelta(delta)
            if outcome.error is not None and outcome.error_after in (None, len(outcome.deltas)):
                raise outcome.error
            if outcome.end is not None:
                yield outcome.end
        finally:
            self.stream_closed += 1

    async def aclose(self) -> None:
        self.closed = True


# --------------------------------------------------------------------------- Redis falso


class FakeRedis:
    """Redis en memoria con TTL simulado y modos de fallo."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self.store: dict[str, tuple[str, float | None]] = {}
        self.clock = clock
        self.fail: Exception | None = None
        self.delay = 0.0
        self.set_calls: list[tuple[str, int | None]] = []
        self.get_calls = 0
        self.closed = False

    async def _maybe_fail(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail is not None:
            raise self.fail

    async def get(self, name: str):
        self.get_calls += 1
        await self._maybe_fail()
        item = self.store.get(name)
        if item is None:
            return None
        value, expires = item
        if expires is not None and self.clock() >= expires:
            del self.store[name]
            return None
        return value.encode("utf-8")

    async def set(self, name: str, value: str, ex: int | None = None):
        await self._maybe_fail()
        self.set_calls.append((name, ex))
        self.store[name] = (value, self.clock() + ex if ex else None)
        return True

    async def delete(self, *names: str):
        await self._maybe_fail()
        for n in names:
            self.store.pop(n, None)
        return len(names)

    async def ping(self):
        await self._maybe_fail()
        return True

    async def aclose(self):
        self.closed = True


# --------------------------------------------------------------------------- composición


async def _no_sleep(_seconds: float) -> None:
    return None


def make_resources(
    settings: Settings,
    providers: dict[str, Any],
    redis: Any = None,
) -> AppResources:
    return build_resources(settings, providers=providers, redis=redis, sleep=_no_sleep)


def make_app(resources: AppResources) -> FastAPI:
    return create_app(
        settings_provider=lambda: resources.settings,
        resources_factory=lambda _s: resources,
    )


def make_client(resources: AppResources) -> TestClient:
    """Úsalo con `with make_client(...) as client:` para activar el lifespan."""
    return TestClient(make_app(resources))


# --------------------------------------------------------------------------- SDK simulados


def openai_response(
    text: str,
    *,
    finish_reason: str | None = "stop",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    model: str = "gpt-4o-mini",
):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish_reason)
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
        model=model,
    )


def anthropic_response(
    text: str,
    *,
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 50,
    model: str = "claude-haiku-4-5",
    extra_blocks: tuple = (),
):
    return SimpleNamespace(
        content=[*extra_blocks, SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason=stop_reason,
        model=model,
    )


def openai_sdk(*outcomes) -> tuple[OpenAIAdapter, AsyncMock]:
    """Adaptador real sobre un SDK simulado; cada llamada consume un resultado."""
    create = AsyncMock(side_effect=list(outcomes))
    client = MagicMock()
    client.chat.completions.create = create
    client.close = AsyncMock()
    return OpenAIAdapter(client), create


def anthropic_sdk(*outcomes) -> tuple[AnthropicAdapter, AsyncMock]:
    create = AsyncMock(side_effect=list(outcomes))
    client = MagicMock()
    client.messages.create = create
    client.close = AsyncMock()
    return AnthropicAdapter(client), create


class _AsyncIterFromList:
    def __init__(self, items: list, error: Exception | None = None):
        self._items = iter(items)
        self._error = error
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            if self._error is not None:
                raise self._error from None
            raise StopAsyncIteration from None

    async def close(self):
        self.closed = True


def openai_stream_chunks(
    deltas: list[str],
    *,
    model: str = "gpt-4o-mini",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    finish_reason: str | None = "stop",
    include_usage: bool = True,
) -> list:
    chunks = [
        SimpleNamespace(
            model=model,
            choices=[SimpleNamespace(delta=SimpleNamespace(content=d), finish_reason=None)],
            usage=None,
        )
        for d in deltas
    ]
    chunks.append(
        SimpleNamespace(
            model=model,
            choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason=finish_reason)],
            usage=None,
        )
    )
    if include_usage:
        chunks.append(
            SimpleNamespace(
                model=model,
                choices=[],
                usage=SimpleNamespace(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                ),
            )
        )
    return chunks


def openai_stream_sdk(chunks: list, error: Exception | None = None):
    stream = _AsyncIterFromList(chunks, error)
    create = AsyncMock(return_value=stream)
    client = MagicMock()
    client.chat.completions.create = create
    client.close = AsyncMock()
    return OpenAIAdapter(client), create, stream


class _FakeAnthropicStream:
    def __init__(self, deltas: list[str], final_message):
        self._deltas = deltas
        self._final_message = final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    @property
    def text_stream(self):
        return _AsyncIterFromList(list(self._deltas))

    async def get_final_message(self):
        return self._final_message


def anthropic_stream_sdk(deltas: list[str], final_message):
    client = MagicMock()
    client.messages.stream = MagicMock(return_value=_FakeAnthropicStream(deltas, final_message))
    client.close = AsyncMock()
    return AnthropicAdapter(client), client


def is_llm_error(exc: BaseException, kind: str) -> bool:
    return isinstance(exc, LLMError) and exc.kind == kind
