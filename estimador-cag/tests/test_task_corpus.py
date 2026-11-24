"""`scripts/build_task_corpus.py`: corpus de tareas válido, determinista e ingesta idempotente (Sesión 9).

La prueba de integración ingesta el corpus dos veces a través de la API real contra `api-db` (embedder falso) y
comprueba que la segunda pasada no duplica nada. Se omite sin `TEST_DATABASE_URL`.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.dependencies import get_embedder
from app.foundation.persistence.database import get_session
from app.foundation.persistence.migrate import upgrade_to_head
from app.foundation.persistence.models import Chunk, Document
from app.generation.rag.schemas import Budget, IngestRequest
from app.main import app
from tests._rag_fakes import FakeEmbedder

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from build_task_corpus import (  # noqa: E402
    CHUNK_TYPE,
    DOCUMENT_TYPE,
    generate_corpus,
    ingest_body,
    ingest_corpus,
    main,
)

URL = os.getenv("TEST_DATABASE_URL")


def test_generated_projects_are_valid_ingest_requests():
    corpus = generate_corpus(count=6, seed=1)

    for project in corpus:
        request = IngestRequest.model_validate(ingest_body(project))
        budget = Budget.model_validate(project)
        assert request.chunk_type == CHUNK_TYPE and request.document_type == DOCUMENT_TYPE
        assert all(component.module for component in budget.components)
        assert budget.total_estimated_hours == sum(component.estimated_hours for component in budget.components)


def test_generation_is_deterministic_and_task_granular():
    corpus = generate_corpus(count=12, seed=90)

    assert corpus == generate_corpus(count=12, seed=90)
    assert corpus != generate_corpus(count=12, seed=91)
    assert len({project["budget_id"] for project in corpus}) == 12
    assert sum(len(project["components"]) for project in corpus) >= 120


def test_ingest_counts_created_and_already_present():
    seen: set[str] = set()

    def handler(request: httpx.Request) -> httpx.Response:
        source_path = json.loads(request.content)["source_path"]
        if source_path in seen:
            return httpx.Response(409, json={"detail": "Document already ingested", "document_id": 1})
        seen.add(source_path)
        return httpx.Response(200, json={"document_id": len(seen)})

    corpus = generate_corpus(count=3, seed=5)
    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api") as client:
        assert ingest_corpus(corpus, client) == (3, 0)
        assert ingest_corpus(corpus, client) == (0, 3)


def test_ingest_aborts_on_an_unexpected_status():
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)), base_url="http://api") as client:
        with pytest.raises(RuntimeError, match="HTTP 500"):
            ingest_corpus(generate_corpus(count=1), client)


def test_generate_only_writes_the_json(tmp_path, capsys):
    out = tmp_path / "corpus.json"

    assert main(["--generate-only", "--count", "2", "--out", str(out)]) == 0

    assert out.exists() and "2 proyectos" in capsys.readouterr().out


async def test_ingesting_twice_through_the_api_does_not_duplicate(monkeypatch):
    if not URL or not URL.split("?")[0].endswith("test"):
        pytest.skip("TEST_DATABASE_URL no definida (o no termina en 'test')")
    monkeypatch.setenv("DATABASE_URL", URL)
    await asyncio.to_thread(upgrade_to_head)
    engine = create_async_engine(URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE documents, chunks RESTART IDENTITY CASCADE"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def session_override():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder(1536)
    corpus = generate_corpus(count=3, seed=90)
    bodies = [ingest_body(project) for project in corpus]
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = [(await client.post("/embeddings/ingest", json=body)).status_code for body in bodies]
            second = [(await client.post("/embeddings/ingest", json=body)).status_code for body in bodies]
        async with sessions() as session:
            documents = (await session.execute(select(func.count()).select_from(Document))).scalar_one()
            chunk_types = set((await session.execute(select(Chunk.chunk_type).distinct())).scalars())
            chunks = (await session.execute(select(func.count()).select_from(Chunk))).scalar_one()
            module = (await session.execute(select(Chunk.metadata_["module"].astext).limit(1))).scalar_one()
    finally:
        await engine.dispose()

    assert first == [200, 200, 200] and second == [409, 409, 409]
    assert documents == 3 and chunks == sum(len(project["components"]) for project in corpus)
    assert chunk_types == {CHUNK_TYPE} and module
