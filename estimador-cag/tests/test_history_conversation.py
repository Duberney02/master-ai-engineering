"""Asociación de estimaciones con su conversación y migración aditiva del esquema."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.services.history import EstimationHistory
from tests._fakes import openai_settings
from tests.test_history import NOW, _outcome, _request

SNAPSHOT = {
    "project_name": "Orion",
    "assumed_team_size": 4,
    "mentioned_technologies": ["FastAPI"],
    "agreed_scope": None,
}


def _engine():
    return create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})


@pytest.fixture
async def engine():
    engine = _engine()
    yield engine
    await engine.dispose()


async def test_estimation_is_saved_with_conversation_and_metadata_snapshot(engine):
    history = EstimationHistory(openai_settings(), engine=engine)

    saved_id = await history.save(_request(), _outcome(), NOW, conversation_id="c-1", metadata_snapshot=SNAPSHOT)
    detail = await history.get(saved_id)

    assert detail.conversation_id == "c-1" and detail.metadata_snapshot == SNAPSHOT


async def test_estimation_without_conversation_keeps_both_fields_empty(engine):
    history = EstimationHistory(openai_settings(), engine=engine)

    detail = await history.get(await history.save(_request(), _outcome(), NOW))

    assert detail.conversation_id is None and detail.metadata_snapshot is None


async def test_latest_for_conversation_returns_the_most_recent_one_of_that_conversation(engine):
    history = EstimationHistory(openai_settings(), engine=engine)
    await history.save(_request(), _outcome(), NOW, conversation_id="c-1", metadata_snapshot={"project_name": "viejo"})
    newest = await history.save(
        _request(), _outcome(), NOW + timedelta(minutes=2), conversation_id="c-1", metadata_snapshot=SNAPSHOT
    )
    await history.save(_request(), _outcome(), NOW + timedelta(minutes=5), conversation_id="c-2")

    latest = await history.latest_for_conversation("c-1")

    assert latest.id == newest and latest.metadata_snapshot == SNAPSHOT
    assert await history.latest_for_conversation("desconocida") is None


async def test_database_created_before_the_change_gets_the_new_columns_without_losing_rows(engine):
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TABLE estimations (id INTEGER PRIMARY KEY AUTOINCREMENT, description TEXT NOT NULL, "
                "options JSON NOT NULL, result JSON NOT NULL, prompt_version VARCHAR(10) NOT NULL, "
                "cached BOOLEAN NOT NULL, cache_source VARCHAR(10) NOT NULL, model VARCHAR(100) NOT NULL DEFAULT '', "
                "provider VARCHAR(20) NOT NULL DEFAULT '', requested_at DATETIME NOT NULL, completed_at DATETIME NOT NULL, metrics JSON)"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO estimations (description, options, result, prompt_version, cached, cache_source, "
                "requested_at, completed_at) VALUES ('antigua', :options, :result, 'v3', 0, 'none', :now, :now)"
            ),
            {
                "options": '{"project_type": "web_saas", "detail_level": "medium", "output_format": "phases_table"}',
                "result": '{"summary": "x", "confidence_pct": 70, "total_duration_weeks": 2, "total_cost_eur": 10, '
                '"phases": [{"name": "A", "description": "", "duration_weeks": 2, "cost_eur": 10}]}',
                "now": datetime.now(timezone.utc).isoformat(),
            },
        )
    history = EstimationHistory(openai_settings(), engine=engine)

    old = await history.get(1)
    new_id = await history.save(_request(), _outcome(), NOW, conversation_id="c-9", metadata_snapshot=SNAPSHOT)

    assert old.description == "antigua" and old.conversation_id is None
    assert (await history.latest_for_conversation("c-9")).id == new_id
    # Idempotente: un segundo arranque no vuelve a alterar la tabla.
    again = EstimationHistory(openai_settings(), engine=engine)
    assert (await again.get(1)).description == "antigua"
