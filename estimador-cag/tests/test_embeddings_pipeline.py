"""Embedder asíncrono, framework de comparación y endpoints `/embeddings/*`."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openai import RateLimitError

from app.config import get_settings
from app.dependencies import get_chunker_builder, get_embedder
from app.generation.rag.analysis.comparison import (
    OBESE_MIN_TOKENS,
    ORPHAN_MAX_TOKENS,
    ChunkingComparator,
    ChunkingStats,
    TokenDistribution,
)
from app.generation.rag.analysis.similarity import cosine_similarity, percentile
from app.generation.rag.chunking.base import Chunker
from app.generation.rag.chunking.registry import (
    FREE_STRATEGIES,
    StrategyUnavailableError,
    UnknownStrategyError,
    build_chunkers,
)
from app.generation.rag.chunking.strategies import HierarchicalChunker
from app.generation.rag.chunking.structural import JSONStructuralChunker
from app.generation.rag.embedding.embedder import BATCH_SIZE, OpenAIEmbedder, estimate_cost_usd
from app.generation.rag.schemas import Chunk
from app.main import app
from tests._fakes import anthropic_settings, openai_settings
from tests._rag_fakes import FakeEmbedder, make_budget


class FakeOpenAI:
    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.calls: list[dict] = []
        self._failures = list(failures or [])
        self.embeddings = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._failures:
            raise self._failures.pop(0)
        # Se devuelven desordenados a propósito: el embedder debe reordenar por `index`.
        data = [SimpleNamespace(index=i, embedding=[float(i), 1.0]) for i in range(len(kwargs["input"]))]
        return SimpleNamespace(data=list(reversed(data)))


def _rate_limit() -> RateLimitError:
    return RateLimitError("slow down", response=SimpleNamespace(status_code=429, headers={}, request=None), body=None)


def _chunks(n: int) -> list[Chunk]:
    return [Chunk(chunk_id=f"c{i}", text=f"text {i}", metadata={}, token_count=2) for i in range(n)]


# --- Embedder ---------------------------------------------------------------------------------------------


async def test_embedder_batches_by_100_and_keeps_order():
    client = FakeOpenAI()
    embedder = OpenAIEmbedder(client, model="text-embedding-3-small", dimensions=1536)

    embedded = await embedder.embed_many(_chunks(250))

    assert [len(c["input"]) for c in client.calls] == [100, 100, 50]
    assert [e.chunk_id for e in embedded] == [f"c{i}" for i in range(250)]
    assert embedded[7].embedding == [7.0, 1.0] and embedded[7].text == "text 7"
    assert BATCH_SIZE == 100


async def test_embedder_passes_the_configured_model_and_dimensions():
    client = FakeOpenAI()

    await OpenAIEmbedder(client, model="text-embedding-3-large", dimensions=256).embed_one("hola")

    assert client.calls == [{"model": "text-embedding-3-large", "input": ["hola"], "dimensions": 256}]


async def test_embedder_defaults_come_from_settings(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "768")
    client = FakeOpenAI()

    await OpenAIEmbedder(client).embed_one("hola")

    assert client.calls[0]["dimensions"] == 768 and client.calls[0]["model"] == "text-embedding-3-small"


async def test_embedder_retries_rate_limits_with_backoff(mocker):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    mocker.patch.object(asyncio, "sleep", fake_sleep)
    client = FakeOpenAI(failures=[_rate_limit(), _rate_limit()])

    vectors = await OpenAIEmbedder(client).embed_texts(["a"])

    assert sleeps == [1, 2] and len(vectors) == 1 and len(client.calls) == 3


async def test_embedder_gives_up_after_three_retries(mocker):
    async def fake_sleep(_):
        return None

    mocker.patch.object(asyncio, "sleep", fake_sleep)
    client = FakeOpenAI(failures=[_rate_limit()] * 4)

    with pytest.raises(RateLimitError):
        await OpenAIEmbedder(client).embed_texts(["a"])
    assert len(client.calls) == 4


async def test_embedder_does_not_retry_other_errors():
    client = FakeOpenAI(failures=[RuntimeError("auth")])

    with pytest.raises(RuntimeError):
        await OpenAIEmbedder(client).embed_texts(["a"])
    assert len(client.calls) == 1


def test_embedding_cost_is_per_million_tokens():
    assert estimate_cost_usd(1_000_000) == pytest.approx(0.02)


# --- Similitud --------------------------------------------------------------------------------------------


def test_cosine_and_percentile():
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine_similarity([1, 0], [0, 1]) == 0.0
    with pytest.raises(ValueError):
        cosine_similarity([0, 0], [1, 0])
    with pytest.raises(ValueError):
        cosine_similarity([1], [1, 2])
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([], 95) == 0.0


# --- Comparador -------------------------------------------------------------------------------------------


class CountingChunker(Chunker):
    """Cuenta cuántas veces se trocea y simula coste de pago."""

    strategy_name = "counting"

    def __init__(self) -> None:
        self.runs = 0

    async def chunk(self, budgets):
        self.runs += 1
        self.last_extra_cost_usd = 0.5
        self.last_extra_api_calls = 3
        sizes = [5, 10, 30, 900]
        return [Chunk(chunk_id=f"k{i}", text=f"text {i}", metadata={}, token_count=n) for i, n in enumerate(sizes)]


async def test_stats_report_distribution_degenerate_chunks_and_cost():
    comparator = ChunkingComparator([CountingChunker()], FakeEmbedder())

    stats = (await comparator.compute_stats([make_budget()]))["counting"]

    assert stats.n_chunks == 4
    assert stats.token_distribution == TokenDistribution(min=5, p50=20.0, p95=a_p95(), max=900)
    assert stats.n_orphan_chunks == 2 and stats.n_obese_chunks == 1  # 5 y 10 tokens < 20; 900 > 800
    assert stats.ingestion_cost_usd == 0.5 and stats.extra_api_calls == 3
    assert ORPHAN_MAX_TOKENS == 20 and OBESE_MIN_TOKENS == 800


def a_p95() -> float:
    return round(percentile([5, 10, 30, 900], 95), 1)


async def test_chunking_is_memoized_between_stats_and_queries():
    chunker = CountingChunker()
    embedder = FakeEmbedder()
    comparator = ChunkingComparator([chunker], embedder)
    budgets = [make_budget()]

    await comparator.compute_stats(budgets)
    await comparator.run_queries(budgets, ["text 1"], top_k=2)
    await comparator.run_queries(budgets, ["text 2"], top_k=2)

    assert chunker.runs == 1
    assert embedder.chunk_calls == 1  # los vectores de los chunks tampoco se repiten


async def test_a_new_budgets_object_rechunks():
    chunker = CountingChunker()
    comparator = ChunkingComparator([chunker], FakeEmbedder())

    await comparator.compute_stats([make_budget()])
    await comparator.compute_stats([make_budget()])

    assert chunker.runs == 2


async def test_top_k_orders_by_cosine_and_exposes_parent_and_level():
    budgets = [make_budget("B-1", ["oauth tokens refresh flow", "inventory stock sync warehouse"])]
    comparator = ChunkingComparator([HierarchicalChunker()], FakeEmbedder())

    results = await comparator.run_queries(budgets, ["inventory stock sync"], top_k=2)

    top = results["hierarchical"][0].top_k
    assert len(top) == 2 and top[0].cosine >= top[1].cosine
    assert top[0].chunk_id == "B-1::C-2"
    assert top[0].level == "child" and top[0].parent_chunk_id == "B-1::parent"


async def test_no_queries_returns_no_results_and_embeds_nothing():
    embedder = FakeEmbedder()
    comparator = ChunkingComparator([JSONStructuralChunker()], embedder)

    assert await comparator.run_queries([make_budget()], [], top_k=3) == {}
    assert embedder.text_calls == [] and embedder.chunk_calls == 0


async def test_use_embedder_keeps_the_chunking_but_re_embeds():
    chunker = CountingChunker()
    first, second = FakeEmbedder(dimensions=8), FakeEmbedder(dimensions=16)
    comparator = ChunkingComparator([chunker], first)
    budgets = [make_budget()]

    await comparator.run_queries(budgets, ["text 1"])
    comparator.use_embedder(second)
    await comparator.run_queries(budgets, ["text 1"])

    assert chunker.runs == 1 and first.chunk_calls == 1 and second.chunk_calls == 1


# --- Registro ---------------------------------------------------------------------------------------------


def test_registry_builds_free_strategies_without_keys():
    settings = openai_settings()
    chunkers = build_chunkers(list(FREE_STRATEGIES), settings, FakeEmbedder())

    assert [c.strategy_name for c in chunkers] == list(FREE_STRATEGIES)


def test_registry_rejects_unknown_strategy():
    with pytest.raises(UnknownStrategyError):
        build_chunkers(["structural", "magic"], openai_settings(), FakeEmbedder())


def test_registry_reports_a_missing_key():
    with pytest.raises(StrategyUnavailableError) as exc:
        build_chunkers(["contextual_retrieval"], openai_settings(), FakeEmbedder())
    assert "ANTHROPIC_API_KEY" in exc.value.reason and exc.value.strategy == "contextual_retrieval"


def test_registry_checks_the_provider_of_the_configured_model():
    with pytest.raises(StrategyUnavailableError):
        build_chunkers(
            ["propositional"], openai_settings(propositional_chunker_model="claude-sonnet-4-5"), FakeEmbedder()
        )
    with pytest.raises(StrategyUnavailableError):
        build_chunkers(
            ["contextual_retrieval"],
            openai_settings(anthropic_api_key="sk-ant-test", contextual_chunker_model="gpt-4o"),
            FakeEmbedder(),
        )


def test_registry_builds_paid_strategies_with_their_configured_models():
    settings = openai_settings(anthropic_api_key="sk-ant-test", propositional_chunker_model="gpt-4o")

    chunkers = build_chunkers(["propositional", "contextual_retrieval", "semantic"], settings, FakeEmbedder())

    assert [c.strategy_name for c in chunkers] == ["propositional", "contextual_retrieval", "semantic"]
    assert chunkers[0]._model == "gpt-4o" and chunkers[1]._model == "claude-sonnet-4-5"


# --- Endpoints --------------------------------------------------------------------------------------------


@pytest.fixture
def client():
    fake = FakeEmbedder()
    app.dependency_overrides[get_embedder] = lambda: fake
    app.dependency_overrides[get_chunker_builder] = lambda: lambda names: build_chunkers(names, openai_settings(), fake)
    try:
        with TestClient(app) as test_client:
            test_client.fake = fake
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _payload(**extra) -> dict:
    return {"budgets": [make_budget("B-1", ["oauth tokens. refresh flow."]).model_dump()], **extra}


def test_ingest_still_returns_vectors_and_stats(client):
    response = client.post("/embeddings/ingest", json=_payload())

    body = response.json()
    assert response.status_code == 200
    assert body["stats"]["total_chunks"] == 1 and len(body["chunks"][0]["embedding"]) == 32


def test_compare_defaults_to_the_free_strategies(client):
    response = client.post("/embeddings/compare", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert list(body["stats_per_strategy"]) == list(FREE_STRATEGIES)
    assert body["queries_per_strategy"] == {}
    assert client.fake.text_calls == []  # sin consultas no se embebe nada


def test_compare_returns_top_k_for_each_requested_strategy(client):
    response = client.post(
        "/embeddings/compare",
        json=_payload(strategies=["structural", "hierarchical"], queries=["oauth tokens"], top_k=1),
    )

    body = response.json()
    assert response.status_code == 200
    assert set(body["queries_per_strategy"]) == {"structural", "hierarchical"}
    hit = body["queries_per_strategy"]["structural"][0]["top_k"]
    assert len(hit) == 1 and hit[0]["chunk_id"] == "B-1::C-1"


def test_compare_unknown_strategy_is_a_400(client):
    response = client.post("/embeddings/compare", json=_payload(strategies=["magic"]))

    assert response.status_code == 400 and "magic" in response.json()["detail"]


def test_compare_missing_provider_key_is_a_503_naming_the_key(client):
    response = client.post("/embeddings/compare", json=_payload(strategies=["contextual_retrieval"]))

    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


def test_compare_queries_without_openai_key_is_a_503(client):
    app.dependency_overrides[get_settings] = lambda: anthropic_settings()

    response = client.post("/embeddings/compare", json=_payload(queries=["oauth"]))

    assert response.status_code == 503 and "OPENAI_API_KEY" in response.json()["detail"]


def test_compare_compute_failure_is_a_generic_500(client, mocker):
    mocker.patch.object(FakeEmbedder, "embed_many", side_effect=RuntimeError("boom sk-secret-123"))

    response = client.post("/embeddings/compare", json=_payload(queries=["oauth"]))

    assert response.status_code == 500
    assert "sk-secret" not in response.text and "boom" not in response.text


def test_compare_validates_the_request(client):
    assert client.post("/embeddings/compare", json={"budgets": []}).status_code == 422
    assert client.post("/embeddings/compare", json=_payload(top_k=0)).status_code == 422
    assert client.post("/embeddings/compare", json=_payload(top_k=11)).status_code == 422


def test_compare_is_documented_in_openapi(client):
    assert "/embeddings/compare" in client.get("/openapi.json").json()["paths"]


def test_response_models_round_trip():
    stats = ChunkingStats(
        strategy="x",
        n_chunks=1,
        token_distribution=TokenDistribution(),
        n_orphan_chunks=0,
        n_obese_chunks=0,
        ingestion_cost_usd=0.0,
        ingestion_seconds=0.0,
    )
    assert stats.extra_api_calls == 0
