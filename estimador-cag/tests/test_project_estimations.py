"""`POST /api/v1/estimate` con la app real y SDK simulados: nunca llama a APIs externas."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.prompts.loader import render_estimation_prompt
from app.schemas import EstimationRequest
from app.schemas import EstimationStreamMetadata
from app.streamlit_client import parse_sse
from tests._fakes import (
    LONG_TRANSCRIPTION,
    anthropic_final_message,
    anthropic_response,
    anthropic_settings,
    openai_response,
    openai_settings,
    openai_stream_chunks,
    patch_anthropic,
    patch_anthropic_stream,
    patch_openai,
    patch_openai_stream,
    patch_settings,
)

SECRET = "sk-super-secret-key-123"
PAYLOAD = {
    "description": "Aplicación móvil para que los vecinos de un municipio reporten incidencias urbanas.",
    "project_type": "mobile_app",
    "detail_level": "detailed",
    "output_format": "phases_table",
}


@pytest.fixture
def client(mocker) -> TestClient:
    patch_settings(mocker, openai_settings())
    return TestClient(app)


def test_valid_request_returns_text_and_default_version(client, mocker):
    patch_openai(mocker, openai_response("| Fase | Horas mín. |"))

    resp = client.post("/api/v1/estimate", json=PAYLOAD)

    assert resp.status_code == 200
    assert resp.json() == {"text": "| Fase | Horas mín. |", "prompt_version": "v1"}


def test_system_and_user_are_sent_as_separate_messages(client, mocker):
    create = patch_openai(mocker, openai_response("ok"))

    client.post("/api/v1/estimate", json=PAYLOAD)

    system, user = render_estimation_prompt(EstimationRequest(**PAYLOAD), "v1")
    messages = create.await_args.kwargs["messages"]
    assert messages == [{"role": "system", "content": system}, {"role": "user", "content": user}]
    assert PAYLOAD["description"] in messages[1]["content"]
    assert PAYLOAD["description"] not in messages[0]["content"]


def test_anthropic_receives_system_parameter_and_user_message(mocker):
    patch_settings(mocker, anthropic_settings())
    create = patch_anthropic(mocker, anthropic_response("ok"))

    resp = TestClient(app).post("/api/v1/estimate", json=PAYLOAD)

    system, user = render_estimation_prompt(EstimationRequest(**PAYLOAD), "v1")
    assert resp.status_code == 200
    assert create.await_args.kwargs["system"] == system
    assert create.await_args.kwargs["messages"] == [{"role": "user", "content": user}]
    assert create.await_args.kwargs["model"] == "claude-haiku-4-5"


def test_prompt_version_query_param_selects_v2(client, mocker):
    create = patch_openai(mocker, openai_response("ok"))

    resp = client.post("/api/v1/estimate?prompt_version=v2", json=PAYLOAD)

    assert resp.status_code == 200
    assert resp.json()["prompt_version"] == "v2"
    assert "consultor de preventa" in create.await_args.kwargs["messages"][0]["content"]


@pytest.mark.parametrize("version", ["v9", "..%2Fv1", "latest"])
def test_unknown_prompt_version_is_422_without_calling_provider(client, mocker, version):
    create = patch_openai(mocker, openai_response("ok"))

    resp = client.post(f"/api/v1/estimate?prompt_version={version}", json=PAYLOAD)

    assert resp.status_code == 422
    assert "v1" in resp.json()["detail"]
    create.assert_not_awaited()


@pytest.mark.parametrize("overrides", [
    {"description": "corta"},
    {"project_type": "desktop_app"},
    {"output_format": "json"},
    {"detail_level": None},
])
def test_invalid_body_is_422_without_calling_provider(client, mocker, overrides):
    create = patch_openai(mocker, openai_response("ok"))

    resp = client.post("/api/v1/estimate", json=PAYLOAD | overrides)

    assert resp.status_code == 422
    create.assert_not_awaited()


def test_reference_projects_reach_the_user_message(client, mocker):
    create = patch_openai(mocker, openai_response("ok"))
    payload = PAYLOAD | {"reference_projects": [
        {"name": "App de turismo", "description": "Rutas y avisos", "actual_hours": 510},
    ]}

    assert client.post("/api/v1/estimate", json=payload).status_code == 200
    assert "App de turismo (510 h reales)" in create.await_args.kwargs["messages"][1]["content"]


def test_provider_failure_is_sanitized(client, mocker):
    patch_openai(mocker, RuntimeError("boom " + SECRET))

    resp = client.post("/api/v1/estimate", json=PAYLOAD)

    assert resp.status_code == 502
    assert SECRET not in resp.text and "boom" not in resp.text


def test_transcription_flow_moved_under_its_own_prefix(client, mocker):
    patch_openai(mocker, openai_response("## Estimación: Demo"))

    moved = client.post("/api/v1/transcription/estimate", json={"transcription": LONG_TRANSCRIPTION})
    old_shape = client.post("/api/v1/estimate", json={"transcription": LONG_TRANSCRIPTION})

    assert moved.status_code == 200 and moved.json()["estimation"] == "## Estimación: Demo"
    assert old_shape.status_code == 422


def test_openapi_documents_both_flows(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert {"/api/v1/estimate", "/api/v1/estimate/stream", "/api/v1/transcription/estimate",
            "/api/v1/transcription/estimate/stream"} <= set(paths)
    params = {p["name"] for p in paths["/api/v1/estimate"]["post"]["parameters"]}
    assert params == {"prompt_version"}


def _events(resp):
    return list(parse_sse(resp.text.splitlines()))


def test_stream_emits_tokens_then_typed_metadata_then_done(client, mocker):
    create = patch_openai_stream(mocker, openai_stream_chunks(
        ["| Fase |", " Horas |\n"], prompt_tokens=321, completion_tokens=45,
    ))

    resp = client.post("/api/v1/estimate/stream", json=PAYLOAD)

    events = _events(resp)
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert [name for name, _ in events] == ["token", "token", "metadata", "done"]
    assert "".join(data["text"] for name, data in events if name == "token") == "| Fase | Horas |\n"
    meta = EstimationStreamMetadata.model_validate(events[2][1])
    assert meta.prompt_version == "v1"
    assert (meta.provider, meta.model, meta.finish_reason) == ("openai", "gpt-4o-mini", "stop")
    assert (meta.usage.input_tokens, meta.usage.output_tokens, meta.usage.total_tokens) == (321, 45, 366)
    assert meta.cache_hit is False
    system, user = render_estimation_prompt(EstimationRequest(**PAYLOAD), "v1")
    assert create.await_args.kwargs["messages"] == [
        {"role": "system", "content": system}, {"role": "user", "content": user},
    ]
    assert create.await_args.kwargs["stream"] is True


def test_stream_with_v2_and_anthropic(mocker):
    patch_settings(mocker, anthropic_settings())
    client = patch_anthropic_stream(mocker, ["Hola"], anthropic_final_message("Hola"))

    resp = TestClient(app).post("/api/v1/estimate/stream?prompt_version=v2", json=PAYLOAD)

    events = _events(resp)
    assert [name for name, _ in events] == ["token", "metadata", "done"]
    assert events[1][1]["prompt_version"] == "v2"
    assert events[1][1]["provider"] == "anthropic"
    kwargs = client.messages.stream.call_args.kwargs
    system, user = render_estimation_prompt(EstimationRequest(**PAYLOAD), "v2")
    assert kwargs["system"] == system
    assert kwargs["messages"] == [{"role": "user", "content": user}]


@pytest.mark.parametrize("query, body", [
    ("?prompt_version=v9", PAYLOAD),
    ("", PAYLOAD | {"description": "corta"}),
])
def test_stream_rejects_invalid_input_before_streaming(client, mocker, query, body):
    create = patch_openai_stream(mocker, openai_stream_chunks(["x"]))

    resp = client.post(f"/api/v1/estimate/stream{query}", json=body)

    assert resp.status_code == 422
    assert not resp.headers["content-type"].startswith("text/event-stream")
    create.assert_not_awaited()


def test_stream_provider_failure_is_a_sanitized_error_without_done(client, mocker):
    patch_openai(mocker, RuntimeError("boom " + SECRET))

    resp = client.post("/api/v1/estimate/stream", json=PAYLOAD)

    events = _events(resp)
    assert [name for name, _ in events] == ["error"]
    assert events[0][1]["status_code"] == 502
    assert SECRET not in resp.text and "boom" not in resp.text
