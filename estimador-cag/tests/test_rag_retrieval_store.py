"""Recuperación filtrada con umbral (Sesión 9): SQL generado y búsqueda contra PostgreSQL + pgvector real.

Las pruebas de integración se omiten sin `TEST_DATABASE_URL` (`api-test` la define con la base efímera `api-db`).
Los embeddings se construyen a mano para controlar la distancia coseno: con la consulta `e0`, un chunk
`cos·e0 + sin·e1` está a distancia `1 - cos`.
"""

import asyncio
import math
import os
import re

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.foundation.persistence.migrate import upgrade_to_head
from app.foundation.persistence.models import Chunk, Document
from app.generation.rag.errors import EmbedderUnavailableError, RetrievalError
from app.generation.rag.retriever import (
    ChunkRetriever,
    RetrievalFilters,
    candidates_statement,
    filtered_search_statement,
)

DIMENSIONS = 1536
URL = os.getenv("TEST_DATABASE_URL")


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def _vector(cosine: float) -> list[float]:
    vector = [0.0] * DIMENSIONS
    vector[0], vector[1] = cosine, math.sqrt(max(0.0, 1 - cosine * cosine))
    return vector


class QueryEmbedder:
    """La consulta siempre es `e0`."""

    async def embed_one(self, text_: str) -> list[float]:
        return _vector(1.0)


# --- SQL ---------------------------------------------------------------------------------------------------------


def test_filtered_statement_keeps_the_halfvec_index_expression():
    filters = RetrievalFilters(sectors=["finance"], project_year_min=2022, project_year_max=2024, chunk_types=["x"])
    sql = _sql(filtered_search_statement([0.1] * DIMENSIONS, 5, 0.6, filters))

    assert "ORDER BY CAST(chunks.embedding AS HALFVEC(1536)) <=>" in sql
    assert "chunks.embedding <=>" not in sql  # sin castear no usaría el índice halfvec
    where = re.split(r"\sORDER BY\s", re.split(r"\sWHERE\s", sql, maxsplit=1)[1], maxsplit=1)[0]
    assert "chunks.metadata ->>" in where and " IN (" in where  # filtros JSONB dentro de la misma consulta
    assert "AS INTEGER) >=" in where and "AS INTEGER) <=" in where
    assert "chunks.chunk_type IN" in where and "HALFVEC(1536)) <=>" in where and "LIMIT" in sql


def test_no_filters_only_require_an_embedding():
    sql = _sql(candidates_statement(RetrievalFilters()))

    assert "chunks.embedding IS NOT NULL" in sql and "metadata" not in sql


async def test_without_embedder_the_retriever_reports_it():
    retriever = ChunkRetriever(lambda: None, None, ef_search=40)

    with pytest.raises(EmbedderUnavailableError):
        await retriever.search("q", top_k=5, distance_threshold=0.6, filters=RetrievalFilters())


async def test_embedder_and_database_failures_are_retrieval_errors():
    class Boom:
        async def embed_one(self, text_):
            raise RuntimeError("provider down")

    with pytest.raises(RetrievalError):
        await ChunkRetriever(lambda: None, Boom(), ef_search=40).search(
            "q", top_k=5, distance_threshold=0.6, filters=RetrievalFilters()
        )

    def broken_factory():
        raise RuntimeError("DATABASE_URL is not configured")

    with pytest.raises(RetrievalError):
        await ChunkRetriever(broken_factory, QueryEmbedder(), ef_search=40).search(
            "q", top_k=5, distance_threshold=0.6, filters=RetrievalFilters()
        )


# --- Integración ---------------------------------------------------------------------------------------------------

CORPUS = [
    # (budget_id, sector, year, chunk_type, coseno con la consulta)
    ("FIN-1", "finance", 2024, "budget_component", 0.95),
    ("FIN-2", "finance", 2022, "historical_task", 0.85),
    ("HLT-1", "healthcare", 2024, "budget_component", 0.97),
    ("LOG-1", "logistics", 2023, "budget_component", 0.50),
    ("EDU-1", "education", 2021, "budget_component", 0.10),
]


@pytest.fixture
async def sessions(monkeypatch):
    if not URL:
        pytest.skip("TEST_DATABASE_URL no definida")
    if not URL.split("?")[0].endswith("test"):
        pytest.skip("la base de pruebas debe terminar en 'test' (se vacían documents y chunks)")
    monkeypatch.setenv("DATABASE_URL", URL)
    await asyncio.to_thread(upgrade_to_head)
    engine = create_async_engine(URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE documents, chunks RESTART IDENTITY CASCADE"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        for budget_id, sector, year, chunk_type, cosine in CORPUS:
            document = Document(source_path=f"test/{budget_id}.json", document_type="historical_budget", metadata_={})
            session.add(document)
            await session.flush()
            session.add(
                Chunk(
                    document_id=document.id,
                    chunk_type=chunk_type,
                    content=f"{budget_id} component",
                    embedding=_vector(cosine),
                    metadata_={"budget_id": budget_id, "client_sector": sector, "year": year},
                )
            )
        await session.commit()
    yield factory
    await engine.dispose()


def _retriever(sessions) -> ChunkRetriever:
    return ChunkRetriever(sessions, QueryEmbedder(), ef_search=40)


async def test_sector_filter_only_returns_that_sector(sessions):
    result = await _retriever(sessions).search(
        "payments", top_k=10, distance_threshold=1.0, filters=RetrievalFilters(sectors=["finance"])
    )

    assert [chunk.budget_id for chunk in result.chunks] == ["FIN-1", "FIN-2"]
    assert {chunk.sector for chunk in result.chunks} == {"finance"}
    assert result.candidates_evaluated == 2 and result.low_confidence is False


async def test_threshold_keeps_only_close_candidates_in_distance_order(sessions):
    # Distancias ≈ 0.03 (HLT-1), 0.05 (FIN-1), 0.15 (FIN-2), 0.5 (LOG-1), 0.9 (EDU-1): solo dos ≤ 0.1.
    result = await _retriever(sessions).search("payments", top_k=5, distance_threshold=0.1, filters=RetrievalFilters())

    assert [chunk.budget_id for chunk in result.chunks] == ["HLT-1", "FIN-1"]
    assert result.chunks[0].distance <= result.chunks[1].distance <= 0.1
    assert result.candidates_evaluated == 5
    first = result.chunks[0]
    assert (first.sector, first.project_year, first.chunk_type) == ("healthcare", 2024, "budget_component")
    assert first.document_id is not None and first.id is not None


async def test_year_and_chunk_type_filters(sessions):
    by_year = await _retriever(sessions).search(
        "q", top_k=10, distance_threshold=2.0, filters=RetrievalFilters(project_year_min=2023, project_year_max=2024)
    )
    by_type = await _retriever(sessions).search(
        "q", top_k=10, distance_threshold=2.0, filters=RetrievalFilters(chunk_types=["historical_task"])
    )

    assert {chunk.budget_id for chunk in by_year.chunks} == {"FIN-1", "HLT-1", "LOG-1"}
    assert [chunk.budget_id for chunk in by_type.chunks] == ["FIN-2"]


async def test_top_k_limits_the_results(sessions):
    result = await _retriever(sessions).search("q", top_k=2, distance_threshold=2.0, filters=RetrievalFilters())

    assert len(result.chunks) == 2 and result.candidates_evaluated == 5


async def test_soft_fail_when_nothing_crosses_the_threshold(sessions):
    result = await _retriever(sessions).search("q", top_k=5, distance_threshold=0.01, filters=RetrievalFilters())

    assert result.chunks == [] and result.low_confidence is True and result.candidates_evaluated == 5


async def test_filtered_query_can_use_the_halfvec_index(sessions):
    statement = filtered_search_statement(_vector(1.0), 5, 0.6, RetrievalFilters(sectors=["finance"]))
    compiled = statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    async with sessions() as session:
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = " ".join((await session.execute(text(f"EXPLAIN {compiled}"))).scalars())

    assert "chunks_embedding_halfvec_idx" in plan
