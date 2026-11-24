"""Pipeline avanzado multi-índice (Sesión 10): fusión por técnica (pura) e integración contra PostgreSQL + pgvector.

Las pruebas de integración se omiten sin `TEST_DATABASE_URL` (la fixture `sessions` lo hace). Los embeddings se
construyen a mano: con la consulta `e0`, un chunk `cos·e0 + sin·e1` está a distancia `1 - cos`.
"""

import asyncio
import math
import os
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.foundation.persistence.migrate import upgrade_to_head
from app.foundation.persistence.models import Chunk, Document, TechnicalDocChunk, TranscriptChunk
from app.generation.rag.errors import EmbedderUnavailableError, RetrievalError
from app.generation.rag.retrieval.advanced_pipeline import AdvancedRetriever, StageConfig, fuse_collection, sigmoid
from app.generation.rag.retrieval.collections import Collection, HardFilters
from app.generation.rag.retriever import CollectionHits
from app.generation.rag.schemas import RetrievedChunk
from tests._grounded import ScriptedGenerator

DIMENSIONS = 1536
URL = os.getenv("TEST_DATABASE_URL")
TODAY = date(2026, 6, 1)
ALL = [Collection.BUDGET, Collection.TRANSCRIPT, Collection.TECHNICAL_DOC]


def _vector(cosine: float) -> list[float]:
    vector = [0.0] * DIMENSIONS
    vector[0], vector[1] = cosine, math.sqrt(max(0.0, 1 - cosine * cosine))
    return vector


class QueryEmbedder:
    """Toda consulta (y subconsulta) es `e0`; registra las llamadas por lotes."""

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        return [_vector(1.0) for _ in texts]


class BrokenEmbedder:
    async def embed_texts(self, texts):
        raise RuntimeError("provider down: sk-secret")


class KeywordReranker:
    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    async def score(self, query, documents):
        return [max((v for k, v in self.scores.items() if k in doc), default=-3.0) for doc in documents]


# --- Fusión por técnica (pura) ---------------------------------------------------------------------------------


def _chunk(chunk_id: int, distance: float = 0.1, collection: str = "budget") -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id, content=f"c{chunk_id}", chunk_type="x", distance=distance, collection=collection
    )


def _hits(vector_ids: list[int], lexical_ids: list[int] | None = None) -> CollectionHits:
    candidates = {chunk_id: _chunk(chunk_id) for chunk_id in [*vector_ids, *(lexical_ids or [])]}
    return CollectionHits(
        collection=Collection.BUDGET,
        candidates=candidates,
        vector_ids=vector_ids,
        lexical_ids=lexical_ids or [],
        candidates_evaluated=len(candidates),
    )


def test_expansion_fuses_the_variants_by_consensus():
    # El chunk 2 está en las tres variantes; el 1 solo gana una. RRF premia el acuerdo.
    hits = [_hits([1, 2, 3]), _hits([9, 2, 8]), _hits([7, 2, 6])]

    fused = fuse_collection(hits, technique="expand", search_mode="vector", rrf_k=60)

    assert fused[0].id == 2


def test_decomposition_fuses_the_subqueries_by_coverage():
    # Cada subconsulta posee un tema: el primero de cada una ocupa un hueco antes que el segundo de ninguna.
    hits = [_hits([1, 2]), _hits([10, 11]), _hits([20])]

    fused = fuse_collection(hits, technique="decompose", search_mode="vector", rrf_k=60)

    assert [chunk.id for chunk in fused] == [1, 10, 20, 2, 11]


def test_decomposition_with_a_topic_only_one_subquery_covers_still_represents_it():
    hits = [_hits([1, 2, 3, 4]), _hits([99])]

    fused = fuse_collection(hits, technique="decompose", search_mode="vector", rrf_k=60)

    assert 99 in [chunk.id for chunk in fused[:2]]


def test_a_direct_query_in_hybrid_mode_fuses_both_branches_with_rrf():
    fused = fuse_collection([_hits([1, 2, 3], lexical_ids=[3])], technique="direct", search_mode="hybrid", rrf_k=60)

    assert [chunk.id for chunk in fused][0] == 3  # presente en ambas ramas


def test_sigmoid_maps_any_logit_to_a_non_negative_score_preserving_order():
    logits = [-12.0, -1.0, 0.0, 2.0, 12.0]
    scores = [sigmoid(x) for x in logits]

    assert scores == sorted(scores) and all(0.0 < s < 1.0 for s in scores)
    assert sigmoid(0) == 0.5
    assert sigmoid(-1000) >= 0.0 and sigmoid(1000) <= 1.0  # sin desbordar


# --- Integración -----------------------------------------------------------------------------------------------


@pytest.fixture
async def sessions(monkeypatch):
    if not URL:
        pytest.skip("TEST_DATABASE_URL no definida")
    if not URL.split("?")[0].endswith("test"):
        pytest.skip("la base de pruebas debe terminar en 'test'")
    monkeypatch.setenv("DATABASE_URL", URL)
    await asyncio.to_thread(upgrade_to_head)
    engine = create_async_engine(URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE documents, chunks RESTART IDENTITY CASCADE"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _insert(sessions, model, rows: list[tuple[str, str, float, dict]], *, chunk_type: str, document_type: str):
    """`rows`: (id trazable, contenido, coseno con la consulta, metadatos)."""
    async with sessions() as session:
        for source_id, content, cosine, metadata in rows:
            document = Document(source_path=f"test/{source_id}", document_type=document_type, metadata_={})
            session.add(document)
            await session.flush()
            session.add(
                model(
                    document_id=document.id,
                    chunk_type=metadata.pop("chunk_type", chunk_type),
                    content=content,
                    embedding=_vector(cosine),
                    metadata_=metadata,
                )
            )
        await session.commit()


def _budgets(rows):
    return [
        (budget_id, content, cosine, {"budget_id": budget_id, "client_sector": "finance", "year": year, **extra})
        for budget_id, content, cosine, year, extra in rows
    ]


@pytest.fixture
async def corpus(sessions):
    await _insert(
        sessions,
        Chunk,
        _budgets(
            [
                ("BUD-OLD", "Stripe Connect vendor payouts marketplace", 0.95, 2015, {}),
                ("BUD-NEW", "Stripe Connect vendor payouts marketplace", 0.90, 2025, {}),
                ("BUD-TASK", "Stripe payouts task", 0.99, 2025, {"chunk_type": "historical_task"}),
            ]
        ),
        chunk_type="budget_component",
        document_type="historical_budget",
    )
    await _insert(
        sessions,
        TranscriptChunk,
        [
            (
                "TR-1",
                "Client discussed kubernetes cluster migration timeline",
                0.80,
                {"transcript_id": "TR-1", "meeting_date": "2025-03-10", "speakers": ["ana"]},
            ),
            (
                "TR-2",
                "Client asked about the stripe connect checkout flow",
                0.70,
                {"transcript_id": "TR-2", "meeting_date": "2020-01-15", "speakers": ["luis"]},
            ),
        ],
        chunk_type="meeting_segment",
        document_type="meeting_transcript",
    )
    await _insert(
        sessions,
        TechnicalDocChunk,
        [
            ("DOC-PAY", "Payments API reference stripe webhooks", 0.60, {"doc_id": "DOC-PAY", "version": "2.1"}),
            ("DOC-OLD", "Legacy payments API reference", 0.60, {"doc_id": "DOC-OLD", "version": "1.0"}),
        ],
        chunk_type="doc_section",
        document_type="technical_doc",
    )
    return sessions


def _stages(**overrides) -> StageConfig:
    base = dict(
        routing_enabled=False,
        query_transform_enabled=False,
        search_mode="vector",
        rerank=False,
        temporal_decay_enabled=False,
        top_k=10,
        distance_threshold=2.0,
    )
    return StageConfig(**{**base, **overrides})


def _retriever(sessions, generator=None, reranker=None, embedder=None) -> AdvancedRetriever:
    return AdvancedRetriever(
        sessions,
        embedder if embedder is not None else QueryEmbedder(),
        generate=generator or ScriptedGenerator(),
        reranker=reranker,
        ef_search=40,
    )


async def _search(retriever, query="stripe payouts", *, stages=None, **kwargs):
    return await retriever.search(query, stages=stages or _stages(), reference_date=TODAY, **kwargs)


async def test_chunks_carry_their_provenance_and_document_date(corpus):
    outcome = await _search(_retriever(corpus), explicit_collections=ALL)

    by_source = {chunk.source_id: chunk for chunk in outcome.chunks}
    assert by_source["TR-1"].collection == "transcript" and by_source["TR-1"].document_date == date(2025, 3, 10)
    assert by_source["DOC-PAY"].collection == "technical_doc" and by_source["DOC-PAY"].document_date is None
    assert by_source["BUD-NEW"].collection == "budget" and by_source["BUD-NEW"].document_date == date(2025, 1, 1)


async def test_the_diagnostics_report_routing_technique_subqueries_and_cardinality(corpus):
    outcome = await _search(_retriever(corpus), explicit_collections=ALL)

    assert outcome.routing.level == "explicit" and outcome.routing.targets == ALL
    assert outcome.technique == "direct" and [s.query for s in outcome.subqueries] == ["stripe payouts"]
    # La cardinalidad cuenta los chunks de la colección tras los filtros: `historical_task` no es de `budget`.
    assert outcome.cardinality == {"budget": 2, "transcript": 2, "technical_doc": 2}
    assert outcome.low_confidence is False


async def test_a_hard_filter_that_empties_a_collection_shows_cardinality_zero(corpus):
    outcome = await _search(
        _retriever(corpus), explicit_collections=ALL, hard_filters=HardFilters(min_date=date(2026, 1, 1))
    )

    assert outcome.cardinality["budget"] == 0 and outcome.cardinality["transcript"] == 0
    assert outcome.cardinality["technical_doc"] == 2  # la fecha mínima no la entiende la documentación
    assert {chunk.collection for chunk in outcome.chunks} == {"technical_doc"}


async def test_hard_filters_apply_inside_each_collection(corpus):
    outcome = await _search(
        _retriever(corpus),
        explicit_collections=ALL,
        hard_filters=HardFilters(min_date=date(2024, 1, 1), version="2.1", sectors=("finance",)),
    )

    sources = {chunk.source_id for chunk in outcome.chunks}
    assert sources == {"BUD-NEW", "TR-1", "DOC-PAY"}  # sin 2015, sin la reunión de 2020, sin la v1.0
    assert outcome.cardinality == {"budget": 1, "transcript": 1, "technical_doc": 1}


async def test_the_budget_collection_does_not_return_historical_task_chunks(corpus):
    outcome = await _search(_retriever(corpus), explicit_collections=[Collection.BUDGET])

    assert {chunk.source_id for chunk in outcome.chunks} == {"BUD-OLD", "BUD-NEW"}


async def test_explicit_collections_never_call_the_classifier(corpus):
    generator = ScriptedGenerator()

    outcome = await _search(
        _retriever(corpus, generator),
        stages=_stages(routing_enabled=True),
        explicit_collections=[Collection.TECHNICAL_DOC],
    )

    assert outcome.routing.level == "explicit" and generator.calls == []
    assert {chunk.collection for chunk in outcome.chunks} == {"technical_doc"}
    assert list(outcome.cardinality) == ["technical_doc"]


async def test_a_classifier_failure_searches_all_three_collections(corpus):
    generator = ScriptedGenerator(RuntimeError("classifier down"), RuntimeError("classifier down"))

    outcome = await _search(
        _retriever(corpus, generator), "why did we choose this approach", stages=_stages(routing_enabled=True)
    )

    assert outcome.routing.level == "fallback" and outcome.routing.targets == ALL
    assert {chunk.collection for chunk in outcome.chunks} == {"budget", "transcript", "technical_doc"}


async def test_rules_route_to_the_matching_collection(corpus):
    outcome = await _search(
        _retriever(corpus), "what was said in the meeting about stripe", stages=_stages(routing_enabled=True)
    )

    assert outcome.routing.level == "rules" and outcome.routing.targets == [Collection.TRANSCRIPT]
    assert {chunk.collection for chunk in outcome.chunks} == {"transcript"}


async def test_a_decomposed_query_gives_each_topic_a_chunk(corpus):
    generator = ScriptedGenerator(
        {
            "subqueries": [
                {"topic": "payments", "query": "stripe connect vendor payouts"},
                {"topic": "infra", "query": "kubernetes cluster migration"},
            ]
        }
    )
    embedder = QueryEmbedder()
    query = "Marketplace with Stripe Connect vendor payouts, and the kubernetes cluster migration plan for the client"

    outcome = await _search(
        _retriever(corpus, generator, embedder=embedder),
        query,
        stages=_stages(query_transform_enabled=True, search_mode="hybrid", top_k=5),
        explicit_collections=[Collection.BUDGET, Collection.TRANSCRIPT],
    )

    assert outcome.technique == "decompose" and [s.topic for s in outcome.subqueries] == ["payments", "infra"]
    sources = [chunk.source_id for chunk in outcome.chunks]
    assert "TR-1" in sources  # el tema «infra» solo lo cubre esa reunión
    assert {"BUD-OLD", "BUD-NEW"} & set(sources)  # y el tema «payments» lo cubre un presupuesto
    assert embedder.batches == [["stripe connect vendor payouts", "kubernetes cluster migration"]]  # un único lote


async def test_a_query_transform_failure_degrades_to_direct(corpus):
    generator = ScriptedGenerator(RuntimeError("down"), RuntimeError("down"))
    query = "Marketplace with Stripe Connect vendor payouts, and the kubernetes cluster migration plan for the client"

    outcome = await _search(
        _retriever(corpus, generator),
        query,
        stages=_stages(query_transform_enabled=True),
        explicit_collections=[Collection.BUDGET],
    )

    assert outcome.technique == "direct" and [s.query for s in outcome.subqueries] == [query]
    assert outcome.chunks


async def test_temporal_decay_breaks_ties_in_favour_of_the_recent_document(corpus):
    without = await _search(_retriever(corpus), explicit_collections=[Collection.BUDGET])
    with_decay = await _search(
        _retriever(corpus), stages=_stages(temporal_decay_enabled=True), explicit_collections=[Collection.BUDGET]
    )

    assert [chunk.source_id for chunk in without.chunks] == ["BUD-OLD", "BUD-NEW"]  # el antiguo está más cerca
    assert [chunk.source_id for chunk in with_decay.chunks] == ["BUD-NEW", "BUD-OLD"]
    assert with_decay.chunks[0].relevance_score > with_decay.chunks[1].relevance_score


async def test_rerank_scores_are_squashed_to_non_negative_relevance(corpus):
    reranker = KeywordReranker({"webhooks": 4.0, "kubernetes": -2.0})

    outcome = await _search(
        _retriever(corpus, reranker=reranker), stages=_stages(rerank=True), explicit_collections=ALL
    )

    assert outcome.chunks[0].source_id == "DOC-PAY"
    assert outcome.chunks[0].relevance_score == pytest.approx(sigmoid(4.0))
    assert all(chunk.relevance_score >= 0 for chunk in outcome.chunks)


async def test_top_k_cuts_the_final_list(corpus):
    outcome = await _search(_retriever(corpus), stages=_stages(top_k=2), explicit_collections=ALL)

    assert len(outcome.chunks) == 2


async def test_nothing_recovered_is_a_soft_fail_with_zero_cardinality(corpus):
    outcome = await _search(
        _retriever(corpus),
        explicit_collections=[Collection.BUDGET],
        hard_filters=HardFilters(sectors=("healthcare",)),
    )

    assert outcome.chunks == [] and outcome.low_confidence is True and outcome.cardinality == {"budget": 0}


async def test_without_an_embedder_the_pipeline_reports_it(corpus):
    retriever = AdvancedRetriever(corpus, None, generate=ScriptedGenerator(), reranker=None, ef_search=40)

    with pytest.raises(EmbedderUnavailableError):
        await _search(retriever, explicit_collections=ALL)


async def test_embedder_and_database_failures_are_sanitized_retrieval_errors(corpus):
    with pytest.raises(RetrievalError) as embedding:
        await _search(_retriever(corpus, embedder=BrokenEmbedder()), explicit_collections=ALL)
    assert "sk-secret" not in str(embedding.value)

    def broken_factory():
        raise RuntimeError("DATABASE_URL is not configured")

    broken = AdvancedRetriever(broken_factory, QueryEmbedder(), generate=ScriptedGenerator(), reranker=None, ef_search=40)
    with pytest.raises(RetrievalError):
        await _search(broken, explicit_collections=ALL)


async def test_rerank_without_a_reranker_is_a_retrieval_error(corpus):
    with pytest.raises(RetrievalError):
        await _search(_retriever(corpus, reranker=None), stages=_stages(rerank=True), explicit_collections=ALL)
