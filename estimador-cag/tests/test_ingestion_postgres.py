"""Integración con PostgreSQL real; se omite salvo que `TEST_DATABASE_URL` esté definida.

Se ejecuta desde Docker contra el servicio `postgres` del Compose raíz, por ejemplo:
TEST_DATABASE_URL=postgresql+asyncpg://estimator:estimator-dev@postgres:5432/estimator
Aplica las migraciones reales y limpia solo las filas que crea.
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.dependencies import build_pseudonymizer
from app.ingestion.catalog.loader import load_catalog
from app.ingestion.loaders.filesystem import FileSystemLoader
from app.ingestion.orchestrator import ingest_source
from app.ingestion.parsers.registry import default_registry
from app.persistence.migrate import upgrade_to_head
from app.persistence.models import PseudonymMappingRow
from app.persistence.repositories.jobs import JobsRepository
from app.persistence.repositories.mappings import MappingsRepository
from tests._fakes import openai_settings

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL no definida")


@pytest.fixture
async def sessions(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", URL)
    await asyncio.to_thread(upgrade_to_head)
    engine = create_async_engine(URL)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_migrations_create_the_tables_and_keep_the_history_table(sessions):
    async with sessions() as session:
        tables = set(
            (await session.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))).scalars()
        )
        version = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar()

    assert {"ingestion_jobs", "pseudonym_mappings", "alembic_version"} <= tables
    assert version == "0001_session6_initial"


async def test_job_lifecycle_and_native_uuid_column(sessions):
    async with sessions() as session:
        repo = JobsRepository(session)
        job = await repo.create(source_name="presupuestos_json")
        await repo.mark_running(job.job_id)
        await repo.mark_completed(job.job_id, documents_count=6)

        done = await repo.get(job.job_id)
        column_type = (
            await session.execute(
                text("SELECT data_type FROM information_schema.columns WHERE table_name='ingestion_jobs' AND column_name='job_id'")
            )
        ).scalar()
        await session.execute(text("DELETE FROM ingestion_jobs WHERE job_id = :id"), {"id": job.job_id})
        await session.commit()

    assert done.status == "completed" and done.documents_count == 6 and done.started_at.tzinfo is not None
    assert column_type == "uuid"


async def test_concurrent_lookup_or_create_converges_on_one_row(sessions):
    entity = f"TEST_{uuid.uuid4().hex[:8]}"

    async def call(n: int) -> str:
        async with sessions() as session:
            mapping = await MappingsRepository(session).lookup_or_create(entity, "hash-1", lambda: f"seudonimo-{n}")
            return mapping.pseudonym

    try:
        results = await asyncio.gather(*(call(n) for n in range(8)))
        async with sessions() as session:
            rows = (
                await session.execute(text("SELECT count(*) FROM pseudonym_mappings WHERE entity_type = :e"), {"e": entity})
            ).scalar()
    finally:
        async with sessions() as session:
            await session.execute(text("DELETE FROM pseudonym_mappings WHERE entity_type = :e"), {"e": entity})
            await session.commit()

    assert len(set(results)) == 1 and rows == 1


async def test_unique_constraint_rejects_a_duplicate_and_forget_removes_it(sessions):
    entity = f"TEST_{uuid.uuid4().hex[:8]}"
    async with sessions() as session:
        repo = MappingsRepository(session)
        first = await repo.lookup_or_create(entity, "h", lambda: "uno")
        assert (await repo.lookup_or_create(entity, "h", lambda: "otro")).pseudonym == first.pseudonym == "uno"

        session.add(PseudonymMappingRow(entity_type=entity, original_hash="h", pseudonym="dup"))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        assert await repo.forget(entity, "h") is True
        assert await repo.forget(entity, "h") is False
        assert await repo.lookup(entity, "h") is None


async def test_pseudonymizer_with_the_postgres_store_stores_hash_not_text(sessions, monkeypatch):
    monkeypatch.setattr("app.dependencies.get_settings", lambda: openai_settings(pseudonym_hash_salt="sal-prueba"))
    text_in = "Laura Fernández revisó BUDGET-2024-0001."

    async with sessions() as session:
        pseudonymizer = build_pseudonymizer(session)
        first = await pseudonymizer.pseudonymize(text_in)
        second = await pseudonymizer.pseudonymize(text_in)
        stored = (
            await session.execute(
                text("SELECT entity_type, original_hash, pseudonym FROM pseudonym_mappings WHERE original_hash = ANY(:h)"),
                {"h": [m.original_hash for m in first.applied]},
            )
        ).all()
        for mapping in first.applied:
            await MappingsRepository(session).forget(mapping.entity_type, mapping.original_hash)

    assert [m.pseudonym for m in first.applied] == [m.pseudonym for m in second.applied]
    assert "Laura Fernández" not in first.pseudonymized_text and "BUDGET-2024-0001" not in first.pseudonymized_text
    assert stored and all("Laura" not in cell and "BUDGET-2024-0001" not in cell for row in stored for cell in row)


async def test_real_ingestion_run_is_tracked_in_postgres(sessions):
    catalog = load_catalog("data/catalog/catalog.yaml")
    async with sessions() as session:
        repo = JobsRepository(session)
        job = await repo.create(source_name="presupuestos_json")

        documents = await ingest_source(
            catalog=catalog,
            source_name="presupuestos_json",
            loader=FileSystemLoader("data/seed"),
            registry=default_registry(),
            jobs_repo=repo,
            job_id=job.job_id,
        )
        done = await repo.get(job.job_id)
        await session.execute(text("DELETE FROM ingestion_jobs WHERE job_id = :id"), {"id": job.job_id})
        await session.commit()

    assert len(documents) == 6 and done.status == "completed" and done.documents_count == 6
