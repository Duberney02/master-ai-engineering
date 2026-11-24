"""Expansión incremental del corpus (Sesión 11): `POST /embeddings/index/runs`, `GET .../jobs/{id}` y `GET .../stats`.

Integración contra PostgreSQL real (se omite sin `TEST_DATABASE_URL`; `api-test` la define con la base efímera). El
embedder es un doble determinista de 1536 dimensiones: no se llama a ningún proveedor.
"""

import asyncio
import os
import uuid

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.dependencies import get_corpus_expansion_service, get_rag_embedder
from app.foundation.persistence.database import get_session
from app.foundation.persistence.migrate import upgrade_to_head
from app.foundation.persistence.models import Chunk, Document, IngestionJobRow, TechnicalDocChunk, TranscriptChunk
from app.generation.rag.chunking.structural import JSONStructuralChunker
from app.generation.rag.corpus_expansion import FAILURE_MESSAGE, CorpusExpansionService
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
RUNS = "/embeddings/index/runs"
STATS = "/embeddings/index/stats"


class FailingEmbedder(FakeEmbedder):
    async def embed_many(self, chunks):
        raise RuntimeError(SECRET)


class FailOnSecondBudget(FakeEmbedder):
    """Embebe el primer presupuesto y falla en el segundo (progreso parcial)."""

    async def embed_many(self, chunks):
        if self.chunk_calls >= 1:
            raise RuntimeError(SECRET)
        return await super().embed_many(chunks)


@pytest.fixture
async def engine(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", URL)
    await asyncio.to_thread(upgrade_to_head)
    engine = create_async_engine(URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE documents, ingestion_jobs RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
async def api(engine):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    holder = {"embedder": FakeEmbedder(DIMENSIONS)}

    async def session_override():
        async with sessions() as session:
            yield session

    def service_override():
        return CorpusExpansionService(sessions, JSONStructuralChunker(), holder["embedder"])

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_corpus_expansion_service] = service_override
    app.dependency_overrides[get_rag_embedder] = lambda: holder["embedder"]
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            client.holder = holder
            client.sessions = sessions
            yield client
    finally:
        app.dependency_overrides.clear()


def batch(*budget_ids: str, **extra) -> dict:
    return {"budgets": [make_budget(budget_id).model_dump() for budget_id in budget_ids], **extra}


async def job(client, job_id: str) -> dict:
    response = await client.get(f"/embeddings/index/jobs/{job_id}")
    assert response.status_code == 200
    return response.json()


async def stats_by_collection(client) -> dict[str, dict]:
    body = (await client.get(STATS)).json()
    return {item["collection"]: item for item in body["collections"]}


# --- POST /runs ------------------------------------------------------------------------------------------------


async def test_a_run_answers_202_with_a_job_and_completes_in_the_background(api):
    response = await api.post(RUNS, json=batch("B-1", "B-2"))

    body = response.json()
    assert response.status_code == 202
    assert body["documents_total"] == 2 and body["status"] == "pending" and uuid.UUID(body["job_id"])
    finished = await job(api, body["job_id"])
    assert finished["status"] == "completed" and finished["documents_processed"] == 2
    assert finished["error_message"] is None and finished["finished_at"] is not None


async def test_the_chunks_are_embedded_and_stored_in_the_budget_collection(api):
    await api.post(RUNS, json=batch("B-1"))

    async with api.sessions() as session:
        documents = (await session.execute(select(Document))).scalars().all()
        chunks = (await session.execute(select(Chunk))).scalars().all()
    assert [(d.source_path, d.document_type) for d in documents] == [("index_run#B-1", "historical_budget")]
    assert chunks and all(len(chunk.embedding) == DIMENSIONS and chunk.chunk_type == "budget_component" for chunk in chunks)


async def test_document_type_and_chunk_type_come_from_the_request(api):
    await api.post(RUNS, json=batch("B-1", document_type="historical_task_breakdown", chunk_type="historical_task"))

    async with api.sessions() as session:
        document_type = (await session.execute(select(Document.document_type))).scalar_one()
        chunk_types = set((await session.execute(select(Chunk.chunk_type))).scalars())
    assert document_type == "historical_task_breakdown" and chunk_types == {"historical_task"}


async def test_a_batch_with_one_duplicate_skips_it_and_indexes_the_other_two(api):
    first = await api.post(RUNS, json=batch("B-1"))
    assert (await job(api, first.json()["job_id"]))["documents_processed"] == 1

    second = await api.post(RUNS, json=batch("B-1", "B-2", "B-3"))

    finished = await job(api, second.json()["job_id"])
    assert second.json()["documents_total"] == 3
    assert finished["status"] == "completed" and finished["documents_processed"] == 2
    async with api.sessions() as session:
        count = (await session.execute(select(func.count()).select_from(Document))).scalar_one()
    assert count == 3  # B-1 no se duplicó


async def test_a_budget_already_ingested_by_another_path_is_also_skipped(api):
    async with api.sessions() as session:
        session.add(
            Document(
                source_path="data/budgets_sample.json#B-9",
                document_type="historical_budget",
                metadata_={"budget_id": "B-9"},
            )
        )
        await session.commit()

    response = await api.post(RUNS, json=batch("B-9", "B-10"))

    assert (await job(api, response.json()["job_id"]))["documents_processed"] == 1


async def test_resending_the_same_batch_is_idempotent(api):
    await api.post(RUNS, json=batch("B-1", "B-2"))
    again = await api.post(RUNS, json=batch("B-1", "B-2"))

    finished = await job(api, again.json()["job_id"])
    assert finished["status"] == "completed" and finished["documents_processed"] == 0
    assert (await stats_by_collection(api))["budget"]["documents"] == 2


async def test_a_provider_failure_marks_the_job_failed_with_a_sanitized_message(api):
    api.holder["embedder"] = FailingEmbedder(DIMENSIONS)

    response = await api.post(RUNS, json=batch("B-1"))

    assert response.status_code == 202  # el fallo ocurre en segundo plano
    failed = await job(api, response.json()["job_id"])
    assert failed["status"] == "failed" and failed["error_message"] == FAILURE_MESSAGE
    assert SECRET not in str(failed) and failed["finished_at"] is not None


async def test_a_failure_keeps_the_documents_already_confirmed(api):
    api.holder["embedder"] = FailOnSecondBudget(DIMENSIONS)

    response = await api.post(RUNS, json=batch("B-1", "B-2"))

    failed = await job(api, response.json()["job_id"])
    assert failed["status"] == "failed" and failed["documents_processed"] == 1
    assert (await stats_by_collection(api))["budget"]["documents"] == 1


async def test_without_an_embedder_the_answer_is_a_generic_500_and_no_job_is_created(api):
    app.dependency_overrides[get_rag_embedder] = lambda: None

    response = await api.post(RUNS, json=batch("B-1"))

    assert response.status_code == 500
    assert response.json() == {"detail": "No se pudo iniciar la expansión del corpus."}
    async with api.sessions() as session:
        assert (await session.execute(select(func.count()).select_from(IngestionJobRow))).scalar_one() == 0


@pytest.mark.parametrize(
    "body",
    [
        {"budgets": []},
        {},
        {"budgets": [{"budget_id": "x"}]},
        {"budgets": [make_budget("B-1").model_dump()], "chunk_type": "Not Valid"},
        {"budgets": [make_budget(f"B-{i}").model_dump() for i in range(51)]},
    ],
)
async def test_an_invalid_batch_is_422_and_creates_no_job(api, body):
    assert (await api.post(RUNS, json=body)).status_code == 422
    async with api.sessions() as session:
        assert (await session.execute(select(func.count()).select_from(IngestionJobRow))).scalar_one() == 0


# --- GET /jobs/{id} --------------------------------------------------------------------------------------------


async def test_an_unknown_job_is_404(api):
    response = await api.get(f"/embeddings/index/jobs/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_a_malformed_job_id_is_422(api):
    assert (await api.get("/embeddings/index/jobs/not-a-uuid")).status_code == 422


async def test_the_job_view_exposes_the_documented_fields(api):
    response = await api.post(RUNS, json=batch("B-1"))

    view = await job(api, response.json()["job_id"])
    assert set(view) == {"job_id", "status", "documents_processed", "error_message", "started_at", "finished_at"}


# --- GET /stats ------------------------------------------------------------------------------------------------


async def test_stats_report_documents_chunks_and_hnsw_per_collection(api):
    async with api.sessions() as session:
        document = Document(source_path="t.json::T-1", document_type="meeting_transcript", metadata_={})
        session.add(document)
        await session.flush()
        session.add(TranscriptChunk(document_id=document.id, chunk_type="meeting_segment", content="kick-off"))
        session.add(TechnicalDocChunk(document_id=document.id, chunk_type="doc_section", content="api"))
        session.add(TechnicalDocChunk(document_id=document.id, chunk_type="doc_section", content="api 2"))
        await session.commit()

    body = (await api.get(STATS)).json()

    by_collection = {item["collection"]: item for item in body["collections"]}
    assert list(by_collection) == ["budget", "transcript", "technical_doc"]
    assert (by_collection["transcript"]["documents"], by_collection["transcript"]["chunks"]) == (1, 1)
    assert (by_collection["technical_doc"]["documents"], by_collection["technical_doc"]["chunks"]) == (1, 2)
    assert by_collection["budget"]["chunks"] == 0
    assert all(item["hnsw_index"] is True for item in body["collections"])
    assert body["total_chunks"] == 3


async def test_the_corpus_growth_is_visible_in_the_stats(api):
    before = (await stats_by_collection(api))["budget"]

    await api.post(RUNS, json=batch("B-1", "B-2"))

    after = (await stats_by_collection(api))["budget"]
    assert after["documents"] == before["documents"] + 2
    assert after["chunks"] > before["chunks"]


async def test_new_chunks_are_searchable_without_reindexing(api):
    await api.post(RUNS, json=batch("B-1"))

    async with api.sessions() as session:
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        nearest = (
            await session.execute(
                text(
                    "SELECT count(*) FROM (SELECT id FROM chunks "
                    "ORDER BY embedding::halfvec(1536) <=> CAST(:q AS halfvec(1536)) LIMIT 3) t"
                ),
                {"q": "[" + ",".join(["1"] + ["0"] * 1535) + "]"},
            )
        ).scalar_one()
    assert nearest >= 1
