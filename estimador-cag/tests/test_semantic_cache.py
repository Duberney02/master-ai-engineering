import math
from unittest.mock import AsyncMock

import pytest

from app.schemas import EstimationRequest, EstimationResult
from app.services import semantic_cache
from app.services.cache import CachedEstimation
from app.services.semantic_cache import SemanticCache, attributes, index_name, semantic_text
from tests._fakes import anthropic_settings, openai_settings

RESULT = EstimationResult(
    summary="Proyecto pequeño.", confidence_pct=80, total_duration_weeks=4, total_cost_eur=8000,
    phases=[{"name": "Desarrollo", "duration_weeks": 4, "cost_eur": 8000}],
)
ENTRY = CachedEstimation(result=RESULT, model="gpt-4o-mini", provider="openai")
BASE = {
    "description": "Aplicación móvil para que los vecinos reporten incidencias urbanas.",
    "project_type": "mobile_app", "detail_level": "medium", "output_format": "phases_table",
}


def _request(**overrides) -> EstimationRequest:
    return EstimationRequest(**{**BASE, **overrides})


class FakeRedisvl:
    """Imita `SemanticCache` de redisvl: distancia coseno, umbral y filtro por igualdad de tags."""

    def __init__(self):
        self.entries = []
        self.checks = []

    async def acheck(self, vector, num_results, filter_expression, distance_threshold):
        self.checks.append((filter_expression, distance_threshold))
        hits = []
        for entry in self.entries:
            if any(entry["filters"][k] != v for k, v in filter_expression.items()):
                continue
            distance = 1 - _cosine(vector, entry["vector"])
            if distance <= distance_threshold:
                hits.append({"response": entry["response"], "vector_distance": str(distance)})
        return sorted(hits, key=lambda h: float(h["vector_distance"]))[:num_results]

    async def astore(self, prompt, response, vector, filters):
        self.entries.append({"response": response, "vector": vector, "filters": filters})


def _cosine(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.hypot(*a) * math.hypot(*b))


class FakeEmbedder:
    def __init__(self, vector=(1.0, 0.0)):
        self.vector = list(vector)
        self.calls = []

    async def embed(self, text):
        self.calls.append(text)
        return self.vector


@pytest.fixture
def backend(monkeypatch):
    fake = FakeRedisvl()
    monkeypatch.setattr(semantic_cache, "_filter_expression", lambda values: values)
    return fake


def _cache(backend, embedder=None, **settings) -> SemanticCache:
    return SemanticCache(
        openai_settings(redis_url="redis://x", **settings), embedder or FakeEmbedder(),
        cache_factory=lambda *args: backend,
    )


async def test_stored_entry_is_returned_for_same_attributes(backend):
    cache = _cache(backend)
    await cache.store(_request(), "v3", ENTRY)

    hit = await cache.lookup(_request(description="Otra redacción de la misma idea de app."), "v3")

    assert hit == ENTRY


async def test_below_threshold_is_a_miss(backend):
    await _cache(backend, FakeEmbedder((1.0, 0.0))).store(_request(), "v3", ENTRY)
    # coseno 0.8 < 0.92
    assert await _cache(backend, FakeEmbedder((0.8, 0.6))).lookup(_request(), "v3") is None


async def test_threshold_is_configurable_and_sent_as_cosine_distance(backend):
    await _cache(backend, FakeEmbedder((1.0, 0.0))).store(_request(), "v3", ENTRY)
    loose = _cache(backend, FakeEmbedder((0.8, 0.6)), semantic_cache_threshold=0.75)

    assert await loose.lookup(_request(), "v3") == ENTRY
    assert backend.checks[-1][1] == pytest.approx(0.25)


@pytest.mark.parametrize(
    "overrides, version",
    [
        ({"detail_level": "detailed"}, "v3"),
        ({"output_format": "narrative"}, "v3"),
        ({"project_type": "web_saas"}, "v3"),
        ({}, "v2"),
    ],
)
async def test_entries_are_isolated_by_attributes(backend, overrides, version):
    cache = _cache(backend)
    await cache.store(_request(), "v3", ENTRY)

    assert await cache.lookup(_request(**overrides), version) is None


async def test_log_only_logs_potential_hit_but_returns_miss(backend):
    await _cache(backend).store(_request(), "v3", ENTRY)
    cache = _cache(backend, semantic_cache_mode="log_only")

    with pytest.MonkeyPatch.context() as mp:
        events = []
        mp.setattr(semantic_cache.logger, "info", lambda event, **kw: events.append((event, kw)))
        assert await cache.lookup(_request(), "v3") is None

    assert events[0][0] == "semantic_cache_would_hit" and events[0][1]["similarity"] == 1.0


async def test_log_only_still_stores(backend):
    await _cache(backend, semantic_cache_mode="log_only").store(_request(), "v3", ENTRY)
    assert len(backend.entries) == 1


@pytest.mark.parametrize("mode", ["off"])
async def test_off_mode_never_touches_embeddings_or_redis(backend, mode):
    embedder = FakeEmbedder()
    cache = _cache(backend, embedder, semantic_cache_mode=mode)
    await cache.store(_request(), "v3", ENTRY)
    assert await cache.lookup(_request(), "v3") is None
    assert embedder.calls == [] and backend.entries == []


async def test_disabled_without_redis_or_openai_key(backend):
    embedder = FakeEmbedder()
    no_redis = SemanticCache(openai_settings(), embedder, cache_factory=lambda *a: backend)
    no_key = SemanticCache(
        anthropic_settings(redis_url="redis://x"), embedder, cache_factory=lambda *a: backend
    )
    for cache in (no_redis, no_key):
        assert not cache.enabled
        assert await cache.lookup(_request(), "v3") is None
    assert embedder.calls == []


async def test_embedding_failure_is_a_miss_and_store_is_silent(backend):
    embedder = FakeEmbedder()
    embedder.embed = AsyncMock(side_effect=RuntimeError("boom"))
    cache = _cache(backend, embedder)
    assert await cache.lookup(_request(), "v3") is None
    await cache.store(_request(), "v3", ENTRY)


async def test_redis_failure_is_a_miss(backend):
    def broken(*args):
        raise ConnectionError("redis down")

    cache = SemanticCache(
        openai_settings(redis_url="redis://x"), FakeEmbedder(), cache_factory=broken
    )
    assert await cache.lookup(_request(), "v3") is None
    await cache.store(_request(), "v3", ENTRY)


async def test_corrupt_cached_payload_is_a_miss(backend):
    backend.entries.append({"response": "{no json", "vector": [1.0, 0.0],
                            "filters": attributes(_request(), "v3")})
    assert await _cache(backend).lookup(_request(), "v3") is None
    backend.entries[0]["response"] = '{"result": {"summary": "x"}}'
    assert await _cache(backend).lookup(_request(), "v3") is None


def test_semantic_text_includes_reference_projects():
    request = _request(reference_projects=[
        {"name": "App vecinal", "description": "Incidencias", "actual_hours": 300}])
    assert "App vecinal (300 h)" in semantic_text(request)


def test_index_name_includes_model_and_dimensions():
    assert index_name(openai_settings()) == "estimation_semantic_text_embedding_3_small_1536"
    assert index_name(openai_settings(embedding_dimensions=256)).endswith("_256")
