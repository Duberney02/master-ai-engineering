"""Horas por tarea (Sesión 10): consenso ponderado y fiabilidad como funciones puras, y el estimador con un recuperador falso."""

import asyncio

import fakeredis
import pytest
from fakeredis import FakeAsyncRedis

from app.config import Settings
from app.foundation.llm.runtime_config import RuntimeRetrievalConfig
from app.generation.rag.errors import RetrievalError
from app.generation.rag.retriever import ChunkRetriever, RetrievalFilters
from app.generation.rag.schemas import RetrievalResult, RetrievedChunk, TaskHoursModuleInput, TaskHoursTaskInput
from app.generation.rag.task_hours import (
    WEIGHT_EPS,
    TaskHoursEstimator,
    compose_task_search_text,
    estimate_from_chunks,
    weighted_consensus,
)
from tests._fakes import openai_settings


def task_chunk(chunk_id: int, hours: float | None, distance: float, budget_id: str | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        content=f"Task {chunk_id}",
        chunk_type="historical_task",
        distance=distance,
        budget_id=budget_id or f"BUD-{chunk_id}",
        estimated_hours=hours,
    )


# --- Consenso (puro) --------------------------------------------------------------------------------------------


def test_the_consensus_leans_towards_the_closer_neighbour():
    consensus = weighted_consensus([(10, 0.1), (30, 0.4)])

    assert consensus.hours == pytest.approx((10 / 0.1 + 30 / 0.4) / (1 / 0.1 + 1 / 0.4), abs=0.05)  # 14.0
    assert abs(consensus.hours - 10) < abs(consensus.hours - 30)


def test_equal_distances_give_the_plain_mean():
    assert weighted_consensus([(10, 0.3), (30, 0.3)]).hours == 20.0


def test_a_single_neighbour_is_its_own_consensus_with_zero_dispersion():
    consensus = weighted_consensus([(24, 0.2)])

    assert (consensus.hours, consensus.dispersion) == (24.0, 0.0)
    assert consensus.reliability == pytest.approx(0.8)  # 1 - distancia, sin penalización por desacuerdo


def test_agreeing_neighbours_are_more_reliable_than_contradicting_ones_at_the_same_distance():
    agree = weighted_consensus([(40, 0.2), (42, 0.2), (38, 0.2)])
    disagree = weighted_consensus([(10, 0.2), (90, 0.2), (50, 0.2)])

    assert agree.reliability > disagree.reliability
    assert agree.dispersion < disagree.dispersion


def test_closer_neighbours_are_more_reliable_than_distant_ones_at_the_same_agreement():
    close = weighted_consensus([(40, 0.05), (40, 0.1)])
    far = weighted_consensus([(40, 0.4), (40, 0.44)])

    assert close.reliability > far.reliability


def test_dispersion_is_the_coefficient_of_variation_of_the_neighbour_hours():
    consensus = weighted_consensus([(10, 0.2), (30, 0.2)])

    assert consensus.dispersion == 0.5  # desviación típica 10 / media 20


def test_an_exact_match_does_not_blow_up_into_an_infinite_weight():
    consensus = weighted_consensus([(8, 0.0), (80, 0.3)])

    assert consensus.hours < 9  # domina el acierto exacto, pero el otro vecino pesa algo
    assert consensus.hours > 8
    assert WEIGHT_EPS > 0


def test_reliability_is_clamped_to_zero_one_even_with_distant_or_contradicting_neighbours():
    far = weighted_consensus([(10, 1.5), (500, 1.9)])

    assert far.reliability == 0.0  # similitud 0
    for neighbours in ([(1, 0.0)], [(1, 0.0), (1000, 0.0)], [(5, 0.1)] * 5):
        assert 0.0 <= weighted_consensus(neighbours).reliability <= 1.0


def test_zero_hours_neighbours_have_no_dispersion():
    assert weighted_consensus([(0, 0.1), (0, 0.2)]).dispersion == 0.0


def test_the_consensus_needs_at_least_one_neighbour():
    with pytest.raises(ValueError):
        weighted_consensus([])


# --- Composición y mapeo -----------------------------------------------------------------------------------------


def test_the_search_text_mirrors_the_historical_task_chunk_shape():
    assert compose_task_search_text("Payments", "Stripe webhooks", "Handle retries") == (
        "Module: Payments\nTask: Stripe webhooks\nHandle retries"
    )
    assert compose_task_search_text("", "Stripe webhooks", None) == "Task: Stripe webhooks"


def test_a_task_without_neighbours_has_no_match_and_no_hours():
    estimate = estimate_from_chunks("Payments", "Stripe webhooks", [])

    assert estimate.has_match is False
    assert estimate.estimated_hours is None and estimate.reliability is None and estimate.neighbors == []


def test_neighbours_without_recorded_hours_do_not_count():
    assert estimate_from_chunks("m", "t", [task_chunk(1, None, 0.1)]).has_match is False


def test_the_estimate_lists_the_neighbours_it_used():
    estimate = estimate_from_chunks("m", "t", [task_chunk(1, 10, 0.1), task_chunk(2, None, 0.2), task_chunk(3, 30, 0.4)])

    assert estimate.has_match is True and estimate.estimated_hours == 14.0
    assert [(n.source_id, n.budget_id, n.estimated_hours, n.distance) for n in estimate.neighbors] == [
        (1, "BUD-1", 10.0, 0.1),
        (3, "BUD-3", 30.0, 0.4),
    ]


# --- Estimador ---------------------------------------------------------------------------------------------------


class HoursRetriever:
    """Devuelve vecinos según el texto de la consulta y registra las búsquedas y la concurrencia."""

    def __init__(self, by_task: dict[str, list[RetrievedChunk]] | None = None, error: Exception | None = None) -> None:
        self.by_task = by_task or {}
        self.error = error
        self.calls: list[dict] = []
        self.active = 0
        self.max_active = 0

    async def search(
        self, query_text, *, top_k, distance_threshold, filters, search_mode="vector", rerank=False, rerank_top_n=None
    ):
        self.calls.append(
            {
                "query_text": query_text,
                "top_k": top_k,
                "distance_threshold": distance_threshold,
                "filters": filters,
                "search_mode": search_mode,
                "rerank": rerank,
                "rerank_top_n": rerank_top_n,
            }
        )
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0)
            if self.error:
                raise self.error
            for task_name, chunks in self.by_task.items():
                if query_text.splitlines()[-1] == f"Task: {task_name}":  # línea completa: `task-1` no casa con `task-10`
                    return RetrievalResult(chunks=chunks, low_confidence=not chunks, candidates_evaluated=9)
            return RetrievalResult(chunks=[], low_confidence=True, candidates_evaluated=9)
        finally:
            self.active -= 1


def modules(*tasks: tuple[str, str]) -> list[TaskHoursModuleInput]:
    grouped: dict[str, list[TaskHoursTaskInput]] = {}
    for module, task in tasks:
        grouped.setdefault(module, []).append(TaskHoursTaskInput(name=task, description=None))
    return [TaskHoursModuleInput(name=name, tasks=items) for name, items in grouped.items()]


def estimator(retriever, runtime=None, **settings) -> TaskHoursEstimator:
    return TaskHoursEstimator(openai_settings(**settings), retriever, runtime_retrieval=runtime)


async def test_each_task_is_searched_over_historical_tasks_only():
    retriever = HoursRetriever({"KYC": [task_chunk(1, 10, 0.1), task_chunk(2, 30, 0.4)]})

    result = await estimator(retriever).estimate_all(modules(("Compliance", "KYC")))

    call = retriever.calls[0]
    assert call["filters"] == RetrievalFilters(chunk_types=["historical_task"])
    assert call["query_text"] == "Module: Compliance\nTask: KYC"
    assert result.tasks[0].estimated_hours == 14.0 and result.tasks[0].has_match is True


async def test_a_task_without_neighbours_under_the_threshold_comes_back_unmatched():
    retriever = HoursRetriever({"KYC": [task_chunk(1, 10, 0.1)]})

    result = await estimator(retriever).estimate_all(modules(("Compliance", "KYC"), ("Compliance", "Unheard-of task")))

    assert [(t.task, t.has_match) for t in result.tasks] == [("KYC", True), ("Unheard-of task", False)]
    assert result.tasks[1].estimated_hours is None


async def test_the_order_of_the_tasks_is_the_order_they_were_submitted():
    names = [f"task-{i}" for i in range(20)]
    retriever = HoursRetriever({name: [task_chunk(i, 10 + i, 0.1)] for i, name in enumerate(names)})

    result = await estimator(retriever).estimate_all(modules(*[("M", name) for name in names]))

    assert [t.task for t in result.tasks] == names
    assert [t.estimated_hours for t in result.tasks] == [10.0 + i for i in range(20)]


async def test_the_defaults_come_from_settings():
    retriever = HoursRetriever()

    await estimator(retriever, task_hours_top_k=7, task_hours_distance_threshold=0.3).estimate_all(modules(("M", "T")))

    call = retriever.calls[0]
    assert (call["top_k"], call["distance_threshold"]) == (7, 0.3)
    assert (call["search_mode"], call["rerank"]) == ("vector", False)


async def test_explicit_arguments_beat_settings():
    retriever = HoursRetriever()

    await estimator(retriever).estimate_all(modules(("M", "T")), top_k=3, distance_threshold=0.2)

    assert (retriever.calls[0]["top_k"], retriever.calls[0]["distance_threshold"]) == (3, 0.2)


async def test_the_runtime_values_drive_k_threshold_search_mode_and_rerank(mocker):
    server = fakeredis.FakeServer()
    mocker.patch(
        "app.foundation.llm.runtime_config.Redis.from_url",
        side_effect=lambda url, **kw: FakeAsyncRedis(server=server, decode_responses=kw.get("decode_responses", False)),
    )
    runtime = RuntimeRetrievalConfig(
        Settings(llm_provider="openai", openai_api_key="sk-test", redis_url="redis://fake/0", _env_file=None)
    )
    await runtime.set_many(
        {"task_hours_top_k": 9, "task_hours_distance_threshold": 0.25, "search_mode": "hybrid", "rerank": True}
    )
    retriever = HoursRetriever()

    await estimator(retriever, runtime).estimate_all(modules(("M", "T")))

    call = retriever.calls[0]
    assert (call["top_k"], call["distance_threshold"]) == (9, 0.25)
    assert (call["search_mode"], call["rerank"]) == ("hybrid", True)
    assert call["rerank_top_n"] == 9  # con reranking, los vecinos del consenso son `top_k`, no `rerank_top_n`


async def test_searches_are_bounded_so_a_large_request_does_not_exhaust_the_database_pool():
    retriever = HoursRetriever()

    await estimator(retriever).estimate_all(modules(*[("M", f"t{i}") for i in range(40)]))

    assert len(retriever.calls) == 40 and 1 < retriever.max_active <= 8


async def test_a_retrieval_failure_propagates_so_the_api_can_sanitize_it():
    with pytest.raises(RetrievalError):
        await estimator(HoursRetriever(error=RetrievalError("boom"))).estimate_all(modules(("M", "T")))


# --- Integración: corpus `historical_task` real ------------------------------------------------------------------


@pytest.fixture
async def sessions(monkeypatch):
    import math
    import os

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.foundation.persistence.migrate import upgrade_to_head
    from app.foundation.persistence.models import Chunk, Document

    url = os.getenv("TEST_DATABASE_URL")
    if not url or not url.split("?")[0].endswith("test"):
        pytest.skip("TEST_DATABASE_URL no definida (o no termina en 'test')")
    monkeypatch.setenv("DATABASE_URL", url)
    await asyncio.to_thread(upgrade_to_head)
    engine = create_async_engine(url, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE documents, chunks RESTART IDENTITY CASCADE"))
    factory = async_sessionmaker(engine, expire_on_commit=False)

    def vector(cosine: float) -> list[float]:
        values = [0.0] * 1536
        values[0], values[1] = cosine, math.sqrt(max(0.0, 1 - cosine * cosine))
        return values

    rows = [  # (budget_id, chunk_type, horas, coseno con la consulta)
        ("BUD-A", "historical_task", 10, 0.90),
        ("BUD-B", "historical_task", 30, 0.60),
        ("BUD-C", "historical_task", 500, 0.10),  # demasiado lejos: queda por encima del umbral
        ("BUD-D", "budget_component", 999, 0.99),  # otro chunk_type: nunca es vecino de una tarea
    ]
    async with factory() as session:
        for budget_id, chunk_type, hours, cosine in rows:
            document = Document(source_path=f"test/{budget_id}", document_type="historical_task_breakdown", metadata_={})
            session.add(document)
            await session.flush()
            session.add(
                Chunk(
                    document_id=document.id,
                    chunk_type=chunk_type,
                    content=f"Task {budget_id}",
                    embedding=vector(cosine),
                    metadata_={"budget_id": budget_id, "estimated_hours": hours, "year": 2024, "client_sector": "x"},
                )
            )
        await session.commit()
    yield factory
    await engine.dispose()


class QueryEmbedder:
    """Toda consulta es `e0`."""

    async def embed_one(self, text_):
        return [1.0] + [0.0] * 1535


async def test_hours_come_from_the_real_historical_task_neighbours_under_the_threshold(sessions):
    retriever = ChunkRetriever(sessions, QueryEmbedder(), ef_search=40)

    result = await TaskHoursEstimator(openai_settings(), retriever).estimate_all(
        modules(("Compliance", "KYC")), top_k=5, distance_threshold=0.45
    )

    task = result.tasks[0]
    assert [n.budget_id for n in task.neighbors] == ["BUD-A", "BUD-B"]  # sin BUD-C (lejos) ni BUD-D (otro tipo)
    assert task.has_match is True and 10 < task.estimated_hours < 20  # más cerca de BUD-A (10 h) que de BUD-B (30 h)
    assert task.neighbors[0].estimated_hours == 10.0 and task.neighbors[0].distance == pytest.approx(0.1, abs=1e-3)  # halfvec: media precisión


async def test_a_threshold_below_every_neighbour_leaves_the_task_unmatched(sessions):
    retriever = ChunkRetriever(sessions, QueryEmbedder(), ef_search=40)

    result = await TaskHoursEstimator(openai_settings(), retriever).estimate_all(
        modules(("Compliance", "KYC")), distance_threshold=0.05
    )

    assert result.tasks[0].has_match is False and result.tasks[0].estimated_hours is None
