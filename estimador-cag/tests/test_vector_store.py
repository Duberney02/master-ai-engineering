"""Migración, ingesta transaccional y búsqueda semántica contra PostgreSQL + pgvector real (Sesión 8).

Se omite sin `TEST_DATABASE_URL`; `docker compose -f docker-compose.verify.yml run --rm api-test` la define con una
base efímera. Las pruebas vacían `documents` y `chunks`, así que exigen una base cuyo nombre termine en `test`.
"""

import asyncio
import os

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.dependencies import get_embedder
from app.foundation.persistence.database import get_session
from app.foundation.persistence.migrate import ALEMBIC_INI, upgrade_to_head
from app.foundation.persistence.models import Chunk, Document
from app.generation.rag.store.documents import search_statement
from app.main import app
from tests._rag_fakes import FakeEmbedder, make_budget

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL no definida"),
    pytest.mark.skipif(
        bool(URL) and not URL.split("?")[0].endswith("test"), reason="la base de pruebas debe terminar en 'test'"
    ),
]

DIMENSIONS = 1536
SECRET = "sk-provider-secret-detail"


class FailingEmbedder(FakeEmbedder):
    async def embed_many(self, chunks):
        raise RuntimeError(SECRET)

    async def embed_texts(self, texts):
        raise RuntimeError(SECRET)


@pytest.fixture
async def engine(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", URL)
    await asyncio.to_thread(upgrade_to_head)
    engine = create_async_engine(URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE documents, chunks RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
async def api(engine):
    """Cliente ASGI en el mismo bucle de eventos que el motor; `embedder` sustituible por prueba."""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    holder = {"embedder": FakeEmbedder(DIMENSIONS)}

    async def session_override():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_embedder] = lambda: holder["embedder"]
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            client.holder = holder
            client.sessions = sessions
            yield client
    finally:
        app.dependency_overrides.clear()


def _ingest_body(source_path: str = "data/budgets/b1.json", descriptions: list[str] | None = None, **budget) -> dict:
    budget_json = make_budget(budget.pop("budget_id", "B-1"), descriptions, **budget).model_dump()
    return {"source_path": source_path, "document_type": "historical_budget", "content": budget_json}


async def _counts(client) -> tuple[int, int]:
    async with client.sessions() as session:
        documents = (await session.execute(select(func.count()).select_from(Document))).scalar_one()
        chunks = (await session.execute(select(func.count()).select_from(Chunk))).scalar_one()
    return documents, chunks


# --- Migración -----------------------------------------------------------------------------------------------


async def test_migration_creates_the_schema_and_the_hnsw_indexes(engine):
    async with engine.connect() as connection:
        extensions = set((await connection.execute(text("SELECT extname FROM pg_extension"))).scalars())
        indexes = dict(
            (await connection.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'chunks'"))).all()
        )
        column = (
            await connection.execute(
                text("SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'")
            )
        ).scalar_one()
        invalid = (
            await connection.execute(text("SELECT count(*) FROM pg_index WHERE indrelid = 'chunks'::regclass AND NOT indisvalid"))
        ).scalar_one()

    assert "vector" in extensions and column == "vector(1536)"  # la columna sigue en full precision
    assert {"ix_chunks_document_id", "ix_chunks_chunk_type", "ix_chunks_metadata_gin"} <= set(indexes)
    assert "gin" in indexes["ix_chunks_metadata_gin"].lower()
    halfvec, full = indexes["chunks_embedding_halfvec_idx"], indexes["chunks_embedding_idx"]
    assert "USING hnsw" in halfvec and "halfvec_cosine_ops" in halfvec and "halfvec(1536)" in halfvec
    assert "m='16'" in halfvec and "ef_construction='128'" in halfvec
    assert "USING hnsw" in full and "vector_cosine_ops" in full and "halfvec" not in full
    assert invalid == 0


async def test_search_query_uses_the_halfvec_index(engine):
    statement = search_statement([0.1] * DIMENSIONS, 5)
    compiled = statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    async with engine.connect() as connection:
        await connection.execute(text("SET enable_seqscan = off"))  # tabla vacía: el planner preferiría el seq scan
        plan = " ".join((await connection.execute(text(f"EXPLAIN {compiled}"))).scalars())

    assert "Index Scan using chunks_embedding_halfvec_idx" in plan


async def test_the_unaligned_expression_ignores_the_halfvec_index(engine):
    """El antipatrón: `embedding <=> q` sin castear no puede usar el índice halfvec (usa el `vector`, si existe)."""
    vector = "[" + ",".join(["0.1"] * DIMENSIONS) + "]"
    async with engine.connect() as connection:
        await connection.execute(text("SET enable_seqscan = off"))
        plan = " ".join(
            (await connection.execute(text(f"EXPLAIN SELECT id FROM chunks ORDER BY embedding <=> '{vector}' LIMIT 5"))).scalars()
        )

    assert "chunks_embedding_halfvec_idx" not in plan


async def test_migration_downgrade_and_upgrade_are_reversible_and_alembic_check_is_clean(engine):
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))

    async def index_names() -> set[str]:
        async with engine.connect() as connection:
            return set((await connection.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'chunks'"))).scalars())

    await asyncio.to_thread(command.check, config)
    await asyncio.to_thread(command.downgrade, config, "0002_pgvector_documents_chunks")
    assert not {"chunks_embedding_idx", "chunks_embedding_halfvec_idx"} & await index_names()
    await asyncio.to_thread(command.upgrade, config, "head")
    assert {"chunks_embedding_idx", "chunks_embedding_halfvec_idx"} <= await index_names()
    await asyncio.to_thread(command.check, config)


async def test_deleting_a_document_cascades_to_its_chunks(api):
    await api.post("/embeddings/ingest", json=_ingest_body())

    async with api.sessions() as session:
        await session.execute(text("DELETE FROM documents"))
        await session.commit()

    assert await _counts(api) == (0, 0)


# --- POST /embeddings/ingest ---------------------------------------------------------------------------------


async def test_ingest_persists_the_document_and_one_chunk_per_component(api):
    body = _ingest_body(descriptions=["oauth tokens", "refresh flow", "rate limits"])

    response = await api.post("/embeddings/ingest", json=body)

    payload = response.json()
    assert response.status_code == 200
    assert payload["chunks_created"] == 3 and payload["embedding_dimension"] == DIMENSIONS
    assert payload["ingestion_time_ms"] >= 0
    assert await _counts(api) == (1, 3)
    async with api.sessions() as session:
        document = await session.get(Document, payload["document_id"])
        chunks = (await session.execute(select(Chunk).order_by(Chunk.id))).scalars().all()
    assert document.source_path == "data/budgets/b1.json" and document.metadata_["budget_id"] == "B-1"
    assert {chunk.chunk_type for chunk in chunks} == {"budget_component"}
    assert all(len(chunk.embedding) == DIMENSIONS and chunk.document_id == document.id for chunk in chunks)
    assert chunks[0].metadata_["component_id"] == "C-1"
    assert len(api.holder["embedder"].text_calls) == 0 and api.holder["embedder"].chunk_calls == 1  # un solo lote


async def test_ingesting_the_same_source_path_is_a_409_with_the_original_id(api):
    first = await api.post("/embeddings/ingest", json=_ingest_body())

    second = await api.post("/embeddings/ingest", json=_ingest_body())

    assert second.status_code == 409
    assert second.json() == {"detail": "Document already ingested", "document_id": first.json()["document_id"]}
    assert await _counts(api) == (1, 1)


async def test_embedder_failure_rolls_back_without_orphan_documents(api):
    api.holder["embedder"] = FailingEmbedder(DIMENSIONS)

    response = await api.post("/embeddings/ingest", json=_ingest_body())

    assert response.status_code == 500
    assert SECRET not in response.text
    assert await _counts(api) == (0, 0)
    # La ruta queda libre: reintentar con un embedder sano funciona.
    api.holder["embedder"] = FakeEmbedder(DIMENSIONS)
    assert (await api.post("/embeddings/ingest", json=_ingest_body())).status_code == 200


async def test_vectors_of_another_dimension_are_rejected_without_persisting(api):
    api.holder["embedder"] = FakeEmbedder(768)

    response = await api.post("/embeddings/ingest", json=_ingest_body())

    assert response.status_code == 500
    assert await _counts(api) == (0, 0)


async def test_invalid_ingest_body_is_a_422(api):
    response = await api.post("/embeddings/ingest", json={"document_type": "historical_budget", "content": {}})

    assert response.status_code == 422


# --- POST /search --------------------------------------------------------------------------------------------


async def _seed(api) -> None:
    topics = {
        "b1": ["oauth tokens refresh flow", "payment ledger reconciliation"],
        "b2": ["restaurant reservations mobile app", "kubernetes microservices migration"],
        "b3": ["react dashboard charts", "email notifications queue"],
    }
    for name, descriptions in topics.items():
        response = await api.post(
            "/embeddings/ingest", json=_ingest_body(f"data/{name}.json", descriptions, budget_id=name.upper())
        )
        assert response.status_code == 200


async def test_search_returns_the_k_closest_chunks_ordered_by_cosine_distance(api):
    await _seed(api)

    response = await api.post("/search", json={"query": "oauth tokens refresh flow", "k": 3})

    body = response.json()
    assert response.status_code == 200
    assert body["query"] == "oauth tokens refresh flow" and body["k"] == 3 and body["search_time_ms"] >= 0
    assert len(body["results"]) == 3
    distances = [item["distance"] for item in body["results"]]
    assert distances == sorted(distances)
    best = body["results"][0]
    assert "oauth tokens refresh flow" in best["content"] and distances[0] < distances[1]
    assert best["chunk_type"] == "budget_component" and best["metadata"]["budget_id"] == "B1"
    assert set(best) == {"chunk_id", "document_id", "chunk_type", "content", "distance", "metadata"}


async def test_search_k_limits_the_results(api):
    await _seed(api)

    response = await api.post("/search", json={"query": "kubernetes", "k": 1})

    assert len(response.json()["results"]) == 1
    assert "kubernetes" in response.json()["results"][0]["content"]


async def test_search_defaults_k_to_five(api):
    await _seed(api)

    response = await api.post("/search", json={"query": "anything"})

    assert response.json()["k"] == 5 and len(response.json()["results"]) == 5


@pytest.mark.parametrize("k", [0, 51])
async def test_search_k_out_of_range_is_a_422(api, k):
    assert (await api.post("/search", json={"query": "oauth", "k": k})).status_code == 422


async def test_search_on_an_empty_store_returns_no_results(api):
    response = await api.post("/search", json={"query": "oauth", "k": 5})

    assert response.status_code == 200 and response.json()["results"] == []


async def test_search_provider_failure_is_a_generic_500(api):
    api.holder["embedder"] = FailingEmbedder(DIMENSIONS)

    response = await api.post("/search", json={"query": "oauth", "k": 5})

    assert response.status_code == 500 and SECRET not in response.text
