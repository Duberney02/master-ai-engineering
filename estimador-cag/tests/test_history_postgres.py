"""Integración con PostgreSQL real; se omite salvo que `TEST_DATABASE_URL` esté definida.

Se ejecuta desde Docker contra el servicio `postgres` del Compose raíz, por ejemplo:
TEST_DATABASE_URL=postgresql+asyncpg://estimator:estimator@postgres:5432/estimator
"""

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.schemas import EstimationRequest, EstimationResult
from app.services.history import EstimationHistory
from app.services.pipeline import PipelineOutcome
from tests._fakes import openai_settings

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL no definida")

RESULT = {
    "summary": "Proyecto pequeño.", "confidence_pct": 80, "total_duration_weeks": 4,
    "total_cost_eur": 8000, "phases": [{"name": "Desarrollo", "duration_weeks": 4, "cost_eur": 8000}],
}


async def test_round_trip_against_real_postgres():
    history = EstimationHistory(openai_settings(database_url=URL))
    request = EstimationRequest(
        description=("Aplicación móvil para incidencias urbanas. " * 2000)[:80_000],
        project_type="mobile_app", detail_level="medium", output_format="phases_table",
    )
    outcome = PipelineOutcome(
        result=EstimationResult.model_validate(RESULT), prompt_version="v3", cached=True,
        cache_source="exact", model="gpt-4o-mini", provider="openai",
    )
    try:
        saved_id = await history.save(request, outcome, datetime.now(timezone.utc))
        assert isinstance(saved_id, int)

        detail = await history.get(saved_id)
        assert detail.description == request.description and len(detail.description) == 80_000
        assert detail.result.total_cost_eur == 8000 and detail.cache_source == "exact"
        assert detail.requested_at.tzinfo is not None

        assert (await history.list_recent(10))[0].id == saved_id

        # En PostgreSQL el resultado es JSONB y las fechas llevan zona horaria.
        engine = create_async_engine(URL)
        async with engine.connect() as connection:
            rows = await connection.execute(text(
                "select column_name, data_type from information_schema.columns "
                "where table_name = 'estimations'"))
            kinds = dict(rows.all())
        await engine.dispose()
        assert kinds["result"] == "jsonb" and kinds["requested_at"] == "timestamp with time zone"
    finally:
        await history.close()
