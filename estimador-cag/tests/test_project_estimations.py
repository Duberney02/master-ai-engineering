"""`POST /api/v1/estimate` con la app real y SDK simulados: nunca llama a APIs externas."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.prompts.loader import render_estimation_prompt
from app.schemas import EstimationRequest, EstimationResult, EstimationStreamMetadata
from app.services.pipeline import PipelineOutcome, get_pipeline
from app.streamlit_client import parse_sse
from tests._fakes import (
    LONG_TRANSCRIPTION,
    anthropic_response,
    anthropic_settings,
    openai_response,
    openai_settings,
    patch_anthropic,
    patch_openai,
    patch_settings,
)

SECRET = "sk-super-secret-key-123"
PAYLOAD = {
    "description": "Aplicación móvil para que los vecinos de un municipio reporten incidencias urbanas.",
    "project_type": "mobile_app",
    "detail_level": "detailed",
    "output_format": "phases_table",
}
RESULT = {
    "summary": "Proyecto mediano.",
    "confidence_pct": 70,
    "phases": [
        {"name": "Diseño", "description": "UX", "duration_weeks": 2, "cost_eur": 4000},
        {"name": "Desarrollo", "description": "App y API", "duration_weeks": 8, "cost_eur": 16000},
    ],
    "total_duration_weeks": 10,
    "total_cost_eur": 20000,
}
MODEL_JSON = json.dumps(RESULT)


def _settings(**kw):
    # Sin Redis ni moderación: las pruebas del endpoint no usan red.
    return openai_settings(moderation_enabled=False, **kw)


@pytest.fixture
def client(mocker) -> TestClient:
    patch_settings(mocker, _settings())
    return TestClient(app)


def test_valid_request_returns_structured_result(client, mocker):
    patch_openai(mocker, openai_response(MODEL_JSON))

    resp = client.post("/api/v1/estimate", json=PAYLOAD)

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"result", "prompt_version", "cached", "cache_source", "estimation_id", "metrics"}
    assert body["prompt_version"] == "v3" and body["cached"] is False
    assert body["cache_source"] == "none" and body["estimation_id"] is None
    assert body["result"] == RESULT | {"out_of_scope": False}


def test_system_and_user_are_sent_as_separate_messages(client, mocker):
    create = patch_openai(mocker, openai_response(MODEL_JSON))

    client.post("/api/v1/estimate", json=PAYLOAD)

    system, user = render_estimation_prompt(EstimationRequest(**PAYLOAD), "v3")
    messages = create.await_args.kwargs["messages"]
    assert messages == [{"role": "system", "content": system}, {"role": "user", "content": user}]
    assert PAYLOAD["description"] in messages[1]["content"]
    assert PAYLOAD["description"] not in messages[0]["content"]


def test_anthropic_receives_system_parameter_and_user_message(mocker):
    patch_settings(mocker, anthropic_settings())
    create = patch_anthropic(mocker, anthropic_response(MODEL_JSON))

    resp = TestClient(app).post("/api/v1/estimate", json=PAYLOAD)

    system, user = render_estimation_prompt(EstimationRequest(**PAYLOAD), "v3")
    assert resp.status_code == 200
    assert create.await_args.kwargs["system"] == system
    assert create.await_args.kwargs["messages"] == [{"role": "user", "content": user}]
    assert create.await_args.kwargs["model"] == "claude-haiku-4-5"


def test_prompt_version_query_param_selects_v2_with_json_contract(client, mocker):
    create = patch_openai(mocker, openai_response(MODEL_JSON))

    resp = client.post("/api/v1/estimate?prompt_version=v2", json=PAYLOAD)

    assert resp.status_code == 200
    assert resp.json()["prompt_version"] == "v2"
    system = create.await_args.kwargs["messages"][0]["content"]
    assert "consultor de preventa" in system and "## Contrato de salida (JSON)" in system


@pytest.mark.parametrize("version", ["v9", "..%2Fv1", "latest"])
def test_unknown_prompt_version_is_422_without_calling_provider(client, mocker, version):
    create = patch_openai(mocker, openai_response(MODEL_JSON))

    resp = client.post(f"/api/v1/estimate?prompt_version={version}", json=PAYLOAD)

    assert resp.status_code == 422
    assert "v1" in resp.json()["detail"]
    create.assert_not_awaited()


@pytest.mark.parametrize(
    "overrides",
    [
        {"description": "corta"},
        {"project_type": "desktop_app"},
        {"output_format": "json"},
        {"detail_level": None},
    ],
)
def test_invalid_body_is_422_without_calling_provider(client, mocker, overrides):
    create = patch_openai(mocker, openai_response(MODEL_JSON))

    resp = client.post("/api/v1/estimate", json=PAYLOAD | overrides)

    assert resp.status_code == 422
    create.assert_not_awaited()


def test_reference_projects_reach_the_user_message(client, mocker):
    create = patch_openai(mocker, openai_response(MODEL_JSON))
    payload = PAYLOAD | {
        "reference_projects": [
            {"name": "App de turismo", "description": "Rutas y avisos", "actual_hours": 510},
        ]
    }

    assert client.post("/api/v1/estimate", json=payload).status_code == 200
    assert "App de turismo (510 h reales)" in create.await_args.kwargs["messages"][1]["content"]


def test_provider_failure_is_sanitized(client, mocker):
    patch_openai(mocker, RuntimeError("boom " + SECRET))

    resp = client.post("/api/v1/estimate", json=PAYLOAD)

    assert resp.status_code == 502
    assert SECRET not in resp.text and "boom" not in resp.text


def test_wrong_sum_is_corrected_with_a_second_call(client, mocker):
    bad = json.dumps(RESULT | {"total_cost_eur": 25000})
    create = patch_openai(mocker, openai_response(bad), openai_response(MODEL_JSON))

    resp = client.post("/api/v1/estimate", json=PAYLOAD)

    assert resp.status_code == 200 and resp.json()["result"]["total_cost_eur"] == 20000
    assert create.await_count == 2
    retry_user = create.await_args_list[1].kwargs["messages"][1]["content"]
    assert PAYLOAD["description"] in retry_user and "25000" in retry_user and "20000" in retry_user


def test_invalid_after_all_attempts_is_a_sanitized_502(client, mocker):
    create = patch_openai(mocker, *[openai_response("no soy json " + SECRET)] * 3)

    resp = client.post("/api/v1/estimate", json=PAYLOAD)

    assert resp.status_code == 502 and create.await_count == 3
    assert SECRET not in resp.text and "no soy json" not in resp.text


def test_low_confidence_returns_placeholder_phase(client, mocker):
    low = json.dumps(RESULT | {"confidence_pct": 15, "summary": "Out of scope: faltan requisitos."})
    patch_openai(mocker, openai_response(low))

    result = client.post("/api/v1/estimate", json=PAYLOAD).json()["result"]

    assert result["out_of_scope"] is True
    assert result["summary"].startswith("Out of scope:")
    assert [(p["name"], p["cost_eur"], p["duration_weeks"]) for p in result["phases"]] == [("No estimable", 0, 1)]
    assert (result["total_cost_eur"], result["total_duration_weeks"]) == (0, 1)


def test_guardrail_rejection_is_400_with_reason_and_message(client, mocker):
    create = patch_openai(mocker, openai_response(MODEL_JSON))
    payload = PAYLOAD | {"description": PAYLOAD["description"] + " Contacto: ana@example.com"}

    resp = client.post("/api/v1/estimate", json=payload)

    assert resp.status_code == 400
    assert set(resp.json()) == {"reason", "message"} and resp.json()["reason"] == "pii_email"
    assert "ana@example.com" not in resp.text
    create.assert_not_awaited()


def test_pipeline_is_injectable_with_dependency_overrides(client):
    class FakePipeline:
        async def run(self, request, prompt_version, input_checked=False):
            return PipelineOutcome(
                result=EstimationResult.model_validate(RESULT), prompt_version=prompt_version, cached=True
            )

    app.dependency_overrides[get_pipeline] = lambda: FakePipeline()
    try:
        resp = client.post("/api/v1/estimate?prompt_version=v2", json=PAYLOAD)
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["cached"] is True and resp.json()["prompt_version"] == "v2"


def test_transcription_flow_moved_under_its_own_prefix(client, mocker):
    patch_openai(mocker, openai_response("## Estimación: Demo"))

    moved = client.post("/api/v1/transcription/estimate", json={"transcription": LONG_TRANSCRIPTION})
    old_shape = client.post("/api/v1/estimate", json={"transcription": LONG_TRANSCRIPTION})

    assert moved.status_code == 200 and moved.json()["estimation"] == "## Estimación: Demo"
    assert old_shape.status_code == 422


def test_openapi_documents_both_flows(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert {
        "/api/v1/estimate",
        "/api/v1/estimate/stream",
        "/api/v1/transcription/estimate",
        "/api/v1/transcription/estimate/stream",
    } <= set(paths)
    params = {p["name"] for p in paths["/api/v1/estimate"]["post"]["parameters"]}
    assert params == {"prompt_version"}
    assert "400" in paths["/api/v1/estimate"]["post"]["responses"]


def _events(resp):
    return list(parse_sse(resp.text.splitlines()))


def test_stream_emits_result_then_typed_metadata_then_done(client, mocker):
    create = patch_openai(mocker, openai_response(MODEL_JSON, prompt_tokens=321, completion_tokens=45))

    resp = client.post("/api/v1/estimate/stream", json=PAYLOAD)

    events = _events(resp)
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert [name for name, _ in events] == ["result", "metadata", "done"]
    assert events[0][1] == RESULT | {"out_of_scope": False}
    meta = EstimationStreamMetadata.model_validate(events[1][1])
    assert meta.prompt_version == "v3"
    assert (meta.provider, meta.model, meta.finish_reason) == ("openai", "gpt-4o-mini", "stop")
    assert (meta.usage.input_tokens, meta.usage.output_tokens, meta.usage.total_tokens) == (321, 45, 366)
    assert meta.cache_hit is False
    system, user = render_estimation_prompt(EstimationRequest(**PAYLOAD), "v3")
    assert create.await_args.kwargs["messages"] == [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def test_stream_with_v2_and_anthropic(mocker):
    patch_settings(mocker, anthropic_settings())
    patch_anthropic(mocker, anthropic_response(MODEL_JSON))

    resp = TestClient(app).post("/api/v1/estimate/stream?prompt_version=v2", json=PAYLOAD)

    events = _events(resp)
    assert [name for name, _ in events] == ["result", "metadata", "done"]
    assert events[1][1]["prompt_version"] == "v2" and events[1][1]["provider"] == "anthropic"


@pytest.mark.parametrize(
    "query, body, status",
    [
        ("?prompt_version=v9", PAYLOAD, 422),
        ("", PAYLOAD | {"description": "corta"}, 422),
        ("", PAYLOAD | {"description": PAYLOAD["description"] + " ana@example.com"}, 400),
    ],
)
def test_stream_rejects_invalid_input_before_streaming(client, mocker, query, body, status):
    create = patch_openai(mocker, openai_response(MODEL_JSON))

    resp = client.post(f"/api/v1/estimate/stream{query}", json=body)

    assert resp.status_code == status
    assert not resp.headers["content-type"].startswith("text/event-stream")
    create.assert_not_awaited()


def test_stream_provider_failure_is_a_sanitized_error_without_done(client, mocker):
    patch_openai(mocker, RuntimeError("boom " + SECRET))

    resp = client.post("/api/v1/estimate/stream", json=PAYLOAD)

    events = _events(resp)
    assert [name for name, _ in events] == ["error"]
    assert events[0][1]["status_code"] == 502
    assert SECRET not in resp.text and "boom" not in resp.text


def test_stream_validation_exhaustion_is_an_error_without_done(client, mocker):
    patch_openai(mocker, *[openai_response("basura")] * 3)

    events = _events(client.post("/api/v1/estimate/stream", json=PAYLOAD))

    assert [name for name, _ in events] == ["error"] and events[0][1]["status_code"] == 502
