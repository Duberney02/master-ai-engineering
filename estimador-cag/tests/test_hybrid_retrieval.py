"""Recuperación híbrida y con reranking contra PostgreSQL + pgvector real (Sesión 10).

Se omite sin `TEST_DATABASE_URL` (`api-test` la define con `api-db`). Los embeddings se construyen a mano para controlar
la distancia: con la consulta `e0`, un chunk `cos·e0 + sin·e1` está a distancia `1 - cos`.
"""

import asyncio
import math
import os

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.foundation.persistence.migrate import upgrade_to_head
from app.foundation.persistence.models import Chunk, Document
from app.generation.rag.errors import RetrievalError
from app.generation.rag.retriever import ChunkRetriever, RetrievalFilters, lexical_search_statement

DIMENSIONS = 1536
URL = os.getenv("TEST_DATABASE_URL")

def _vector(cosine: float) -> list[float]:
    vector = [0.0] * DIMENSIONS
    vector[0], vector[1] = cosine, math.sqrt(max(0.0, 1 - cosine * cosine))
    return vector


class QueryEmbedder:
    """La consulta siempre es `e0`."""

    async def embed_one(self, text_: str) -> list[float]:
        return _vector(1.0)


class KeywordReranker:
    """Cross-encoder falso: puntúa alto el texto que contiene la palabra clave."""

    def __init__(self, keyword: str) -> None:
        self.keyword = keyword
        self.pool_sizes: list[int] = []

    async def score(self, query, documents):
        self.pool_sizes.append(len(documents))
        return [10.0 if self.keyword in document else -1.0 for document in documents]


class BrokenReranker:
    async def score(self, query, documents):
        raise RuntimeError("model download failed: sk-secret")


# --- SQL (sin base de datos) -----------------------------------------------------------------------------------


def test_the_lexical_statement_uses_the_generated_column_the_same_regconfig_and_the_filters():
    statement = lexical_search_statement("stripe payouts", 50, RetrievalFilters(sectors=["finance"], chunk_types=["x"]))
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "chunks.content_tsv @@" in sql and "ts_rank_cd(chunks.content_tsv" in sql
    assert "plainto_tsquery" in sql and "chunks.metadata ->>" in sql and "chunks.chunk_type IN" in sql
    assert "ORDER BY ts_rank_cd" in sql and "LIMIT" in sql


def test_the_lexical_statement_does_not_require_an_embedding():
    sql = str(lexical_search_statement("stripe", 5, RetrievalFilters()).compile(dialect=postgresql.dialect()))

    assert "embedding IS NOT NULL" not in sql  # un chunk sin vectorizar puede casar léxicamente


# --- Integración (la fixture `sessions` se omite sin TEST_DATABASE_URL) ----------------------------------------------

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


async def _insert(sessions, rows: list[tuple[str, str, float, dict]]) -> None:
    """`rows`: (budget_id, contenido, coseno con la consulta, metadatos extra)."""
    async with sessions() as session:
        for budget_id, content, cosine, extra in rows:
            document = Document(source_path=f"test/{budget_id}.json", document_type="historical_budget", metadata_={})
            session.add(document)
            await session.flush()
            session.add(
                Chunk(
                    document_id=document.id,
                    chunk_type=extra.pop("chunk_type", "budget_component"),
                    content=content,
                    embedding=_vector(cosine),
                    metadata_={"budget_id": budget_id, "client_sector": "finance", "year": 2024, **extra},
                )
            )
        await session.commit()


def _retriever(sessions, reranker=None, **kwargs) -> ChunkRetriever:
    return ChunkRetriever(sessions, QueryEmbedder(), ef_search=40, reranker=reranker, **kwargs)


def _crowded_corpus() -> list[tuple[str, str, float, dict]]:
    """12 chunks que el embedding considera muy cercanos y uno con un identificador literal que queda muy atrás."""
    rows = [(f"BUD-{i:02d}", f"Generic onboarding component number {i}", 0.99 - 0.01 * i, {}) for i in range(12)]
    rows.append(("BUD-ZX", "Legacy gateway adapter ZX9000 settlement", 0.30, {}))
    return rows


async def test_hybrid_surfaces_a_literal_identifier_the_vector_branch_ranks_last(sessions):
    await _insert(sessions, _crowded_corpus())
    retriever = _retriever(sessions)
    args = {"top_k": 3, "distance_threshold": 1.0, "filters": RetrievalFilters()}

    vector = await retriever.search("ZX9000", search_mode="vector", **args)
    hybrid = await retriever.search("ZX9000", search_mode="hybrid", **args)

    assert "BUD-ZX" not in [chunk.budget_id for chunk in vector.chunks]
    assert hybrid.chunks[0].budget_id == "BUD-ZX"
    assert len(hybrid.chunks) == 3 and hybrid.low_confidence is False


async def test_a_lexical_only_candidate_beyond_the_threshold_still_enters_the_fusion(sessions):
    """El umbral recorta la rama vectorial; la léxica aporta lo que el embedding no sitúa."""
    await _insert(sessions, _crowded_corpus())

    result = await _retriever(sessions).search(
        "ZX9000", top_k=5, distance_threshold=0.2, filters=RetrievalFilters(), search_mode="hybrid"
    )

    zx = next(chunk for chunk in result.chunks if chunk.budget_id == "BUD-ZX")
    assert zx.distance == 1.0  # centinela: no entró en el ranking vectorial, no tiene distancia coseno


async def test_vector_mode_without_rerank_matches_the_session_9_behaviour(sessions):
    await _insert(sessions, _crowded_corpus())
    retriever = _retriever(sessions)

    default = await retriever.search(
        "ZX9000", top_k=4, distance_threshold=1.0, filters=RetrievalFilters()
    )
    explicit = await retriever.search(
        "ZX9000", top_k=4, distance_threshold=1.0, filters=RetrievalFilters(), search_mode="vector", rerank=False
    )

    assert [c.budget_id for c in default.chunks] == ["BUD-00", "BUD-01", "BUD-02", "BUD-03"]  # por distancia
    assert default == explicit
    assert all(chunk.relevance_score is None and chunk.collection == "budget" for chunk in default.chunks)
    assert default.chunks[0].source_id == "BUD-00"


async def test_hybrid_applies_the_structural_filters_to_the_lexical_branch(sessions):
    await _insert(
        sessions,
        [
            ("BUD-A", "Stripe settlement adapter", 0.9, {"client_sector": "finance"}),
            ("BUD-B", "Stripe settlement adapter", 0.9, {"client_sector": "healthcare"}),
        ],
    )

    result = await _retriever(sessions).search(
        "stripe settlement",
        top_k=5,
        distance_threshold=1.0,
        filters=RetrievalFilters(sectors=["healthcare"]),
        search_mode="hybrid",
    )

    assert [chunk.budget_id for chunk in result.chunks] == ["BUD-B"]


async def test_a_long_query_still_matches_lexically_on_any_term(sessions):
    """OR entre lexemas: una consulta larga con un identificador no exige que el chunk contenga todas las palabras."""
    await _insert(sessions, [("BUD-ZX", "Legacy gateway adapter ZX9000", 0.30, {})])
    long_query = "We need a modern platform for payments with onboarding dashboards and also the ZX9000 adapter"

    result = await _retriever(sessions).search(
        long_query, top_k=3, distance_threshold=0.1, filters=RetrievalFilters(), search_mode="hybrid"
    )

    assert [chunk.budget_id for chunk in result.chunks] == ["BUD-ZX"]


async def test_rerank_floats_the_candidate_the_recall_ranked_thirtieth(sessions):
    rows = [(f"BUD-{i:02d}", f"Generic component number {i}", 0.99 - 0.005 * i, {}) for i in range(35)]
    rows[29] = ("BUD-29", "Generic component number 29 with oauth refresh tokens", 0.99 - 0.005 * 29, {})
    await _insert(sessions, rows)
    reranker = KeywordReranker("oauth")

    result = await _retriever(sessions, reranker, recall_top_k=50, rerank_top_n=5).search(
        "oauth", top_k=10, distance_threshold=1.0, filters=RetrievalFilters(), rerank=True
    )

    assert result.chunks[0].budget_id == "BUD-29" and result.chunks[0].relevance_score == 10.0
    assert len(result.chunks) == 5  # `rerank_top_n`, no `top_k`
    assert reranker.pool_sizes == [35]  # recall ancho: el cross-encoder vio todo el conjunto de candidatos


async def test_a_reranker_failure_is_a_sanitized_retrieval_error(sessions):
    await _insert(sessions, _crowded_corpus())

    with pytest.raises(RetrievalError) as error:
        await _retriever(sessions, BrokenReranker()).search(
            "ZX9000", top_k=3, distance_threshold=1.0, filters=RetrievalFilters(), rerank=True
        )

    assert "sk-secret" not in str(error.value)


async def test_rerank_without_a_configured_reranker_is_a_retrieval_error():
    with pytest.raises(RetrievalError):
        await _retriever(lambda: None).search(
            "q", top_k=3, distance_threshold=1.0, filters=RetrievalFilters(), rerank=True
        )


async def test_an_unknown_search_mode_is_a_retrieval_error():
    with pytest.raises(RetrievalError):
        await _retriever(lambda: None).search(
            "q", top_k=3, distance_threshold=1.0, filters=RetrievalFilters(), search_mode="lexical"
        )
