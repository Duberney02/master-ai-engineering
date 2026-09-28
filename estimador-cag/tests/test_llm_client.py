"""Wrapper LLM: reintentos, fallback, timeout, caché, deduplicación y streaming."""

import asyncio

import pytest

from app.cache.result_cache import ResultCache
from app.llm.client import LLMClient
from app.llm.errors import (
    LLMAuthError,
    LLMEmptyResponseError,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMStreamInterruptedError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.pricing import PricingTable
from app.llm.routing import ModelRef, ModelRoute
from app.llm.types import LLMRequest, StreamDelta
from tests._fakes import FakeProvider, FakeRedis, StreamScript, completion

REQ = LLMRequest(system="Sistema", user="Transcripción", max_tokens=500, purpose="estimation")
PRIMARY = ModelRef("openai", "gpt-4o-mini")
SECONDARY = ModelRef("anthropic", "claude-haiku-4-5")
ROUTE = ModelRoute((PRIMARY, SECONDARY))
ONLY_PRIMARY = ModelRoute((PRIMARY,))


def _client(openai=None, anthropic=None, *, redis=None, retries=2, timeout=5.0, sleeps=None,
            inflight_wait=5.0):
    providers = {}
    if openai is not None:
        providers["openai"] = openai
    if anthropic is not None:
        providers["anthropic"] = anthropic
    cache = ResultCache(redis, enabled=redis is not None, ttl_seconds=60)

    async def sleep(seconds):
        if sleeps is not None:
            sleeps.append(seconds)

    return LLMClient(providers, cache, PricingTable(), timeout=timeout, max_retries=retries,
                     backoff=0.5, inflight_wait=inflight_wait, sleep=sleep)


async def _stream(client, request=REQ, route=ROUTE):
    deltas, final = [], None
    async for event in client.stream(request, route):
        if isinstance(event, StreamDelta):
            deltas.append(event.text)
        else:
            final = event.result
    return deltas, final


# --------------------------------------------------------------------------- fallback


async def test_primary_is_tried_first_and_used_when_it_works():
    primary = FakeProvider("openai", [completion("ok")])
    secondary = FakeProvider("anthropic", [])
    result = await _client(primary, secondary).complete(REQ, ROUTE)
    assert result.provider == "openai" and not result.fallback_used
    assert secondary.calls == []


@pytest.mark.parametrize("error", [LLMUnavailableError(), LLMRateLimitError(), LLMTimeoutError()])
async def test_retryable_errors_are_retried_then_fall_back(error):
    sleeps: list[float] = []
    primary = FakeProvider("openai", [error, error, error])
    secondary = FakeProvider("anthropic", [completion("respaldo", model="claude-haiku-4-5")])
    result = await _client(primary, secondary, retries=2, sleeps=sleeps).complete(REQ, ROUTE)

    assert len(primary.calls) == 3  # 1 intento + 2 reintentos, en orden
    assert [c[0] for c in secondary.calls] == ["claude-haiku-4-5"]
    assert sleeps == [0.5, 1.0]  # backoff exponencial acotado
    assert result.fallback_used and result.provider == "anthropic"
    assert result.model == "claude-haiku-4-5" and result.attempts == 4


@pytest.mark.parametrize("error", [LLMAuthError(), LLMEmptyResponseError()])
async def test_non_retryable_errors_go_straight_to_fallback(error):
    primary = FakeProvider("openai", [error])
    secondary = FakeProvider("anthropic", [completion("ok", model="claude-haiku-4-5")])
    result = await _client(primary, secondary).complete(REQ, ROUTE)
    assert len(primary.calls) == 1 and result.fallback_used


async def test_invalid_request_neither_retries_nor_falls_back():
    primary = FakeProvider("openai", [LLMInvalidRequestError()])
    secondary = FakeProvider("anthropic", [])
    with pytest.raises(LLMInvalidRequestError):
        await _client(primary, secondary).complete(REQ, ROUTE)
    assert len(primary.calls) == 1 and secondary.calls == []


async def test_single_candidate_route_never_uses_another_model():
    primary = FakeProvider("openai", [LLMUnavailableError()] * 3)
    secondary = FakeProvider("anthropic", [])
    with pytest.raises(LLMUnavailableError):
        await _client(primary, secondary).complete(REQ, ONLY_PRIMARY)
    assert secondary.calls == []


async def test_timeout_is_enforced_per_attempt():
    slow = FakeProvider("openai", [completion("tarde")] * 2, delay=0.5)
    with pytest.raises(LLMTimeoutError):
        await _client(slow, retries=1, timeout=0.05).complete(REQ, ONLY_PRIMARY)
    assert len(slow.calls) == 2


async def test_unexpected_provider_exception_is_wrapped_and_sanitised():
    primary = FakeProvider("openai", [RuntimeError("sk-secret /srv/internal")])
    with pytest.raises(Exception) as exc:
        await _client(primary).complete(REQ, ONLY_PRIMARY)
    assert "sk-secret" not in str(exc.value)


# --------------------------------------------------------------------------- streaming


async def test_stream_falls_back_before_first_token():
    primary = FakeProvider("openai", [LLMUnavailableError()] * 3)
    secondary = FakeProvider("anthropic", [StreamScript(["Hola ", "mundo"], model="claude-haiku-4-5",
                                                        finish_reason="end_turn")])
    deltas, final = await _stream(_client(primary, secondary))
    assert deltas == ["Hola ", "mundo"]
    assert final.fallback_used and final.provider == "anthropic"


async def test_stream_never_switches_provider_after_content():
    primary = FakeProvider("openai", [StreamScript(["Parcial"], error=LLMUnavailableError(), error_after=1)])
    secondary = FakeProvider("anthropic", [])
    with pytest.raises(LLMStreamInterruptedError):
        await _stream(_client(primary, secondary))
    assert secondary.calls == [] and len(primary.calls) == 1


async def test_stream_idle_timeout_after_content_interrupts():
    hanging = FakeProvider("openai", [StreamScript(["a", "b"], delays=[0.0, 0.5])])
    with pytest.raises(LLMStreamInterruptedError) as exc:
        await _stream(_client(hanging, retries=2, timeout=0.1), route=ONLY_PRIMARY)
    assert isinstance(exc.value.cause, LLMTimeoutError)
    assert len(hanging.calls) == 1


async def test_stream_timeout_before_content_is_a_timeout():
    slow = FakeProvider("openai", [StreamScript(["a"], delay=0.3)])
    with pytest.raises(LLMTimeoutError):
        await _stream(_client(slow, retries=0, timeout=0.05), route=ONLY_PRIMARY)


async def test_stream_keeps_real_metadata_and_unknown_values():
    provider = FakeProvider("openai", [StreamScript(["x"], model="gpt-4o-mini-2024-07-18",
                                                    finish_reason="unknown", input_tokens=None,
                                                    output_tokens=None)])
    _, final = await _stream(_client(provider), route=ONLY_PRIMARY)
    assert final.model == "gpt-4o-mini-2024-07-18" and final.requested_model == "gpt-4o-mini"
    assert final.finish_reason == "unknown"
    assert final.input_tokens is None and final.total_tokens is None
    assert final.original_cost_usd is None and final.incurred_cost_usd is None


# --------------------------------------------------------------------------- caché


async def test_identical_request_is_served_from_cache_without_calling_the_provider():
    redis = FakeRedis()
    provider = FakeProvider("openai", [completion("## Estimación", input_tokens=1000, output_tokens=500)])
    client = _client(provider, redis=redis)

    first = await client.complete(REQ, ONLY_PRIMARY)
    second = await client.complete(REQ, ONLY_PRIMARY)

    assert len(provider.calls) == 1
    assert first.cache_status == "miss" and second.cache_status == "hit"
    assert second.text == first.text and second.model == first.model
    assert (second.input_tokens, second.output_tokens) == (1000, 500)  # tokens originales
    assert second.original_cost_usd == first.original_cost_usd == pytest.approx(0.00045)
    assert second.incurred_cost_usd == 0.0  # no se atribuye el coste histórico
    assert second.attempts == 0
    assert second.original_latency_ms == first.latency_ms
    assert redis.set_calls[0][1] == 60  # TTL configurado


@pytest.mark.parametrize("finish_reason", ["length", "max_tokens", "unknown", "content_filter"])
async def test_incomplete_results_are_not_cached(finish_reason):
    redis = FakeRedis()
    provider = FakeProvider("openai", [completion("x", finish_reason=finish_reason)] * 2)
    client = _client(provider, redis=redis)
    await client.complete(REQ, ONLY_PRIMARY)
    again = await client.complete(REQ, ONLY_PRIMARY)
    assert redis.store == {} and len(provider.calls) == 2 and again.cache_status == "miss"


async def test_failed_generation_is_not_cached():
    redis = FakeRedis()
    provider = FakeProvider("openai", [LLMInvalidRequestError()])
    with pytest.raises(LLMInvalidRequestError):
        await _client(provider, redis=redis).complete(REQ, ONLY_PRIMARY)
    assert redis.store == {}


async def test_interrupted_stream_leaves_no_cache_entry():
    redis = FakeRedis()
    provider = FakeProvider("openai", [StreamScript(["uno ", "dos ", "tres"], delay=0.01)])
    client = _client(provider, redis=redis)
    stream = client.stream(REQ, ONLY_PRIMARY)
    first = await anext(stream)
    assert isinstance(first, StreamDelta)
    await stream.aclose()  # el cliente se desconecta a mitad
    assert redis.store == {}
    assert provider.stream_closed == 1  # se libera el stream del proveedor


async def test_stream_provider_error_after_content_leaves_no_cache_entry():
    redis = FakeRedis()
    provider = FakeProvider("openai", [StreamScript(["a"], error=LLMUnavailableError(), error_after=1)])
    with pytest.raises(LLMStreamInterruptedError):
        await _stream(_client(provider, redis=redis), route=ONLY_PRIMARY)
    assert redis.store == {}


async def test_stream_then_complete_share_cache_with_identical_metadata():
    redis = FakeRedis()
    provider = FakeProvider("openai", [StreamScript(["## Est", "imación"], model="gpt-4o-mini-2024-07-18",
                                                    input_tokens=700, output_tokens=300)])
    client = _client(provider, redis=redis)
    _, streamed = await _stream(client, route=ONLY_PRIMARY)
    reused = await client.complete(REQ, ONLY_PRIMARY)

    assert len(provider.calls) == 1
    assert reused.cache_status == "hit" and reused.text == streamed.text == "## Estimación"
    for attr in ("model", "provider", "requested_model", "finish_reason", "input_tokens",
                 "output_tokens", "original_cost_usd", "fallback_used"):
        assert getattr(reused, attr) == getattr(streamed, attr), attr


async def test_complete_then_stream_replays_cache_with_same_contract():
    redis = FakeRedis()
    provider = FakeProvider("openai", [completion("## Estimación\n\nlínea 2")])
    client = _client(provider, redis=redis)
    original = await client.complete(REQ, ONLY_PRIMARY)
    deltas, final = await _stream(client, route=ONLY_PRIMARY)
    assert "".join(deltas) == original.text
    assert final.cache_status == "hit" and final.incurred_cost_usd == 0.0
    assert len(provider.calls) == 1


async def test_fallback_result_is_cached_with_real_model():
    redis = FakeRedis()
    primary = FakeProvider("openai", [LLMAuthError()])
    secondary = FakeProvider("anthropic", [completion("ok", model="claude-haiku-4-5", finish_reason="end_turn")])
    client = _client(primary, secondary, redis=redis)
    await client.complete(REQ, ROUTE)
    hit = await client.complete(REQ, ROUTE)
    assert hit.cache_status == "hit" and hit.provider == "anthropic" and hit.fallback_used


async def test_redis_down_degrades_to_provider_calls():
    redis = FakeRedis()
    redis.fail = ConnectionError("redis://user:pass@host down")
    provider = FakeProvider("openai", [completion("a"), completion("b")])
    client = _client(provider, redis=redis)
    first = await client.complete(REQ, ONLY_PRIMARY)
    second = await client.complete(REQ, ONLY_PRIMARY)
    assert first.cache_status == "error" and second.cache_status == "error"
    assert len(provider.calls) == 2


# --------------------------------------------------------------------------- concurrencia


async def test_identical_concurrent_requests_call_the_provider_once():
    provider = FakeProvider("openai", [completion("único")], delay=0.1)
    client = _client(provider, redis=FakeRedis())
    results = await asyncio.gather(*(client.complete(REQ, ONLY_PRIMARY) for _ in range(5)))
    assert len(provider.calls) == 1
    statuses = sorted(r.cache_status for r in results)
    assert statuses == ["miss", "shared", "shared", "shared", "shared"]
    leader = next(r for r in results if r.cache_status == "miss")
    assert leader.incurred_cost_usd == leader.original_cost_usd
    for r in results:
        if r.cache_status == "shared":
            assert r.incurred_cost_usd == 0.0 and r.original_cost_usd == leader.original_cost_usd


async def test_concurrent_stream_and_complete_are_deduplicated_without_cache():
    provider = FakeProvider("openai", [StreamScript(["a", "b"], delay=0.05)])
    client = _client(provider)  # sin Redis: la deduplicación no depende de la caché
    (deltas, streamed), completed = await asyncio.gather(
        _stream(client, route=ONLY_PRIMARY), client.complete(REQ, ONLY_PRIMARY)
    )
    assert len(provider.calls) == 1
    assert completed.cache_status == "shared" and completed.text == streamed.text == "ab"


async def test_follower_generates_on_its_own_if_the_leader_fails():
    provider = FakeProvider("openai", [LLMInvalidRequestError(), completion("segundo")], delay=0.05)
    client = _client(provider)
    results = await asyncio.gather(
        client.complete(REQ, ONLY_PRIMARY), client.complete(REQ, ONLY_PRIMARY),
        return_exceptions=True,
    )
    assert isinstance(results[0], LLMInvalidRequestError)
    assert results[1].text == "segundo" and results[1].cache_status == "disabled"


async def test_follower_wait_is_bounded():
    provider = FakeProvider("openai", [completion("lento"), completion("rápido")], delay=0.3)
    client = _client(provider, inflight_wait=0.05)
    leader = asyncio.create_task(client.complete(REQ, ONLY_PRIMARY))
    await asyncio.sleep(0.01)
    follower = await client.complete(REQ, ONLY_PRIMARY)  # no espera al líder indefinidamente
    await leader
    assert len(provider.calls) == 2 and follower.cache_status == "disabled"


async def test_providers_are_closed_on_shutdown():
    provider = FakeProvider("openai", [])
    await _client(provider).aclose()
    assert provider.closed
