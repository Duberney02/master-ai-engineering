"""Historial persistente: servicio con SQLite en memoria y endpoints con `dependency_overrides`."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.main import app
from app.schemas import EstimationRequest, EstimationResult
from app.services import history as history_module
from app.services.history import EstimationHistory, get_history
from app.services.pipeline import PipelineOutcome, get_pipeline
from tests._fakes import openai_settings, patch_settings

RESULT = {
    "summary": "Proyecto mediano.",
    "confidence_pct": 70,
    "total_duration_weeks": 10,
    "total_cost_eur": 20000,
    "phases": [
        {"name": "Diseño", "description": "UX", "duration_weeks": 2, "cost_eur": 4000},
        {"name": "Desarrollo", "description": "App", "duration_weeks": 8, "cost_eur": 16000},
    ],
}
LOW_CONFIDENCE = {
    "summary": "Out of scope: faltan objetivos.",
    "confidence_pct": 10,
    "total_duration_weeks": 1,
    "total_cost_eur": 0,
    "phases": [{"name": "No estimable", "description": "", "duration_weeks": 1, "cost_eur": 0}],
}
PAYLOAD = {
    "description": "Aplicación móvil para que los vecinos de un municipio reporten incidencias.",
    "project_type": "mobile_app",
    "detail_level": "medium",
    "output_format": "phases_table",
}
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def _request(**overrides) -> EstimationRequest:
    return EstimationRequest(**{**PAYLOAD, **overrides})


def _outcome(result=RESULT, *, cache_source="none", version="v3") -> PipelineOutcome:
    return PipelineOutcome(
        result=EstimationResult.model_validate(result),
        prompt_version=version,
        cached=cache_source != "none",
        cache_source=cache_source,
        model="gpt-4o-mini",
        provider="openai",
    )


def _engine():
    # StaticPool: una única conexión, imprescindible para que SQLite en memoria conserve las tablas.
    return create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})


@pytest.fixture
async def history():
    engine = _engine()
    yield EstimationHistory(openai_settings(), engine=engine)
    await engine.dispose()


async def test_saved_estimation_is_returned_with_all_fields(history):
    request = _request(reference_projects=[{"name": "App vecinal", "description": "Incidencias", "actual_hours": 300}])

    started = datetime.now(timezone.utc) - timedelta(seconds=5)
    saved_id = await history.save(request, _outcome(cache_source="semantic"), started)
    detail = await history.get(saved_id)

    assert detail.id == saved_id
    assert detail.description == request.description
    assert detail.options.project_type.value == "mobile_app"
    assert detail.options.reference_projects[0].name == "App vecinal"
    assert detail.result.total_cost_eur == 20000 and detail.result.phases[1].name == "Desarrollo"
    assert detail.prompt_version == "v3" and detail.model == "gpt-4o-mini"
    assert detail.cached is True and detail.cache_source == "semantic"
    assert detail.requested_at == started and detail.completed_at > started


async def test_long_transcription_is_stored_in_full(history):
    text = ("Reunión de planificación del portal de clientes. " * 1700)[:80_000]

    saved_id = await history.save(_request(description=text), _outcome(), NOW)

    assert len((await history.get(saved_id)).description) == 80_000


async def test_list_is_newest_first_limited_and_without_full_description(history):
    for index in range(12):
        await history.save(_request(description=f"{index} " + "x" * 400), _outcome(), NOW + timedelta(minutes=index))

    recent = await history.list_recent(10)

    assert len(recent) == 10
    assert [item.requested_at for item in recent] == sorted((item.requested_at for item in recent), reverse=True)
    assert recent[0].description_excerpt.startswith("11 ")
    assert len(recent[0].description_excerpt) == 200
    assert not hasattr(recent[0], "description")


async def test_summary_exposes_confidence_cost_and_low_confidence_flag(history):
    await history.save(_request(), _outcome(), NOW)
    await history.save(_request(), _outcome(LOW_CONFIDENCE), NOW + timedelta(minutes=1))

    low, normal = await history.list_recent(10)

    assert low.out_of_scope is True and low.confidence_pct == 10 and low.total_cost_eur == 0
    assert normal.out_of_scope is False and normal.total_cost_eur == 20000
    assert normal.total_duration_weeks == 10 and normal.cache_source == "none"


async def test_unknown_id_returns_none(history):
    assert await history.get(999) is None


async def test_disabled_without_database_url():
    disabled = EstimationHistory(openai_settings())

    assert not disabled.enabled
    assert await disabled.save(_request(), _outcome(), NOW) is None
    with pytest.raises(history_module.HistoryUnavailable, match="not configured"):
        await disabled.list_recent(10)


async def test_save_failure_is_swallowed_and_logged_without_user_data(mocker):
    broken = EstimationHistory(openai_settings(database_url="postgresql+asyncpg://u:secret@db/x"))
    mocker.patch.object(history_module, "create_async_engine", side_effect=OSError("db down"))
    warnings = []
    mocker.patch.object(history_module.logger, "warning", lambda event, **kw: warnings.append((event, kw)))

    assert await broken.save(_request(), _outcome(), NOW) is None
    assert warnings == [("history_save_failed", {"error_type": "OSError"})]


async def test_read_failure_is_sanitized(mocker):
    broken = EstimationHistory(openai_settings(database_url="postgresql+asyncpg://u:secret@db/x"))
    mocker.patch.object(history_module, "create_async_engine", side_effect=OSError("secret@db"))

    with pytest.raises(history_module.HistoryUnavailable) as exc:
        await broken.get(1)

    assert exc.value.detail == "History is unavailable" and "secret" not in exc.value.detail


# --- API -----------------------------------------------------------------------------------------


class FakePipeline:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def run(self, request, prompt_version, input_checked=False):
        return _outcome(**self.kwargs, version=prompt_version)

    async def check_input(self, request, prompt_version):
        return None


@pytest.fixture
def api(mocker):
    patch_settings(mocker, openai_settings(moderation_enabled=False))
    store = EstimationHistory(openai_settings(), engine=_engine())
    app.dependency_overrides[get_history] = lambda: store
    app.dependency_overrides[get_pipeline] = lambda: FakePipeline()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_estimate_saves_and_returns_the_estimation_id(api):
    created = api.post("/api/v1/estimate", json=PAYLOAD)
    fetched = api.get(f"/api/v1/estimations/{created.json()['estimation_id']}")

    assert created.status_code == 200 and isinstance(created.json()["estimation_id"], int)
    assert created.json()["cache_source"] == "none"
    assert fetched.status_code == 200
    assert fetched.json()["description"] == PAYLOAD["description"]
    assert fetched.json()["result"]["total_cost_eur"] == 20000
    assert fetched.json()["options"]["detail_level"] == "medium"


def test_list_endpoint_orders_and_validates_limit(api):
    for _ in range(3):
        api.post("/api/v1/estimate", json=PAYLOAD)

    listing = api.get("/api/v1/estimations?limit=2")

    assert listing.status_code == 200 and len(listing.json()) == 2
    assert listing.json()[0]["id"] > listing.json()[1]["id"]
    assert set(listing.json()[0]) >= {
        "id",
        "requested_at",
        "project_type",
        "confidence_pct",
        "total_cost_eur",
        "total_duration_weeks",
        "cache_source",
        "out_of_scope",
        "description_excerpt",
    }
    assert "description" not in listing.json()[0]
    assert api.get("/api/v1/estimations?limit=0").status_code == 422
    assert api.get("/api/v1/estimations?limit=51").status_code == 422


def test_unknown_estimation_is_404(api):
    assert api.get("/api/v1/estimations/12345").status_code == 404
    assert api.get("/api/v1/estimations/abc").status_code == 422


def test_invalid_request_is_not_saved(api):
    assert api.post("/api/v1/estimate", json={**PAYLOAD, "description": "corta"}).status_code == 422
    assert api.get("/api/v1/estimations").json() == []


def test_cached_estimation_is_saved_with_its_provenance(api):
    app.dependency_overrides[get_pipeline] = lambda: FakePipeline(cache_source="exact")

    created = api.post("/api/v1/estimate", json=PAYLOAD).json()

    assert created["cached"] is True and created["cache_source"] == "exact"
    assert api.get(f"/api/v1/estimations/{created['estimation_id']}").json()["cache_source"] == "exact"


def test_low_confidence_result_is_saved_and_listed_as_out_of_scope(api):
    app.dependency_overrides[get_pipeline] = lambda: FakePipeline(result=LOW_CONFIDENCE)

    api.post("/api/v1/estimate", json=PAYLOAD)

    assert api.get("/api/v1/estimations").json()[0]["out_of_scope"] is True


def test_stream_metadata_includes_cache_source_and_estimation_id(api):
    app.dependency_overrides[get_pipeline] = lambda: FakePipeline(cache_source="semantic")

    body = api.post("/api/v1/estimate/stream", json=PAYLOAD).text

    assert "event: metadata" in body and '"cache_source": "semantic"' in body
    assert '"estimation_id": 1' in body
    assert api.get("/api/v1/estimations/1").json()["cache_source"] == "semantic"


def test_estimation_survives_a_failing_history(mocker):
    patch_settings(mocker, openai_settings(moderation_enabled=False))
    mocker.patch.object(history_module, "create_async_engine", side_effect=OSError("db down"))
    broken = EstimationHistory(openai_settings(database_url="postgresql+asyncpg://u:p@db/x"))
    app.dependency_overrides[get_history] = lambda: broken
    app.dependency_overrides[get_pipeline] = lambda: FakePipeline()
    try:
        with TestClient(app) as client:
            created = client.post("/api/v1/estimate", json=PAYLOAD)
            listing = client.get("/api/v1/estimations")
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 200 and created.json()["estimation_id"] is None
    assert created.json()["result"]["total_cost_eur"] == 20000
    assert listing.status_code == 503 and listing.json() == {"detail": "History is unavailable"}


def test_history_endpoints_return_503_when_not_configured(mocker):
    patch_settings(mocker, openai_settings(moderation_enabled=False))
    history_module._instances.clear()
    app.dependency_overrides[get_pipeline] = lambda: FakePipeline()
    try:
        with TestClient(app) as client:
            listing = client.get("/api/v1/estimations")
            detail = client.get("/api/v1/estimations/1")
            created = client.post("/api/v1/estimate", json=PAYLOAD)
    finally:
        app.dependency_overrides.clear()

    assert listing.status_code == detail.status_code == 503
    assert listing.json() == {"detail": "History is not configured"}
    assert created.status_code == 200 and created.json()["estimation_id"] is None


# --- Métricas de la llamada y vista previa del prompt ---------------------------------------------


def _metrics_outcome() -> PipelineOutcome:
    return PipelineOutcome(
        result=EstimationResult.model_validate(RESULT),
        prompt_version="v3",
        cached=False,
        model="gpt-4o-mini",
        provider="openai",
        input_tokens=1200,
        output_tokens=340,
        latency_ms=2500,
        estimated_cost_usd=0.0004,
        request_cost_usd=0.0004,
    )


def test_outcome_metrics_sum_tokens_and_flag_cache_hits():
    metrics = _metrics_outcome().metrics()

    assert metrics.usage.total_tokens == 1540 and metrics.cache_hit is False
    assert metrics.latency_ms == 2500 and metrics.request_cost_usd == 0.0004
    cached = PipelineOutcome(
        result=EstimationResult.model_validate(RESULT),
        prompt_version="v3",
        cached=True,
        cache_source="exact",
        model="m",
        provider="openai",
    )
    assert cached.metrics().cache_hit is True and cached.metrics().usage.total_tokens == 0


def test_estimate_response_includes_metrics_and_history_keeps_them(api):
    class WithMetrics(FakePipeline):
        async def run(self, request, prompt_version, input_checked=False):
            return _metrics_outcome()

    app.dependency_overrides[get_pipeline] = lambda: WithMetrics()

    created = api.post("/api/v1/estimate", json=PAYLOAD).json()
    detail = api.get(f"/api/v1/estimations/{created['estimation_id']}").json()

    for body in (created["metrics"], detail["metrics"]):
        assert body["model"] == "gpt-4o-mini" and body["usage"]["input_tokens"] == 1200
        assert body["usage"]["total_tokens"] == 1540 and body["latency_ms"] == 2500
        assert body["request_cost_usd"] == 0.0004 and body["cache_hit"] is False


async def test_record_without_metrics_is_returned_with_null_metrics(history):
    saved_id = await history.save(_request(), _outcome(), NOW)
    async with history._sessions()() as session:
        record = await session.get(history_module.EstimationRecord, saved_id)
        record.metrics = None
        await session.commit()

    assert (await history.get(saved_id)).metrics is None


def test_prompt_preview_returns_system_prompt_and_examples(mocker):
    patch_settings(mocker, openai_settings(moderation_enabled=False))
    client = TestClient(app)

    body = client.get("/api/v1/prompts/estimation").json()

    assert body["prompt_version"] == "v3"
    assert "arquitecto sénior de estimación" in body["system_prompt"]
    assert [e["title"] for e in body["examples"]][0] == "Portal de reservas para un gimnasio"
    assert all(e["description"] for e in body["examples"])


def test_prompt_preview_follows_version_and_options_and_validates(mocker):
    patch_settings(mocker, openai_settings(moderation_enabled=False))
    client = TestClient(app)

    v2 = client.get("/api/v1/prompts/estimation?prompt_version=v2&detail_level=detailed").json()
    assert v2["prompt_version"] == "v2" and "## Contrato de salida (JSON)" in v2["system_prompt"]
    assert client.get("/api/v1/prompts/estimation?prompt_version=v9").status_code == 422
    assert client.get("/api/v1/prompts/estimation?prompt_version=..%2Fv1").status_code == 422
    assert client.get("/api/v1/prompts/estimation?project_type=otro").status_code == 422
