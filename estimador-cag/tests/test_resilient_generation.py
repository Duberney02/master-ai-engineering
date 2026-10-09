import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from openai import APITimeoutError, AuthenticationError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.services.cache import EstimationCache, make_key
from app.services.llm_service import (
    GenerationOptions,
    StreamMetrics,
    generate_estimation,
    generate_estimation_stream,
    generate_from_prompts,
)
from app.services.llm_wrapper import LLMWrapper
from tests._fakes import (
    LONG_TRANSCRIPTION,
    anthropic_final_message,
    anthropic_response,
    openai_response,
    openai_settings,
    openai_stream_chunks,
    patch_anthropic,
    patch_anthropic_stream,
    patch_openai,
    patch_openai_stream,
    patch_settings,
)


class MemoryCache:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value):
        self.values[key] = value


@pytest.fixture
def memory(mocker):
    cache = MemoryCache()
    mocker.patch("app.services.llm_wrapper.EstimationCache", return_value=cache)
    return cache


def priced(**kwargs):
    return openai_settings(model_prices={"gpt-4o-mini": {"input": 1, "output": 2}}, **kwargs)


async def test_cache_preserves_usage_but_request_cost_is_zero(mocker, memory):
    patch_settings(mocker, priced())
    call = patch_openai(mocker, openai_response("Respuesta", prompt_tokens=1000, completion_tokens=500))
    first = await generate_estimation(LONG_TRANSCRIPTION)
    second = await generate_estimation(LONG_TRANSCRIPTION)
    assert call.await_count == 1
    assert first.estimated_cost_usd == second.estimated_cost_usd == 0.002
    assert first.request_cost_usd == 0.002
    assert second.request_cost_usd == 0
    assert second.cache_hit and second.total_tokens == 1500
    assert second.phases[0].provider == "openai"


async def test_two_phase_partial_cache_cost_and_aggregation(mocker, memory):
    patch_settings(mocker, priced())
    call = patch_openai(mocker, openai_response("Requisitos"), openai_response("Uno"), openai_response("Dos"))
    await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(preprocessing="two_phase"))
    result = await generate_estimation(
        LONG_TRANSCRIPTION, GenerationOptions(preprocessing="two_phase", max_tokens=1200)
    )
    assert call.await_count == 3
    assert result.phases[0].cache_hit and not result.phases[1].cache_hit
    assert result.total_tokens == 300 and not result.cache_hit
    assert result.estimated_cost_usd == 0.0004
    assert result.request_cost_usd == 0.0002


@pytest.mark.parametrize("reason", ["length", "unknown", "content_filter"])
async def test_incomplete_responses_are_not_cached(mocker, memory, reason):
    patch_settings(mocker, priced())
    patch_openai(mocker, openai_response("Incompleta", finish_reason=reason))
    await generate_estimation(LONG_TRANSCRIPTION)
    assert memory.values == {}


async def test_unknown_price_stays_null(mocker, memory):
    patch_settings(mocker, priced())
    patch_openai(mocker, openai_response("Respuesta", model="unknown-model"))
    result = await generate_estimation(LONG_TRANSCRIPTION)
    assert result.estimated_cost_usd is None and result.request_cost_usd is None
    cached = await generate_estimation(LONG_TRANSCRIPTION)
    assert cached.estimated_cost_usd is None and cached.request_cost_usd == 0


def test_keys_include_all_inputs_and_fallback_policy():
    wrapper = LLMWrapper(priced())
    base = ["system", "user", "model", 1000, None, True]
    key = wrapper.key(*base)
    for position, value in enumerate(["system2", "user2", "model2", 2000, 2048]):
        changed = base.copy()
        changed[position] = value
        assert wrapper.key(*changed) != key
    fallback = LLMWrapper(priced(anthropic_api_key="test", fallback_provider="anthropic", fallback_model="claude"))
    assert fallback.key(*base) != key
    assert fallback.key(*base[:-1], False) == key
    assert LONG_TRANSCRIPTION not in make_key(user=LONG_TRANSCRIPTION)


async def test_corrupt_payload_is_a_miss(mocker, memory):
    patch_settings(mocker, priced())
    call = patch_openai(mocker, openai_response("Uno"), openai_response("Dos"))
    await generate_estimation(LONG_TRANSCRIPTION)
    key = next(iter(memory.values))
    memory.values[key] = {"text": "bad"}
    assert (await generate_estimation(LONG_TRANSCRIPTION)).estimation == "Dos"
    assert call.await_count == 2


async def test_redis_failure_and_invalid_json_are_fail_open(mocker):
    cache = EstimationCache(priced(redis_url="redis://unused"))
    client = AsyncMock()
    client.__aenter__.return_value = client
    mocker.patch.object(cache, "_client", return_value=client)
    client.get.side_effect = RedisConnectionError("private password")
    client.setex.side_effect = RedisConnectionError("private password")
    assert await cache.get("key") is None
    await cache.set("key", {"ok": True})
    client.get.side_effect = None
    client.get.return_value = "not json"
    assert await cache.get("key") is None


async def test_redis_ttl_is_applied_and_expiry_is_a_miss(mocker):
    cache = EstimationCache(priced(redis_url="redis://unused", cache_ttl=2))
    client = AsyncMock()
    client.__aenter__.return_value = client
    mocker.patch.object(cache, "_client", return_value=client)
    await cache.set("key", {"answer": 1})
    client.setex.assert_awaited_once_with("key", 2, json.dumps({"answer": 1}))
    client.get.side_effect = [json.dumps({"answer": 1}), None]
    assert await cache.get("key") == {"answer": 1}
    assert await cache.get("key") is None


def fallback_settings():
    return priced(
        anthropic_api_key="test", fallback_provider="anthropic", fallback_model="claude-haiku-4-5", llm_retries=0
    )


async def test_timeout_invokes_real_alternate_adapter(mocker):
    patch_settings(mocker, fallback_settings())
    primary = patch_openai(mocker, APITimeoutError(request=httpx.Request("POST", "https://example.test")))
    alternate = patch_anthropic(mocker, anthropic_response("Recuperada", input_tokens=123, output_tokens=12))
    result = await generate_estimation(LONG_TRANSCRIPTION)
    assert primary.await_count == alternate.await_count == 1
    assert result.provider == "anthropic" and result.total_tokens == 135
    assert result.phases[0].provider == "anthropic"


@pytest.mark.parametrize("explicit", [True, False])
async def test_no_fallback_for_override_or_auth_failure(mocker, explicit):
    patch_settings(mocker, fallback_settings())
    req = httpx.Request("POST", "https://example.test")
    error = (
        APITimeoutError(request=req)
        if explicit
        else AuthenticationError("secret", response=httpx.Response(401, request=req), body={})
    )
    patch_openai(mocker, error)
    alternate = patch_anthropic(mocker, anthropic_response("No debe ocurrir"))
    with pytest.raises(HTTPException):
        await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(model="gpt-4o-mini" if explicit else None))
    alternate.assert_not_awaited()


async def test_stream_cache_reused_by_normal_response_preserves_finish_and_tokens(mocker, memory):
    patch_settings(mocker, priced())
    call = patch_openai_stream(mocker, openai_stream_chunks(["Hola\n", "mundo"]))
    metrics = StreamMetrics()
    assert "".join([x async for x in generate_estimation_stream(LONG_TRANSCRIPTION, metrics)]) == "Hola\nmundo"
    result = await generate_estimation(LONG_TRANSCRIPTION)
    assert call.await_count == 1
    assert result.cache_hit and result.total_tokens == 150 and result.finish_reason == "stop"
    assert result.estimated_cost_usd == 0.0002 and result.request_cost_usd == 0


async def test_stream_failure_after_text_never_falls_back_or_caches(mocker, memory):
    patch_settings(mocker, fallback_settings())
    chunks = openai_stream_chunks(["Parcial"])

    async def broken():
        yield chunks[0]
        raise APITimeoutError(request=httpx.Request("POST", "https://example.test"))

    call = patch_openai_stream(mocker, [])
    call.return_value = broken()
    alternate = patch_anthropic_stream(mocker, ["No mezclar"], anthropic_final_message("No mezclar"))
    with pytest.raises(HTTPException):
        async for _ in generate_estimation_stream(LONG_TRANSCRIPTION, StreamMetrics()):
            pass
    alternate.messages.stream.assert_not_called()
    assert memory.values == {}


async def test_stream_fallback_before_text(mocker):
    patch_settings(mocker, fallback_settings())
    call = patch_openai_stream(mocker, [])
    call.side_effect = APITimeoutError(request=httpx.Request("POST", "https://example.test"))
    patch_anthropic_stream(mocker, ["Recuperada"], anthropic_final_message("Recuperada"))
    metrics = StreamMetrics()
    assert [x async for x in generate_estimation_stream(LONG_TRANSCRIPTION, metrics)] == ["Recuperada"]
    assert metrics.result.provider == "anthropic"


async def test_generator_close_releases_provider_and_does_not_cache(mocker, memory):
    patch_settings(mocker, priced())
    closed = asyncio.Event()

    async def source():
        try:
            yield openai_stream_chunks(["partial"])[0]
        finally:
            closed.set()

    provider_stream = source()

    # OpenAI AsyncStream.close is explicit; model it instead of relying on GC.
    class Stream:
        def __aiter__(self):
            return provider_stream

        async def close(self):
            await provider_stream.aclose()

    call = patch_openai_stream(mocker, [])
    call.return_value = Stream()
    stream = generate_estimation_stream(LONG_TRANSCRIPTION, StreamMetrics())
    assert await anext(stream) == "partial"
    await stream.aclose()
    assert closed.is_set() and memory.values == {}


async def test_stream_task_cancellation_closes_sdk_and_does_not_cache(mocker, memory):
    patch_settings(mocker, priced())
    started, closed = asyncio.Event(), asyncio.Event()

    class Stream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            started.set()
            await asyncio.Event().wait()

        async def close(self):
            closed.set()

    call = patch_openai_stream(mocker, [])
    call.return_value = Stream()

    async def consume():
        async for _ in generate_estimation_stream(LONG_TRANSCRIPTION, StreamMetrics()):
            pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set() and not memory.values


async def test_cached_normal_response_can_be_streamed(mocker, memory):
    patch_settings(mocker, priced())
    call = patch_openai(mocker, openai_response("Texto\ncompleto"))
    first = await generate_estimation(LONG_TRANSCRIPTION)
    metrics = StreamMetrics()
    assert [x async for x in generate_estimation_stream(LONG_TRANSCRIPTION, metrics)] == [first.estimation]
    assert call.await_count == 1 and metrics.result.cache_hit


async def test_stream_truncation_and_missing_usage_are_not_cached(mocker, memory):
    patch_settings(mocker, priced())
    chunks = openai_stream_chunks(["Truncado"])
    chunks[-2].choices[0].finish_reason = "length"
    patch_openai_stream(mocker, chunks)
    metrics = StreamMetrics()
    async for _ in generate_estimation_stream(LONG_TRANSCRIPTION, metrics):
        pass
    assert metrics.result.finish_reason == "length" and not memory.values
    patch_openai_stream(mocker, openai_stream_chunks(["Sin consumo"])[:-1])
    async for _ in generate_estimation_stream(LONG_TRANSCRIPTION, metrics):
        pass
    assert not metrics.result.phases[0].usage_available
    assert metrics.result.estimated_cost_usd is None and not memory.values


async def test_sdk_timeout_retries_and_close_are_configured(mocker):
    patch_settings(mocker, priced(llm_timeout=12, llm_retries=1))
    patch_openai(mocker, openai_response("Respuesta"))
    from app.services import llm_service

    llm_service.AsyncOpenAI.return_value.close = AsyncMock()
    await generate_estimation(LONG_TRANSCRIPTION)
    assert llm_service.AsyncOpenAI.call_args.kwargs["timeout"] == 12
    assert llm_service.AsyncOpenAI.call_args.kwargs["max_retries"] == 1
    llm_service.AsyncOpenAI.return_value.close.assert_awaited_once()


# --- Validar antes de cachear: solo se guardan las respuestas que el llamador acepta ---


def _accept_only_good(text: str) -> bool:
    return text == "buena"


async def test_unaccepted_response_is_returned_but_not_cached(mocker, memory):
    patch_settings(mocker, priced())
    call = patch_openai(mocker, openai_response("mala"), openai_response("buena"))

    first = await generate_from_prompts("sys", "usr", accept=_accept_only_good)
    assert first.text == "mala" and memory.values == {}

    second = await generate_from_prompts("sys", "usr", accept=_accept_only_good)
    assert second.text == "buena" and not second.cache_hit
    assert call.await_count == 2
    assert len(memory.values) == 1


async def test_cached_entry_that_is_no_longer_acceptable_is_ignored_and_replaced(mocker, memory):
    patch_settings(mocker, priced())
    call = patch_openai(mocker, openai_response("mala"), openai_response("buena"))
    await generate_from_prompts("sys", "usr")  # sin criterio: la respuesta mala queda cacheada
    (key,) = memory.values
    assert memory.values[key]["text"] == "mala"

    result = await generate_from_prompts("sys", "usr", accept=_accept_only_good)

    assert result.text == "buena" and not result.cache_hit
    assert call.await_count == 2
    assert memory.values[key]["text"] == "buena"


async def test_accepted_response_is_cached_and_served_from_cache(mocker, memory):
    patch_settings(mocker, priced())
    call = patch_openai(mocker, openai_response("buena"))

    await generate_from_prompts("sys", "usr", accept=_accept_only_good)
    second = await generate_from_prompts("sys", "usr", accept=_accept_only_good)

    assert second.cache_hit and second.text == "buena"
    assert call.await_count == 1


async def test_failing_accept_callback_counts_as_not_acceptable(mocker, memory):
    patch_settings(mocker, priced())
    patch_openai(mocker, openai_response("buena"))

    def broken(text):
        raise RuntimeError("fallo del criterio")

    result = await generate_from_prompts("sys", "usr", accept=broken)

    assert result.text == "buena" and memory.values == {}
