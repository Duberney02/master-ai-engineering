import json
from contextlib import contextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.routers.estimations import router
from app.schemas.estimation import EstimationRequest
from app.services.evaluation import evaluate_estimation
from app.services.llm_service import GenerationOptions, StreamMetrics, generate_estimation, generate_estimation_stream
from app.streamlit_client import EstimationStreamError, parse_sse, stream_estimation
from tests._fakes import (
    LONG_TRANSCRIPTION, openai_settings, anthropic_settings, patch_settings,
    openai_response, anthropic_response, patch_openai, patch_anthropic,
    openai_stream_chunks, patch_openai_stream, patch_anthropic_stream, anthropic_final_message,
)


def client():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/transcription")
    return TestClient(app)


def test_sse_tokens_metadata_done_and_multiline(mocker):
    patch_settings(mocker, openai_settings())
    patch_openai_stream(mocker, openai_stream_chunks(["## Estimación\n\n", "Texto"] ))
    response = client().post("/api/v1/transcription/estimate/stream", json={"transcription": LONG_TRANSCRIPTION})
    events = list(parse_sse(response.text.splitlines()))
    assert response.headers["content-type"].startswith("text/event-stream")
    assert [name for name, _ in events] == ["token", "token", "metadata", "done"]
    assert events[0][1]["text"] == "## Estimación\n\n"
    meta = events[-2][1]
    assert meta["usage"]["total_tokens"] == 150
    assert meta["finish_reason"] == "stop"
    assert meta["evaluation"] is not None and "estimation" not in meta


def test_sse_error_sanitized_and_never_done(mocker):
    patch_settings(mocker, openai_settings())
    call = patch_openai_stream(mocker, [])
    async def broken():
        yield openai_stream_chunks(["partial"])[0]
        raise RuntimeError("private secret")
    call.return_value = broken()
    response = client().post("/api/v1/transcription/estimate/stream", json={"transcription": LONG_TRANSCRIPTION})
    events = list(parse_sse(response.text.splitlines()))
    assert [name for name, _ in events] == ["token", "error"]
    assert "private secret" not in response.text


@pytest.mark.parametrize("payload", [
    {"transcription": "short"}, {"transcription": "x" * 50001},
    {"transcription": LONG_TRANSCRIPTION, "thinking_budget": 1},
    {"transcription": LONG_TRANSCRIPTION, "thinking_budget": 2048},
    {"transcription": LONG_TRANSCRIPTION, "model": "not-allowed"},
])
def test_stream_validation_before_provider(mocker, payload):
    patch_settings(mocker, openai_settings(allowed_models="gpt-4o-mini"))
    call = patch_openai_stream(mocker, [])
    response = client().post("/api/v1/transcription/estimate/stream", json=payload)
    assert response.status_code == 422
    call.assert_not_awaited()


def test_two_phase_stream_reports_extraction_and_evaluation(mocker):
    patch_settings(mocker, openai_settings())
    call = patch_openai_stream(mocker, [])
    from tests._fakes import _AsyncIterFromList
    call.side_effect = [openai_response("Requisitos", finish_reason="length"),
                        _AsyncIterFromList(openai_stream_chunks(["Estimación"]))]
    response = client().post("/api/v1/transcription/estimate/stream", json={"transcription": LONG_TRANSCRIPTION, "preprocessing": "two_phase"})
    events = list(parse_sse(response.text.splitlines()))
    meta = events[-2][1]
    assert meta["extracted_requirements"] == "Requisitos"
    assert len(meta["usage"]["phases"]) == 2 and meta["usage"]["total_tokens"] == 300
    assert any("fase 1" in s for s in meta["evaluation"]["issues"])


async def test_thinking_only_reaches_anthropic_estimation_phase(mocker):
    patch_settings(mocker, anthropic_settings())
    call = patch_anthropic(mocker, anthropic_response("Requisitos"), anthropic_response("Estimación"))
    await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(
        preprocessing="two_phase", thinking_budget=2048, max_tokens=1000,
    ))
    assert "thinking" not in call.call_args_list[0].kwargs
    assert call.call_args_list[1].kwargs["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    assert call.call_args_list[1].kwargs["max_tokens"] == 3072


async def test_thinking_streaming_and_incompatible_fallback(mocker):
    patch_settings(mocker, anthropic_settings())
    provider = patch_anthropic_stream(mocker, ["Hola"], anthropic_final_message("Hola"))
    async for _ in generate_estimation_stream(LONG_TRANSCRIPTION, StreamMetrics(), GenerationOptions(thinking_budget=2048)):
        pass
    assert provider.messages.stream.call_args.kwargs["thinking"]["budget_tokens"] == 2048
    patch_settings(mocker, anthropic_settings(openai_api_key="test", fallback_provider="openai", fallback_model="gpt-4o-mini"))
    with pytest.raises(HTTPException) as error:
        await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(thinking_budget=2048))
    assert error.value.status_code == 422


async def test_project_budget_prompt_is_opt_in(mocker):
    patch_settings(mocker, openai_settings())
    call = patch_openai(mocker, openai_response("Uno"), openai_response("Dos"))
    await generate_estimation(LONG_TRANSCRIPTION)
    await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(include_project_costs=True, developer_rate_eur=70.5))
    first = call.call_args_list[0].kwargs["messages"][0]["content"]
    second = call.call_args_list[1].kwargs["messages"][0]["content"]
    assert "Presupuesto económico" not in first
    assert "70.5 EUR/h" in second and "### Presupuesto económico" in second
    assert "| # | Área | Tarea | Horas |" in second


BUDGET = """Total estimado: 12.5 horas
### Presupuesto económico
| Rol | Horas | Tarifa EUR/h | Coste EUR |
|---|---:|---:|---:|
| Desarrollo | 10 | 62.5 | 625 |
| Diseño | 2.5 | 50 | 125 |
Total presupuesto: 750 EUR
"""


@pytest.mark.parametrize("text,valid", [
    (BUDGET, True), (BUDGET.replace("12.5", "12,5").replace("2.5", "2,5"), True),
    (BUDGET.replace("750", "751"), False), (BUDGET.replace("625", "626"), False),
    (BUDGET.replace("62.5", "70"), False), (BUDGET.replace("12.5", "13"), False),
    (BUDGET.replace("Desarrollo", "Otro"), False), ("Sin presupuesto", False),
])
def test_budget_validation_detects_multiplication_totals_rates_and_hours(text, valid):
    result = evaluate_estimation(text, "stop", project_rates={"Desarrollo": 62.5, "Diseño": 50})
    assert result.project_cost_match is valid
    assert evaluate_estimation(text, "stop").project_cost_match is None


@pytest.mark.parametrize("field,value", [("developer_rate_eur", 0), ("designer_rate_eur", -1), ("developer_rate_eur", float("inf")), ("thinking_budget", 15001)])
def test_invalid_new_options(field, value):
    with pytest.raises(ValidationError):
        EstimationRequest(transcription=LONG_TRANSCRIPTION, **{field: value})


def test_sse_parser_multiline_data_comments_and_unicode():
    events = list(parse_sse([': heartbeat', 'event: token', 'data: {', 'data: "text": "á\\nβ"}', '', 'event: done', 'data: {}', '']))
    assert events == [("token", {"text": "á\nβ"}), ("done", {})]


@pytest.mark.parametrize("body", [
    'event: token\ndata: {"text":"partial"}\n\n',
    'event: error\ndata: {"message":"secret"}\n\n',
    'event: done\ndata: {}\n\n',
    'event: token\ndata: invalid\n\n',
])
def test_client_never_accepts_partial_error_or_missing_metadata(mocker, body):
    @contextmanager
    def fake(*args, **kwargs):
        yield httpx.Response(200, text=body, request=httpx.Request("POST", "http://test"))
    mocker.patch("app.streamlit_client.httpx.stream", fake)
    metrics = {"old": 1}
    with pytest.raises(EstimationStreamError) as exc:
        list(stream_estimation(LONG_TRANSCRIPTION, "http://test", metrics))
    assert "secret" not in str(exc.value) and metrics == {}
