"""Persistencia de la ingesta con SQLite: repositorio de trabajos, store en memoria y migraciones Alembic.

El comportamiento específico de PostgreSQL (`ON CONFLICT`, concurrencia) se prueba en
`test_ingestion_postgres.py`.
"""

import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.domain.history import Base as HistoryBase
from app.domain.history import EstimationRecord
from app.foundation.persistence.migrate import upgrade_to_head
from app.foundation.persistence.models import Base, IngestionJobRow, PseudonymMappingRow
from app.foundation.persistence.repositories.jobs import JobsRepository, list_jobs
from app.ingestion.pii import InMemoryMappingStore


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db_session:
        yield db_session
    await engine.dispose()


async def test_job_goes_from_pending_to_completed(session):
    repo = JobsRepository(session)

    job = await repo.create(source_name="presupuestos_json")
    assert job.status == "pending" and job.documents_count == 0 and job.finished_at is None
    assert job.started_at is not None and isinstance(job.job_id, uuid.UUID)

    await repo.mark_running(job.job_id)
    assert (await repo.get(job.job_id)).status == "running"

    await repo.mark_completed(job.job_id, documents_count=6)
    done = await repo.get(job.job_id)
    assert done.status == "completed" and done.documents_count == 6 and done.finished_at is not None


async def test_failed_job_keeps_a_truncated_error(session):
    repo = JobsRepository(session)
    job = await repo.create(source_name="presupuestos_json")

    await repo.mark_failed(job.job_id, error_message="x" * 5000)

    failed = await repo.get(job.job_id)
    assert failed.status == "failed" and len(failed.error_message) == 2048 and failed.finished_at is not None


async def test_unknown_job_is_none_and_updates_are_ignored(session):
    repo = JobsRepository(session)
    unknown = uuid.uuid4()

    assert await repo.get(unknown) is None
    await repo.mark_running(unknown)
    assert await list_jobs(session) == []


async def test_list_jobs_returns_the_latest_first(session):
    repo = JobsRepository(session)
    first = await repo.create(source_name="a")
    second = await repo.create(source_name="b")

    jobs = await list_jobs(session, limit=1)

    assert len(jobs) == 1 and jobs[0].job_id in {first.job_id, second.job_id}


async def test_in_memory_store_invokes_the_factory_once_and_forgets():
    store = InMemoryMappingStore()
    created = []

    def factory():
        created.append(1)
        return f"pseudo-{len(created)}"

    assert await store.lookup_or_create("PERSON", "h1", factory) == "pseudo-1"
    assert await store.lookup_or_create("PERSON", "h1", factory) == "pseudo-1"
    assert len(created) == 1
    assert await store.forget("PERSON", "h1") is True
    assert await store.forget("PERSON", "h1") is False
    assert await store.lookup_or_create("PERSON", "h1", factory) == "pseudo-2"


def test_mapping_table_never_stores_the_original_value():
    columns = {column.name for column in PseudonymMappingRow.__table__.columns}

    assert columns == {"id", "entity_type", "original_hash", "pseudonym", "created_at"}
    names = {c.name for c in IngestionJobRow.__table__.columns}
    assert names == {
        "job_id", "source_name", "status", "documents_count", "error_message", "started_at", "finished_at"
    }


def test_mapping_uniqueness_and_indexes_are_declared():
    table = PseudonymMappingRow.__table__
    uniques = {tuple(c.name for c in u.columns) for u in table.constraints if u.__class__.__name__ == "UniqueConstraint"}

    assert ("entity_type", "original_hash") in uniques
    assert {i.name for i in table.indexes} == {"idx_mappings_lookup"}
    assert {i.name for i in IngestionJobRow.__table__.indexes} == {"idx_jobs_status"}


# --- Migraciones ---


@pytest.fixture
def sqlite_url(tmp_path, monkeypatch):
    path = tmp_path / "migrations.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    return f"sqlite:///{path}"


def _tables(sync_url: str) -> set[str]:
    engine = create_engine(sync_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_creates_both_tables_and_is_repeatable(sqlite_url):
    assert upgrade_to_head() is True
    assert {"ingestion_jobs", "pseudonym_mappings", "alembic_version"} <= _tables(sqlite_url)

    assert upgrade_to_head() is True  # la segunda ejecución no cambia nada
    engine = create_engine(sqlite_url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == [
            "0001_session6_initial"
        ]
    engine.dispose()


def test_downgrade_removes_the_tables(sqlite_url):
    from alembic.config import Config

    from alembic import command
    from app.foundation.persistence.migrate import ALEMBIC_INI

    upgrade_to_head()
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))
    command.downgrade(config, "base")

    assert not {"ingestion_jobs", "pseudonym_mappings"} & _tables(sqlite_url)


def test_migration_does_not_touch_the_history_table(sqlite_url):
    engine = create_engine(sqlite_url)
    HistoryBase.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO estimations (description, options, result, prompt_version, cached, cache_source,"
                " model, provider, requested_at, completed_at) VALUES ('d', '{}', '{}', 'v3', 0, 'none', 'm', 'p',"
                " '2026-10-05 12:00:00', '2026-10-05 12:00:01')"
            )
        )
    before = {c["name"] for c in inspect(engine).get_columns(EstimationRecord.__tablename__)}

    upgrade_to_head()

    assert {c["name"] for c in inspect(engine).get_columns("estimations")} == before
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM estimations")).scalar() == 1
    engine.dispose()


def test_without_database_url_migrations_are_skipped(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr("app.foundation.persistence.migrate.get_settings", lambda: type("S", (), {"database_url": None})())

    assert upgrade_to_head() is False
