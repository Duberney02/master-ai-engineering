"""Caché de completions sobre Redis simulado (FakeRedis): ida y vuelta, serialización y TTL."""

import asyncio
import json

import fakeredis
import pytest
from fakeredis import FakeAsyncRedis

from app.schemas import EstimationRequest, EstimationResult
from app.services.cache import CachedEstimation, EstimationCache, make_key, make_result_key
from app.services.llm_wrapper import Completion, LLMWrapper
from tests._fakes import openai_settings

URL = "redis://fake:6379/0"
PAYLOAD = {
    "text": "Estimación en español: coste ≈ 12 000 € · plazo 8 semanas",
    "model": "gpt-4o-mini",
    "provider": "openai",
    "nested": {"fases": ["Diseño", "Desarrollo"], "ok": True, "n": 3},
}


@pytest.fixture
def server():
    return fakeredis.FakeServer()


@pytest.fixture
def connect(mocker, server):
    """Cada operación de la caché abre (y cierra) su propio cliente: los datos viven en el servidor simulado."""

    def factory(url, **kwargs):
        assert url == URL
        return FakeAsyncRedis(server=server, decode_responses=kwargs.get("decode_responses", False))

    return mocker.patch("app.services.cache.Redis.from_url", side_effect=factory)


@pytest.fixture
def cache(connect):
    return EstimationCache(openai_settings(redis_url=URL, cache_ttl=120))


async def raw(server, key):
    async with FakeAsyncRedis(server=server, decode_responses=True) as client:
        return await client.get(key)


async def ttl(server, key):
    async with FakeAsyncRedis(server=server, decode_responses=True) as client:
        return await client.ttl(key)


# --- Ida y vuelta ---


async def test_set_then_get_returns_the_same_dictionary_including_non_ascii_text(cache):
    await cache.set("k", PAYLOAD)

    assert await cache.get("k") == PAYLOAD


async def test_missing_key_returns_none(cache):
    assert await cache.get("no-existe") is None


async def test_values_are_overwritten_by_a_second_set(cache):
    await cache.set("k", {"v": 1})
    await cache.set("k", {"v": 2})

    assert await cache.get("k") == {"v": 2}


async def test_keys_are_isolated(cache):
    await cache.set("a", {"v": "a"})
    await cache.set("b", {"v": "b"})

    assert await cache.get("a") == {"v": "a"} and await cache.get("b") == {"v": "b"}


async def test_without_redis_url_the_cache_is_disabled_and_never_connects(connect):
    disabled = EstimationCache(openai_settings())

    await disabled.set("k", PAYLOAD)

    assert await disabled.get("k") is None
    connect.assert_not_called()


# --- Serialización ---


async def test_values_are_stored_as_json_text(cache, server):
    await cache.set("k", PAYLOAD)

    assert json.loads(await raw(server, "k")) == PAYLOAD


@pytest.mark.parametrize("stored", ["esto no es json", "{truncado", "[1, 2, 3]", '"texto"', "42", "null", ""])
async def test_corrupt_or_non_object_values_read_as_missing(cache, server, stored):
    async with FakeAsyncRedis(server=server, decode_responses=True) as client:
        await client.set("k", stored)

    assert await cache.get("k") is None


async def test_unserializable_values_are_not_written_and_do_not_raise(cache, server):
    await cache.set("k", {"valor": object()})

    assert await raw(server, "k") is None


async def test_redis_errors_degrade_to_a_miss(mocker):
    from redis.exceptions import ConnectionError as RedisConnectionError

    mocker.patch("app.services.cache.Redis.from_url", side_effect=RedisConnectionError("caído"))
    broken = EstimationCache(openai_settings(redis_url=URL))

    await broken.set("k", {"v": 1})

    assert await broken.get("k") is None


async def test_clients_are_created_with_the_configured_timeouts(connect):
    settings = openai_settings(redis_url=URL, cache_timeout=0.25)

    await EstimationCache(settings).get("k")

    kwargs = connect.call_args.kwargs
    assert kwargs["socket_timeout"] == 0.25 and kwargs["socket_connect_timeout"] == 0.25
    assert kwargs["decode_responses"] is True


# --- TTL ---


async def test_entries_are_written_with_the_configured_ttl(cache, server):
    await cache.set("k", PAYLOAD)

    assert 0 < await ttl(server, "k") <= 120


async def test_ttl_follows_the_setting(connect, server):
    await EstimationCache(openai_settings(redis_url=URL, cache_ttl=3600)).set("k", {"v": 1})

    assert 3500 < await ttl(server, "k") <= 3600


async def test_entries_expire_after_the_ttl(connect, server):
    short = EstimationCache(openai_settings(redis_url=URL, cache_ttl=1))
    await short.set("k", {"v": 1})
    assert await short.get("k") == {"v": 1}

    await asyncio.sleep(1.2)

    assert await short.get("k") is None


# --- Claves y capas superiores ---


def test_keys_are_deterministic_and_depend_on_the_payload():
    assert make_key(a=1, b="x") == make_key(b="x", a=1)
    assert make_key(a=1) != make_key(a=2) and make_key(a="á") != make_key(a="a")
    assert make_key(a=1).startswith("estimation:v1:")


def test_result_keys_depend_on_request_version_provider_and_model():
    request = EstimationRequest(
        description="Aplicación para gestionar pedidos y facturas.",
        project_type="web_saas",
        detail_level="medium",
        output_format="phases_table",
    )
    base = make_result_key(request, "v3", "openai", "gpt-4o-mini")

    assert base == make_result_key(request, "v3", "openai", "gpt-4o-mini") and base.startswith("estimation:v2:")
    assert (
        len(
            {
                base,
                make_result_key(request, "v4", "openai", "gpt-4o-mini"),
                make_result_key(request, "v3", "anthropic", "gpt-4o-mini"),
                make_result_key(request, "v3", "openai", "gpt-4o"),
            }
        )
        == 4
    )


async def test_validated_estimations_survive_a_roundtrip_through_the_cache(cache):
    result = EstimationResult.model_validate(
        {
            "summary": "Proyecto ñandú con tildes: diseño y desarrollo.",
            "confidence_pct": 75,
            "phases": [{"name": "Diseño", "description": "UX", "duration_weeks": 2, "cost_eur": 1000.5}],
            "total_duration_weeks": 2,
            "total_cost_eur": 1000.5,
        }
    )
    await cache.set(
        "k", CachedEstimation(result=result, model="gpt-4o-mini", provider="openai").model_dump(mode="json")
    )

    restored = CachedEstimation.parse(await cache.get("k"))

    assert restored.result == result and restored.model == "gpt-4o-mini"


async def test_wrapper_serves_the_second_identical_call_from_the_cache(connect, server):
    settings = openai_settings(redis_url=URL, cache_ttl=300, model_prices={"gpt-4o-mini": {"input": 1, "output": 2}})
    wrapper = LLMWrapper(settings)
    calls = 0

    async def call(provider, model):
        nonlocal calls
        calls += 1
        return Completion(
            text="Respuesta con ñ",
            model=model,
            provider=provider,
            finish_reason="stop",
            input_tokens=10,
            output_tokens=5,
        )

    first = await wrapper.complete("sys", "usuario", "gpt-4o-mini", None, None, False, call)
    second = await wrapper.complete("sys", "usuario", "gpt-4o-mini", None, None, False, call)

    assert calls == 1 and not first.cache_hit
    assert second.cache_hit and second.text == "Respuesta con ñ" and second.request_cost_usd == 0.0
    key = wrapper.key("sys", "usuario", "gpt-4o-mini", None, None, False)
    assert 0 < await ttl(server, key) <= 300


async def test_wrapper_does_not_cache_responses_the_caller_rejects(connect, server):
    wrapper = LLMWrapper(openai_settings(redis_url=URL))

    async def call(provider, model):
        return Completion(text="mala", model=model, provider=provider, finish_reason="stop", input_tokens=1)

    await wrapper.complete("sys", "u", "gpt-4o-mini", None, None, False, call, accept=lambda text: False)

    assert await raw(server, wrapper.key("sys", "u", "gpt-4o-mini", None, None, False)) is None
