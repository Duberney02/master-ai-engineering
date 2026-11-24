"""`scripts/build_multi_index_corpus.py` y el golden set de recuperación (Sesión 10).

Las pruebas de datos no necesitan base; la de ingesta ejecuta el script DOS veces contra `api-db` con un embedder falso y
comprueba que la segunda no duplica nada. Se omite sin `TEST_DATABASE_URL`.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.foundation.persistence.migrate import upgrade_to_head
from app.foundation.persistence.models import Document, TechnicalDocChunk, TranscriptChunk
from app.generation.rag.retrieval.collections import Collection, spec_for
from tests._rag_fakes import FakeEmbedder

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_multi_index_corpus import (  # noqa: E402
    PLANS,
    doc_chunks,
    ingest_collection,
    transcript_chunks,
)

URL = os.getenv("TEST_DATABASE_URL")
TRANSCRIPTS = json.loads((ROOT / "data" / "transcripts_sample.json").read_text(encoding="utf-8"))
DOCS = json.loads((ROOT / "data" / "technical_docs_sample.json").read_text(encoding="utf-8"))
BUDGETS = json.loads((ROOT / "data" / "budgets_sample.json").read_text(encoding="utf-8"))
GOLDEN = json.loads((ROOT / "evals" / "golden_retrieval.json").read_text(encoding="utf-8"))


# --- Datos ---------------------------------------------------------------------------------------------------


def test_each_transcript_segment_becomes_a_chunk_with_the_collection_schema():
    transcript = TRANSCRIPTS[0]

    chunks = transcript_chunks(transcript)

    assert len(chunks) == len(transcript["segments"])
    first = chunks[0]
    assert first.metadata["transcript_id"] == transcript["transcript_id"]
    assert first.metadata["meeting_date"] == transcript["meeting_date"] and "speakers" in first.metadata
    assert transcript["project"] in first.text and first.token_count > 0
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)


def test_each_doc_section_becomes_a_chunk_with_its_version():
    doc = DOCS[0]

    chunks = doc_chunks(doc)

    assert len(chunks) == len(doc["sections"])
    assert chunks[0].metadata["doc_id"] == doc["doc_id"] and chunks[0].metadata["version"] == doc["version"]
    assert doc["title"] in chunks[0].text


def test_the_meeting_dates_span_several_years_so_the_decay_has_something_to_show():
    years = {transcript["meeting_date"][:4] for transcript in TRANSCRIPTS}

    assert len(years) >= 3
    assert len({doc["version"] for doc in DOCS}) >= 3  # versiones distintas para probar el filtro duro


def test_the_plans_cover_the_two_new_collections_with_their_registry_chunk_type():
    assert [plan.collection for plan in PLANS] == [Collection.TRANSCRIPT, Collection.TECHNICAL_DOC]
    assert [plan.id_key for plan in PLANS] == [spec_for(plan.collection).source_id_key for plan in PLANS]


# --- Golden set ----------------------------------------------------------------------------------------------


def test_every_golden_query_has_at_least_one_relevant_source_id():
    assert GOLDEN["queries"], "el golden set no puede estar vacío"
    for query in GOLDEN["queries"]:
        assert query["relevant_source_ids"], query["id"]
        assert query["query"].strip() and query["note"].strip()


def test_golden_ids_are_unique_and_every_annotated_source_exists_in_the_corpus():
    corpus = (
        {budget["budget_id"] for budget in BUDGETS}
        | {transcript["transcript_id"] for transcript in TRANSCRIPTS}
        | {doc["doc_id"] for doc in DOCS}
    )
    ids = [query["id"] for query in GOLDEN["queries"]]

    assert len(set(ids)) == len(ids)
    for query in GOLDEN["queries"]:
        assert set(query["relevant_source_ids"]) <= corpus, query["id"]


def test_the_golden_set_has_single_index_and_cross_collection_queries():
    def collections(query) -> set[str]:
        return {
            "transcript" if source.startswith("TR-") else "technical_doc" if source.startswith("DOC-") else "budget"
            for source in query["relevant_source_ids"]
        }

    spans = [len(collections(query)) for query in GOLDEN["queries"]]

    assert 1 in spans and max(spans) >= 2
    assert GOLDEN["k"] == 5


# --- Ingesta idempotente -----------------------------------------------------------------------------------


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


async def _run(sessions, embedder) -> list[tuple[int, int]]:
    results = []
    for plan in PLANS:
        items = json.loads((ROOT / plan.source_file).read_text(encoding="utf-8"))
        results.append(await ingest_collection(plan, items, session_factory=sessions, embedder=embedder))
    return results


async def _counts(sessions) -> tuple[int, int, int]:
    counts = []
    async with sessions() as session:
        for table in (Document, TranscriptChunk, TechnicalDocChunk):
            counts.append((await session.execute(select(func.count()).select_from(table))).scalar_one())
    return tuple(counts)


async def test_running_the_script_twice_does_not_duplicate_anything(sessions):
    embedder = FakeEmbedder(1536)
    expected_transcript_chunks = sum(len(t["segments"]) for t in TRANSCRIPTS)
    expected_doc_chunks = sum(len(d["sections"]) for d in DOCS)

    first = await _run(sessions, embedder)
    after_first = await _counts(sessions)
    second = await _run(sessions, embedder)

    assert first == [(len(TRANSCRIPTS), 0), (len(DOCS), 0)]
    assert second == [(0, len(TRANSCRIPTS)), (0, len(DOCS))]
    assert after_first == (len(TRANSCRIPTS) + len(DOCS), expected_transcript_chunks, expected_doc_chunks)
    assert await _counts(sessions) == after_first
    assert embedder.chunk_calls == len(TRANSCRIPTS) + len(DOCS)  # la segunda pasada ni siquiera embebe


async def test_chunks_are_stored_with_the_collection_chunk_type_and_metadata(sessions):
    await _run(sessions, FakeEmbedder(1536))

    async with sessions() as session:
        transcript = (await session.execute(select(TranscriptChunk).limit(1))).scalar_one()
        doc = (await session.execute(select(TechnicalDocChunk).limit(1))).scalar_one()
        documents = set(
            (await session.execute(select(Document.document_type).distinct())).scalars()
        )

    assert transcript.chunk_type == spec_for(Collection.TRANSCRIPT).chunk_type
    assert {"transcript_id", "meeting_date", "speakers", "chunk_id"} <= set(transcript.metadata_)
    assert doc.chunk_type == spec_for(Collection.TECHNICAL_DOC).chunk_type
    assert {"doc_id", "version", "chunk_id"} <= set(doc.metadata_)
    assert documents == {"meeting_transcript", "technical_doc"}


async def test_an_embedder_with_the_wrong_dimension_stores_nothing(sessions):
    with pytest.raises(ValueError):
        await _run(sessions, FakeEmbedder(32))

    assert await _counts(sessions) == (0, 0, 0)
