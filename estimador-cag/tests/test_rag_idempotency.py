"""Almacén de idempotencia: Redis asíncrono (`fakeredis`), memoria con caducidad y degradación ante fallos."""

import fakeredis
import pytest
from fakeredis import FakeAsyncRedis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.dependencies import get_idempotency_store
from app.generation.rag import idempotency as idempotency_module
from app.generation.rag.estimator import insufficient_estimate
from app.generation.rag.idempotency import KEY_PREFIX, IdempotencyStore
from app.generation.rag.schemas import Estimate
from tests._grounded import estimate_payload


@pytest.fixture
def server():
    return fakeredis.FakeServer()


def _redis_store(server, ttl: int = 60) -> IdempotencyStore:
    return IdempotencyStore(ttl=ttl, redis_factory=lambda: FakeAsyncRedis(server=server, decode_responses=True))


async def test_redis_round_trip_with_prefix_and_ttl(server):
    store = _redis_store(server, ttl=120)
    estimate = Estimate.model_validate(estimate_payload())

    await store.set("abc", estimate)

    assert await store.get("abc") == estimate and await store.get("missing") is None
    raw = FakeAsyncRedis(server=server, decode_responses=True)
    assert 0 < await raw.ttl(KEY_PREFIX + "abc") <= 120
    assert store.backend == "redis"


async def test_redis_is_shared_between_store_instances(server):
    await _redis_store(server).set("k", insufficient_estimate())

    assert (await _redis_store(server).get("k")).confidence == "insufficient"


async def test_a_corrupt_entry_is_a_miss(server):
    await FakeAsyncRedis(server=server, decode_responses=True).set(KEY_PREFIX + "bad", "{not json")

    assert await _redis_store(server).get("bad") is None


async def test_memory_store_round_trip_and_expiry(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(idempotency_module.time, "monotonic", lambda: clock["now"])
    store = IdempotencyStore(ttl=10)
    estimate = Estimate.model_validate(estimate_payload())

    await store.set("k", estimate)
    assert await store.get("k") == estimate and store.backend == "memory"

    clock["now"] += 11
    assert await store.get("k") is None


async def test_memory_store_is_bounded(monkeypatch):
    monkeypatch.setattr(idempotency_module, "MEMORY_MAX_ENTRIES", 3)
    store = IdempotencyStore(ttl=60)
    for key in "abcd":
        await store.set(key, insufficient_estimate())

    assert await store.get("a") is None and await store.get("d") is not None


async def test_redis_failures_degrade_to_memory():
    class Broken:
        async def __aenter__(self):
            raise RedisConnectionError("down")

        async def __aexit__(self, *exc):
            return False

    store = IdempotencyStore(ttl=60, redis_factory=Broken)

    await store.set("k", insufficient_estimate())

    assert (await store.get("k")).confidence == "insufficient"


def test_factory_uses_memory_without_redis_url(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)

    assert get_idempotency_store().backend == "memory"
    assert get_idempotency_store() is get_idempotency_store()  # una instancia por proceso


def test_factory_uses_redis_with_redis_url(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    assert get_idempotency_store().backend == "redis"
