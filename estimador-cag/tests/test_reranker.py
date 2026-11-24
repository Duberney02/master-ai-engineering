"""Reranker (Sesión 10): carga diferida del cross-encoder y reordenación con un reranker falso (sin pesos)."""

import asyncio
import sys
import threading
import types

import pytest

from app.generation.rag.retrieval.reranker import CrossEncoderReranker, rerank_with_scores
from app.generation.rag.schemas import RetrievedChunk


class FakeReranker:
    """Puntúa un documento por las palabras clave que contiene; registra las llamadas."""

    def __init__(self, keywords: dict[str, float]) -> None:
        self.keywords = keywords
        self.calls: list[tuple[str, list[str]]] = []

    async def score(self, query, documents):
        self.calls.append((query, list(documents)))
        return [max((v for k, v in self.keywords.items() if k in doc), default=0.0) for doc in documents]


def _chunk(chunk_id: int, content: str) -> RetrievedChunk:
    return RetrievedChunk(id=chunk_id, content=content, chunk_type="budget_component", distance=0.1 * chunk_id)


async def test_the_fake_reranker_reorders_and_keeps_only_the_top_n():
    candidates = [_chunk(i, f"component {i}") for i in range(1, 31)]
    candidates[29] = _chunk(30, "component 30 oauth refresh tokens")  # el candidato 30 de la fase de recall
    reranker = FakeReranker({"oauth": 5.0})

    ranked = await rerank_with_scores(reranker, "oauth", candidates, top_n=5)

    assert ranked[0][0].id == 30 and ranked[0][1] == 5.0
    assert len(ranked) == 5
    assert [chunk.id for chunk, _ in ranked[1:]] == [1, 2, 3, 4]  # empates: se conserva el orden de recall


async def test_the_reranker_scores_the_query_against_every_candidate_text():
    reranker = FakeReranker({})
    await rerank_with_scores(reranker, "kyc", [_chunk(1, "a"), _chunk(2, "b")], top_n=2)

    assert reranker.calls == [("kyc", ["a", "b"])]


async def test_no_candidates_means_no_call_to_the_model():
    reranker = FakeReranker({})

    assert await rerank_with_scores(reranker, "kyc", [], top_n=5) == []
    assert reranker.calls == []


def test_importing_and_building_the_reranker_does_not_load_torch_or_the_model():
    reranker = CrossEncoderReranker("cross-encoder/does-not-matter")

    assert reranker.loaded is False
    assert reranker.model_name == "cross-encoder/does-not-matter"


def _install_fake_sentence_transformers(monkeypatch, loads: list, started: threading.Event | None = None):
    class FakeCrossEncoder:
        def __init__(self, name):
            loads.append(name)
            if started is not None:
                started.wait(timeout=2)  # alarga la carga para que dos hilos compitan

        def predict(self, pairs):
            return [float(len(document)) for _query, document in pairs]

    module = types.ModuleType("sentence_transformers")
    module.CrossEncoder = FakeCrossEncoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)


async def test_the_model_loads_on_first_use_and_only_once(monkeypatch):
    loads: list = []
    _install_fake_sentence_transformers(monkeypatch, loads)
    reranker = CrossEncoderReranker("modelo-x")

    assert loads == []
    assert await reranker.score("q", ["aa", "b"]) == [2.0, 1.0]
    await reranker.score("q", ["c"])

    assert loads == ["modelo-x"] and reranker.loaded is True


async def test_two_concurrent_first_uses_load_the_model_once(monkeypatch):
    loads: list = []
    gate = threading.Event()
    _install_fake_sentence_transformers(monkeypatch, loads, started=gate)
    reranker = CrossEncoderReranker("modelo-x")

    first = asyncio.create_task(reranker.score("q", ["a"]))
    second = asyncio.create_task(reranker.score("q", ["b"]))
    await asyncio.sleep(0.05)
    gate.set()
    await asyncio.gather(first, second)

    assert loads == ["modelo-x"]


async def test_scoring_runs_off_the_event_loop(monkeypatch):
    threads: list[int] = []
    loads: list = []
    _install_fake_sentence_transformers(monkeypatch, loads)
    reranker = CrossEncoderReranker("modelo-x")
    original = reranker._score_sync

    def spy(query, documents):
        threads.append(threading.get_ident())
        return original(query, documents)

    monkeypatch.setattr(reranker, "_score_sync", spy)
    await reranker.score("q", ["a"])

    assert threads and threads[0] != threading.get_ident()


async def test_an_empty_document_list_scores_nothing_without_loading():
    reranker = CrossEncoderReranker("modelo-x")

    assert await reranker.score("q", []) == []
    assert reranker.loaded is False


@pytest.mark.parametrize("n", [1, 3])
async def test_top_n_larger_than_the_pool_returns_everything(n):
    ranked = await rerank_with_scores(FakeReranker({}), "q", [_chunk(1, "a")], top_n=n)

    assert len(ranked) == 1
