"""Endpoint normal `/api/v1/estimate`: compatibilidad, validación, opciones y metadatos."""

from datetime import datetime, timezone

import pytest

from app.context.examples import ESTIMATION_EXAMPLES
from app.llm.types import LLMResult
from app.services.estimation_service import EstimationResult, GenerationOptions, PhaseResult
from tests._fakes import FakeProvider, completion, make_client, make_resources, openai_settings

TRANSCRIPTION = "El cliente solicita una plataforma de e-commerce con pagos y envíos integrados."
WELL_FORMED = ESTIMATION_EXAMPLES[0]["estimation"]
URL = "/api/v1/estimate"


def _llm(text=WELL_FORMED, **kw) -> LLMResult:
    base = dict(
        text=text, provider="openai", model="gpt-4o-mini", requested_model="gpt-4o-mini",
        finish_reason="stop", input_tokens=2000, output_tokens=900, latency_ms=2100,
        cache_status="miss", original_cost_usd=0.00084, incurred_cost_usd=0.00084,
        generated_at=datetime(2026, 9, 11, 12, tzinfo=timezone.utc), original_latency_ms=2100,
    )
    base.update(kw)
    return LLMResult(**base)


def _rich_result(**overrides) -> EstimationResult:
    base = dict(
        estimation=WELL_FORMED,
        phases=[
            PhaseResult("preprocessing", _llm("### Requisitos funcionales\n- Pagos",
                                              input_tokens=300, output_tokens=40, latency_ms=400,
                                              original_cost_usd=0.000069, incurred_cost_usd=0.000069)),
            PhaseResult("estimation", _llm()),
        ],
        latency_ms=2500,
        generated_at=datetime(2026, 9, 11, 12, tzinfo=timezone.utc),
        preprocessing="two_phase",
        extracted_requirements="### Requisitos funcionales\n- Pagos",
    )
    base.update(overrides)
    return EstimationResult(**base)


@pytest.fixture
def provider():
    return FakeProvider("openai", [completion(WELL_FORMED) for _ in range(5)])


@pytest.fixture
def resources(provider):
    return make_resources(openai_settings(), {"openai": provider})


@pytest.fixture
def client(resources):
    with make_client(resources) as c:
        yield c


@pytest.fixture
def spy(mocker, resources):
    """Espía el servicio conservando su comportamiento real."""
    return mocker.spy(resources.service, "generate")


def test_estimate_valid_returns_200(client):
    assert client.post(URL, json={"transcription": TRANSCRIPTION}).status_code == 200


def test_estimate_response_keeps_previous_fields(client):
    data = client.post(URL, json={"transcription": TRANSCRIPTION}).json()
    for field in ("estimation", "model", "provider", "finish_reason", "usage",
                  "estimated_cost_usd", "latency_ms", "generated_at", "preprocessing",
                  "extracted_requirements", "evaluation"):
        assert field in data
    assert data["provider"] == "openai" and data["model"] == "gpt-4o-mini"
    assert data["usage"]["input_tokens"] == 100 and data["usage"]["output_tokens"] == 50
    assert data["usage"]["total_tokens"] == 150
    # Ahora hay tarifa conocida: 100*0.15 + 50*0.60 por millón.
    assert data["estimated_cost_usd"] == pytest.approx(0.000045)
    assert data["cost"]["incurred_usd"] == data["estimated_cost_usd"]
    assert data["cache"] == {"status": "disabled", "phases": {"estimation": "disabled"}}


@pytest.mark.parametrize("body", [{"transcription": "Corto"}, {"transcription": ""}, {},
                                  {"transcription": "A" * 50_001}])
def test_estimate_rejects_invalid_transcriptions(client, provider, body):
    assert client.post(URL, json=body).status_code == 422
    assert provider.calls == []


def test_defaults_preserve_previous_behaviour(client, spy):
    client.post(URL, json={"transcription": TRANSCRIPTION})
    assert spy.call_args.args[1] == GenerationOptions()


def test_all_options_are_forwarded_to_the_service(client, spy, provider):
    resp = client.post(
        URL,
        json={
            "transcription": TRANSCRIPTION,
            "preprocessing": "inline_cleaning",
            "example_format": "json",
            "num_examples": 4,
            "use_examples": False,
            "model": "gpt-4o",
            "allow_fallback": True,
            "max_tokens": 2500,
            "evaluate": False,
        },
    )
    assert resp.status_code == 200
    assert spy.call_args.args[0] == TRANSCRIPTION
    assert spy.call_args.args[1] == GenerationOptions(
        preprocessing="inline_cleaning", example_format="json", num_examples=4,
        use_examples=False, model="gpt-4o", max_tokens=2500, allow_fallback=True, evaluate=False,
    )
    model, request, _ = provider.calls[0]
    assert model == "gpt-4o" and request.max_tokens == 2500


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
        ("allow_fallback", "a veces"),
    ],
)
def test_invalid_options_are_rejected_with_422(client, provider, field, value):
    resp = client.post(URL, json={"transcription": TRANSCRIPTION, field: value})
    assert resp.status_code == 422
    assert provider.calls == []


def test_unknown_fields_are_not_silently_ignored(client):
    resp = client.post(URL, json={"transcription": TRANSCRIPTION, "thinking_budget": 2000})
    assert resp.status_code == 200  # compatibilidad del endpoint normal
    assert resp.headers["X-Ignored-Fields"] == "thinking_budget"


@pytest.mark.parametrize("n", [0, 1, 5])
def test_num_examples_boundaries_are_accepted(client, n):
    assert client.post(URL, json={"transcription": TRANSCRIPTION, "num_examples": n}).status_code == 200


def test_response_exposes_finish_reason_phases_and_extracted_requirements(client, resources, mocker):
    mocker.patch.object(resources.service, "generate", return_value=_rich_result())
    data = client.post(URL, json={"transcription": TRANSCRIPTION, "preprocessing": "two_phase"}).json()
    assert data["finish_reason"] == "stop"
    assert data["preprocessing"] == "two_phase"
    assert data["extracted_requirements"] == "### Requisitos funcionales\n- Pagos"
    assert data["usage"]["total_tokens"] == 3240
    pre, est = data["usage"]["phases"]
    assert pre["phase"] == "preprocessing"
    assert (pre["input_tokens"], pre["output_tokens"], pre["total_tokens"], pre["latency_ms"]) == (
        300, 40, 340, 400,
    )
    assert pre["provider"] == "openai" and pre["model"] == "gpt-4o-mini"
    assert est["phase"] == "estimation" and est["total_tokens"] == 2900


def test_evaluation_is_included_by_default(client):
    data = client.post(URL, json={"transcription": TRANSCRIPTION}).json()
    assert data["evaluation"]["score"] == 1.0
    assert data["evaluation"]["hours_match"] is True
    assert data["evaluation"]["issues"] == []


def test_evaluation_can_be_disabled(client):
    data = client.post(URL, json={"transcription": TRANSCRIPTION, "evaluate": False}).json()
    assert data["evaluation"] is None


def test_evaluation_flags_truncated_response(resources, provider):
    provider.outcomes = [completion(WELL_FORMED[:700], finish_reason="length")]
    with make_client(resources) as client:
        data = client.post(URL, json={"transcription": TRANSCRIPTION}).json()
    assert data["finish_reason"] == "length"
    assert data["evaluation"]["truncated"] is True
    assert data["evaluation"]["score"] < 1.0
    assert any("truncada" in issue for issue in data["evaluation"]["issues"])


def test_evaluation_flags_numeric_discrepancy(resources, provider):
    bad = WELL_FORMED.replace("**Total estimado:** 292 horas", "**Total estimado:** 400 horas")
    provider.outcomes = [completion(bad)]
    with make_client(resources) as client:
        ev = client.post(URL, json={"transcription": TRANSCRIPTION}).json()["evaluation"]
    assert ev["hours_match"] is False
    assert ev["range_consistent"] is False
    assert any("Discrepancia numérica" in issue for issue in ev["issues"])


def test_evaluation_reports_truncated_preprocessing_phase(resources, provider):
    provider.outcomes = [completion("### Requisitos\n- x", finish_reason="length"), completion(WELL_FORMED)]
    with make_client(resources) as client:
        ev = client.post(
            URL, json={"transcription": TRANSCRIPTION, "preprocessing": "two_phase"}
        ).json()["evaluation"]
    assert any("fase 1" in issue for issue in ev["issues"])


def test_single_phase_result_serialises_one_phase(client):
    data = client.post(URL, json={"transcription": TRANSCRIPTION}).json()
    assert data["extracted_requirements"] is None
    assert [p["phase"] for p in data["usage"]["phases"]] == ["estimation"]


def test_request_id_is_propagated(client):
    resp = client.post(URL, json={"transcription": TRANSCRIPTION}, headers={"X-Request-ID": "abc-123"})
    assert resp.headers["X-Request-ID"] == "abc-123"
    assert resp.json()["request_id"] == "abc-123"
