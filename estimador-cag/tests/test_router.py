from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.context.examples import ESTIMATION_EXAMPLES
from app.routers.estimations import router
from app.services.llm_service import GenerationOptions, LLMEstimationResult, PhaseResult


def _make_result() -> LLMEstimationResult:
    return LLMEstimationResult(
        estimation="## Estimación: Test\nContenido de prueba",
        model="gpt-4o-mini",
        provider="openai",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        estimated_cost_usd=None,
        generated_at=datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc),
        latency_ms=1200,
    )


@pytest.fixture
def client(mocker) -> TestClient:
    mocker.patch(
        "app.routers.estimations.generate_estimation",
        new=AsyncMock(return_value=_make_result()),
    )
    test_app = FastAPI()
    test_app.include_router(router)
    return TestClient(test_app)


def test_estimate_valid_returns_200(client):
    resp = client.post(
        "/estimate",
        json={"transcription": "El cliente solicita una plataforma de e-commerce con pagos y envíos integrados."},
    )
    assert resp.status_code == 200


def test_estimate_response_shape(client):
    resp = client.post(
        "/estimate",
        json={"transcription": "El cliente solicita una plataforma de e-commerce con pagos y envíos integrados."},
    )
    data = resp.json()
    assert data["estimation"].startswith("## Estimación: Test")
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4o-mini"
    assert data["usage"]["input_tokens"] == 100
    assert data["usage"]["output_tokens"] == 50
    assert data["usage"]["total_tokens"] == 150
    assert data["estimated_cost_usd"] is None
    assert data["latency_ms"] == 1200
    assert "generated_at" in data


def test_estimate_rejects_too_short(client):
    resp = client.post("/estimate", json={"transcription": "Corto"})
    assert resp.status_code == 422


def test_estimate_rejects_empty(client):
    resp = client.post("/estimate", json={"transcription": ""})
    assert resp.status_code == 422


def test_estimate_rejects_missing_field(client):
    resp = client.post("/estimate", json={})
    assert resp.status_code == 422


def test_estimate_rejects_too_long(client):
    resp = client.post("/estimate", json={"transcription": "A" * 50_001})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Opciones por solicitud, metadatos y evaluación
# ---------------------------------------------------------------------------

TRANSCRIPTION = "El cliente solicita una plataforma de e-commerce con pagos y envíos integrados."
WELL_FORMED = ESTIMATION_EXAMPLES[0]["estimation"]


def _rich_result(**overrides) -> LLMEstimationResult:
    base = dict(
        estimation=WELL_FORMED,
        model="gpt-4o-mini",
        provider="openai",
        input_tokens=2300,
        output_tokens=940,
        total_tokens=3240,
        estimated_cost_usd=None,
        generated_at=datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc),
        latency_ms=2500,
        finish_reason="stop",
        preprocessing="two_phase",
        extracted_requirements="### Requisitos funcionales\n- Pagos",
        phases=[
            PhaseResult("preprocessing", "gpt-4o-mini", "stop", 300, 40, 340, 400),
            PhaseResult("estimation", "gpt-4o-mini", "stop", 2000, 900, 2900, 2100),
        ],
    )
    base.update(overrides)
    return LLMEstimationResult(**base)


@pytest.fixture
def service(mocker) -> AsyncMock:
    return mocker.patch(
        "app.routers.estimations.generate_estimation",
        new=AsyncMock(return_value=_rich_result()),
    )


@pytest.fixture
def rich_client(service) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_defaults_preserve_previous_behaviour(rich_client, service):
    rich_client.post("/estimate", json={"transcription": TRANSCRIPTION})
    options: GenerationOptions = service.await_args.args[1]
    assert options == GenerationOptions(
        preprocessing="none",
        example_format="markdown",
        num_examples=2,
        use_examples=True,
        model=None,
        max_tokens=None,
    )


def test_all_options_are_forwarded_to_the_service(rich_client, service):
    resp = rich_client.post(
        "/estimate",
        json={
            "transcription": TRANSCRIPTION,
            "preprocessing": "two_phase",
            "example_format": "json",
            "num_examples": 4,
            "use_examples": False,
            "model": "gpt-4o",
            "max_tokens": 2500,
            "evaluate": False,
        },
    )
    assert resp.status_code == 200
    assert service.await_args.args[0] == TRANSCRIPTION
    assert service.await_args.args[1] == GenerationOptions(
        preprocessing="two_phase",
        example_format="json",
        num_examples=4,
        use_examples=False,
        model="gpt-4o",
        max_tokens=2500,
    )


@pytest.mark.parametrize(
    "field, value",
    [
        ("preprocessing", "magic"),
        ("example_format", "yaml"),
        ("num_examples", -1),
        ("num_examples", 6),
        ("num_examples", "muchos"),
        ("use_examples", "quizas"),
        ("max_tokens", 0),
        ("max_tokens", -5),
        ("max_tokens", 16_001),
        ("model", ""),
        ("model", "gpt 4o; drop table"),
        ("model", "x" * 101),
        ("evaluate", "tal vez"),
    ],
)
def test_invalid_options_are_rejected_with_422(rich_client, service, field, value):
    resp = rich_client.post("/estimate", json={"transcription": TRANSCRIPTION, field: value})
    assert resp.status_code == 422
    service.assert_not_awaited()


@pytest.mark.parametrize("n", [0, 1, 5])
def test_num_examples_boundaries_are_accepted(rich_client, n):
    resp = rich_client.post("/estimate", json={"transcription": TRANSCRIPTION, "num_examples": n})
    assert resp.status_code == 200


def test_response_exposes_finish_reason_phases_and_extracted_requirements(rich_client):
    data = rich_client.post("/estimate", json={"transcription": TRANSCRIPTION, "preprocessing": "two_phase"}).json()
    assert data["finish_reason"] == "stop"
    assert data["preprocessing"] == "two_phase"
    assert data["extracted_requirements"] == "### Requisitos funcionales\n- Pagos"
    assert data["usage"]["total_tokens"] == 3240
    pre, est = data["usage"]["phases"]
    assert pre == {
        "phase": "preprocessing",
        "model": "gpt-4o-mini",
        "finish_reason": "stop",
        "input_tokens": 300,
        "output_tokens": 40,
        "total_tokens": 340,
        "latency_ms": 400,
        "provider": "",
        "cache_hit": False,
        "estimated_cost_usd": None,
        "request_cost_usd": None,
        "usage_available": True,
    }
    assert est["phase"] == "estimation" and est["total_tokens"] == 2900


def test_evaluation_is_included_by_default(rich_client):
    data = rich_client.post("/estimate", json={"transcription": TRANSCRIPTION}).json()
    assert data["evaluation"]["score"] == 1.0
    assert data["evaluation"]["hours_match"] is True
    assert data["evaluation"]["issues"] == []


def test_evaluation_can_be_disabled(rich_client):
    data = rich_client.post("/estimate", json={"transcription": TRANSCRIPTION, "evaluate": False}).json()
    assert data["evaluation"] is None


def test_evaluation_flags_truncated_response(rich_client, service):
    service.return_value = _rich_result(estimation=WELL_FORMED[:700], finish_reason="length")
    data = rich_client.post("/estimate", json={"transcription": TRANSCRIPTION}).json()
    assert data["finish_reason"] == "length"
    assert data["evaluation"]["truncated"] is True
    assert data["evaluation"]["score"] < 1.0
    assert any("truncada" in issue for issue in data["evaluation"]["issues"])


def test_evaluation_flags_numeric_discrepancy(rich_client, service):
    bad = WELL_FORMED.replace("**Total estimado:** 292 horas", "**Total estimado:** 400 horas")
    service.return_value = _rich_result(estimation=bad)
    ev = rich_client.post("/estimate", json={"transcription": TRANSCRIPTION}).json()["evaluation"]
    assert ev["hours_match"] is False
    assert ev["range_consistent"] is False
    assert any("Discrepancia numérica" in issue for issue in ev["issues"])


def test_evaluation_reports_truncated_preprocessing_phase(rich_client, service):
    result = _rich_result()
    result.phases[0].finish_reason = "length"
    service.return_value = result
    ev = rich_client.post("/estimate", json={"transcription": TRANSCRIPTION}).json()["evaluation"]
    assert any("fase 1" in issue for issue in ev["issues"])


def test_single_phase_result_serialises_one_phase(rich_client, service):
    service.return_value = _rich_result(
        preprocessing="none",
        extracted_requirements=None,
        phases=[PhaseResult("estimation", "gpt-4o-mini", "stop", 100, 50, 150, 900)],
    )
    data = rich_client.post("/estimate", json={"transcription": TRANSCRIPTION}).json()
    assert data["extracted_requirements"] is None
    assert [p["phase"] for p in data["usage"]["phases"]] == ["estimation"]
