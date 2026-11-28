"""`scripts/build_contradictions_s11.py`: corpus determinista, contradictorio de verdad e ingesta idempotente (Sesión 11).

La ingesta idempotente se comprueba contra el endpoint REAL `/embeddings/ingest` sobre `api-db` (embedder falso, sin
claves): el script llama por HTTP, así que se le pasa un `TestClient` (que es un `httpx.Client`). Se omite sin
`TEST_DATABASE_URL`.
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.dependencies import get_embedder
from app.foundation.persistence.database import get_session
from app.foundation.persistence.migrate import upgrade_to_head
from app.foundation.persistence.models import Chunk, Document
from app.generation.rag.schemas import Budget
from app.generation.rag.task_hours import weighted_consensus
from app.main import app
from tests._rag_fakes import FakeEmbedder

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_contradictions_s11 as script  # noqa: E402
from build_task_corpus import COMMON_MODULES, SECTOR_MODULES  # noqa: E402

URL = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(
    not URL or not URL.split("?")[0].endswith("test"), reason="TEST_DATABASE_URL de pruebas no definida"
)


def test_the_corpus_is_deterministic_and_every_project_is_a_valid_budget():
    first, second = script.generate_corpus(), script.generate_corpus()

    assert first == second and len(first) == 2 * len(script.CONTRADICTIONS)
    budgets = [Budget.model_validate(project) for project in first]
    assert len({b.budget_id for b in budgets}) == len(budgets)
    assert all(len(b.components) == 1 and b.components[0].module for b in budgets)


def test_each_task_matches_a_real_template_of_the_task_corpus():
    catalogs = [COMMON_MODULES, *SECTOR_MODULES.values()]
    templates = {name: module for catalog in catalogs for module, items in catalog.items() for name, *_ in items}

    for case in script.CONTRADICTIONS:
        assert templates.get(case.name) == case.module, case.name


@pytest.mark.parametrize("case", script.CONTRADICTIONS, ids=lambda case: case.key)
def test_every_pair_is_contradictory_enough_to_trigger_a_range(case):
    # Dos vecinos a la misma distancia: lo que verá la síntesis al estimar la tarea.
    consensus = weighted_consensus([(case.low_hours, 0.1), (case.high_hours, 0.1)])

    assert case.high_hours >= 2 * case.low_hours
    assert consensus.dispersion > 0.35  # umbral por defecto de `synthesis_contradiction_threshold`


def test_the_ingest_bodies_have_stable_source_paths_and_the_task_chunk_type():
    bodies = [script.ingest_body(project) for project in script.generate_corpus()]

    assert len({body["source_path"] for body in bodies}) == len(bodies)
    assert all(body["source_path"].startswith(script.SOURCE_PREFIX) for body in bodies)
    assert {(body["document_type"], body["chunk_type"]) for body in bodies} == {
        ("historical_task_contradiction", "historical_task")
    }


def test_generate_only_needs_no_network(capsys, tmp_path):
    out = tmp_path / "contradictions.json"

    assert script.main(["--generate-only", "--out", str(out)]) == 0

    assert out.exists() and "proyectos" in capsys.readouterr().out


@needs_db
def test_running_the_ingestion_twice_does_not_duplicate_anything(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", URL)
    upgrade_to_head()  # prueba síncrona: sin bucle en marcha, Alembic puede abrir el suyo

    async def counts() -> tuple[int, int]:
        engine = create_async_engine(URL, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                documents = (
                    await connection.execute(
                        select(func.count()).select_from(Document).where(Document.document_type == script.DOCUMENT_TYPE)
                    )
                ).scalar_one()
                chunks = (
                    await connection.execute(
                        select(func.count())
                        .select_from(Chunk)
                        .join(Document, Chunk.document_id == Document.id)
                        .where(Document.document_type == script.DOCUMENT_TYPE, Chunk.chunk_type == script.CHUNK_TYPE)
                    )
                ).scalar_one()
            return documents, chunks
        finally:
            await engine.dispose()

    async def clean() -> None:
        engine = create_async_engine(URL, poolclass=NullPool)
        async with engine.begin() as connection:
            await connection.execute(text("DELETE FROM documents WHERE document_type = :t"), {"t": script.DOCUMENT_TYPE})
        await engine.dispose()

    async def session_override():
        engine = create_async_engine(URL, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                yield session
        finally:
            await engine.dispose()

    asyncio.run(clean())
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder(1536)
    corpus = script.generate_corpus()
    try:
        with TestClient(app) as client:
            first = script.ingest_corpus(corpus, client)
            after_first = asyncio.run(counts())
            second = script.ingest_corpus(corpus, client)
            after_second = asyncio.run(counts())
    finally:
        app.dependency_overrides.clear()
        asyncio.run(clean())

    assert first == (len(corpus), 0) and second == (0, len(corpus))
    assert after_first == after_second and after_first[0] == len(corpus) and after_first[1] == len(corpus)
