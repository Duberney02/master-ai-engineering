"""Servicio de caché: claves deterministas, TTL, Redis caído/lento y datos corruptos."""

import asyncio
import json
import re
from datetime import datetime, timezone

import pytest

from app.cache.result_cache import CACHE_SCHEMA_VERSION, CachedCompletion, ResultCache
from app.llm.client import LLMClient
from app.llm.pricing import PricingTable
from app.llm.routing import ModelRef, ModelRoute
from app.llm.types import LLMRequest
from app.services.estimation_service import EstimationService, GenerationOptions
from app.services.prompts import build_system_prompt
from tests._fakes import FakeProvider, FakeRedis

ENTRY = CachedCompletion(
    text="## Estimación", provider="openai", model="gpt-4o-mini", requested_model="gpt-4o-mini",
    finish_reason="stop", input_tokens=10, output_tokens=5, latency_ms=900,
    generated_at=datetime(2026, 9, 1, tzinfo=timezone.utc), original_cost_usd=0.000004,
    fallback_used=False,
)


def _llm_client(**providers) -> LLMClient:
    providers = providers or {"openai": FakeProvider("openai"), "anthropic": FakeProvider("anthropic")}
    return LLMClient(providers, ResultCache(FakeRedis(), prefix="p"), PricingTable())


ROUTE = ModelRoute((ModelRef("openai", "gpt-4o-mini"),))
REQ = LLMRequest(system="S", user="U", max_tokens=100)


# --------------------------------------------------------------------------- claves


def test_key_is_deterministic_prefixed_versioned_and_sha256():
    cache = ResultCache(FakeRedis(), prefix="estimador-cag")
    a = cache.key_for({"b": 1, "a": [1, 2]})
    b = cache.key_for({"a": [1, 2], "b": 1})  # orden de claves irrelevante (serialización canónica)
    assert a == b
    assert re.fullmatch(rf"estimador-cag:v{CACHE_SCHEMA_VERSION}:llm:[0-9a-f]{{64}}", a)


def test_purpose_does_not_affect_the_key():
    client = _llm_client()
    assert client.cache_key(REQ, ROUTE) == client.cache_key(
        LLMRequest(system="S", user="U", max_tokens=100, purpose="otro"), ROUTE
    )


@pytest.mark.parametrize(
    "request_, route",
    [
        (LLMRequest(system="S2", user="U", max_tokens=100), ROUTE),  # prompt
        (LLMRequest(system="S", user="U2", max_tokens=100), ROUTE),  # mensaje
        (LLMRequest(system="S", user="U", max_tokens=101), ROUTE),  # límite de salida
        (LLMRequest(system="S", user="U", max_tokens=None), ROUTE),
        (REQ, ModelRoute((ModelRef("openai", "gpt-4o"),))),  # modelo
        (REQ, ModelRoute((ModelRef("openai", "gpt-4o-mini"), ModelRef("anthropic", "claude-haiku-4-5")))),  # fallback
    ],
)
def test_relevant_changes_produce_different_keys(request_, route):
    client = _llm_client()
    assert client.cache_key(request_, route) != client.cache_key(REQ, ROUTE)


def test_adapter_generation_params_are_part_of_the_key():
    class OtherParams(FakeProvider):
        def generation_params(self):
            return {"temperature": 0.9}

    a = _llm_client(openai=FakeProvider("openai")).cache_key(REQ, ROUTE)
    b = _llm_client(openai=OtherParams("openai")).cache_key(REQ, ROUTE)
    assert a != b


@pytest.mark.parametrize(
    "options",
    [
        GenerationOptions(num_examples=3),
        GenerationOptions(example_format="json"),
        GenerationOptions(use_examples=False),
        GenerationOptions(preprocessing="inline_cleaning"),
        GenerationOptions(max_tokens=900),
    ],
)
def test_prompt_and_example_options_change_the_estimation_key(options):
    client = _llm_client()
    service = EstimationService(llm=client, policy=None)  # type: ignore[arg-type]
    base = service._estimation_request("T" * 30, GenerationOptions(), None)
    changed = service._estimation_request("T" * 30, options, None)
    assert client.cache_key(base, ROUTE) != client.cache_key(changed, ROUTE)


def test_changing_an_example_changes_the_key(monkeypatch):
    import app.context.examples as examples

    client = _llm_client()
    before = client.cache_key(LLMRequest(system=build_system_prompt(), user="U"), ROUTE)
    first = examples.ESTIMATION_EXAMPLES_CATALOG[0]
    import dataclasses

    edited = dataclasses.replace(first, meeting_summary=first.meeting_summary + " (editado)")
    monkeypatch.setattr(examples, "ESTIMATION_EXAMPLES_CATALOG", [edited, *examples.ESTIMATION_EXAMPLES_CATALOG[1:]])
    after = client.cache_key(LLMRequest(system=build_system_prompt(), user="U"), ROUTE)
    assert before != after


# --------------------------------------------------------------------------- lectura/escritura


async def test_roundtrip_with_ttl_and_expiry():
    now = [1000.0]
    redis = FakeRedis(clock=lambda: now[0])
    cache = ResultCache(redis, ttl_seconds=30)
    assert await cache.set("k", ENTRY)
    assert redis.set_calls == [("k", 30)]
    entry, status = await cache.get("k")
    assert status == "hit" and entry == ENTRY
    now[0] += 31  # expira
    assert await cache.get("k") == (None, "miss")


async def test_disabled_cache_never_touches_redis():
    redis = FakeRedis()
    cache = ResultCache(redis, enabled=False)
    assert await cache.get("k") == (None, "disabled")
    assert not await cache.set("k", ENTRY)
    assert redis.get_calls == 0 and redis.set_calls == []
    assert await cache.ping() is None


async def test_redis_errors_are_misses_and_trigger_a_backoff_window():
    now = [0.0]
    redis = FakeRedis()
    redis.fail = ConnectionError("down")
    cache = ResultCache(redis, retry_after=10, clock=lambda: now[0])
    assert await cache.get("k") == (None, "error")
    assert await cache.get("k") == (None, "error")
    assert redis.get_calls == 1  # durante la ventana no se vuelve a consultar
    assert not await cache.set("k", ENTRY)
    redis.fail = None
    now[0] = 11
    assert await cache.get("k") == (None, "miss")  # se recupera solo


async def test_slow_redis_is_bounded_by_timeout():
    redis = FakeRedis()
    redis.delay = 1.0
    cache = ResultCache(redis, op_timeout=0.05)
    start = asyncio.get_running_loop().time()
    assert await cache.get("k") == (None, "error")
    assert asyncio.get_running_loop().time() - start < 0.5


@pytest.mark.parametrize(
    "raw",
    [
        "{no es json",
        json.dumps({"schema": CACHE_SCHEMA_VERSION + 1, "text": "x"}),  # versión incompatible
        json.dumps({"schema": CACHE_SCHEMA_VERSION, "text": "x"}),  # campos ausentes
        json.loads(ENTRY.to_json()) | {"input_tokens": "diez"},  # tipos erróneos
        json.loads(ENTRY.to_json()) | {"text": "   "},  # vacía
        b"\xff\xfe",
    ],
)
async def test_corrupt_or_incompatible_entries_are_misses_and_deleted(raw):
    redis = FakeRedis()
    value = json.dumps(raw) if isinstance(raw, dict) else raw
    redis.store["k"] = (value.decode("latin-1") if isinstance(value, bytes) else value, None)
    if isinstance(raw, bytes):
        async def get_bytes(name):
            return raw
        redis.get = get_bytes
    cache = ResultCache(redis)
    assert await cache.get("k") == (None, "miss")
    if not isinstance(raw, bytes):
        assert "k" not in redis.store


async def test_close_releases_redis():
    redis = FakeRedis()
    await ResultCache(redis).aclose()
    assert redis.closed
