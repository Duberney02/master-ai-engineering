"""Errores del endpoint completo (app real + SDK simulados): estado HTTP y no fuga de datos."""

import httpx
import pytest
from anthropic import (
    APITimeoutError as AnthropicTimeout,
    AuthenticationError as AnthropicAuthError,
    BadRequestError as AnthropicBadRequest,
    RateLimitError as AnthropicRateLimit,
)
from fastapi.testclient import TestClient
from openai import (
    APITimeoutError as OpenAITimeout,
    AuthenticationError as OpenAIAuthError,
    BadRequestError as OpenAIBadRequest,
    NotFoundError as OpenAINotFound,
    RateLimitError as OpenAIRateLimit,
)

from app.context.examples import ESTIMATION_EXAMPLES
from tests._fakes import (
    LONG_TRANSCRIPTION,
    anthropic_response,
    openai_response,
    patch_anthropic,
    patch_openai,
)

SECRET = "sk-super-secret-key-123"
INTERNAL = "/srv/internal/path traceback boom"


def _http_error(cls, status: int, url: str):
    request = httpx.Request("POST", url)
    return cls("mensaje interno " + SECRET, response=httpx.Response(status, request=request), body={})


def _client(monkeypatch, provider: str) -> TestClient:
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    from app.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    return TestClient(app)


OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

OPENAI_CASES = [
    (_http_error(OpenAIAuthError, 401, OPENAI_URL), 502),
    (OpenAITimeout(request=httpx.Request("POST", OPENAI_URL)), 504),
    (_http_error(OpenAIRateLimit, 429, OPENAI_URL), 429),
    (_http_error(OpenAIBadRequest, 400, OPENAI_URL), 400),
    (_http_error(OpenAINotFound, 404, OPENAI_URL), 400),
    (RuntimeError(INTERNAL + " " + SECRET), 502),
]
ANTHROPIC_CASES = [
    (_http_error(AnthropicAuthError, 401, ANTHROPIC_URL), 502),
    (AnthropicTimeout(request=httpx.Request("POST", ANTHROPIC_URL)), 504),
    (_http_error(AnthropicRateLimit, 429, ANTHROPIC_URL), 429),
    (_http_error(AnthropicBadRequest, 400, ANTHROPIC_URL), 400),
    (RuntimeError(INTERNAL + " " + SECRET), 502),
]


@pytest.mark.parametrize("exc, status", OPENAI_CASES, ids=lambda x: type(x).__name__ if isinstance(x, Exception) else x)
def test_openai_errors_map_to_safe_http_responses(monkeypatch, mocker, exc, status):
    patch_openai(mocker, exc)
    resp = _client(monkeypatch, "openai").post(
        "/api/v1/estimate", json={"transcription": LONG_TRANSCRIPTION}
    )
    assert resp.status_code == status
    assert SECRET not in resp.text and "internal" not in resp.text.lower()
    assert "traceback" not in resp.text.lower()


@pytest.mark.parametrize("exc, status", ANTHROPIC_CASES, ids=lambda x: type(x).__name__ if isinstance(x, Exception) else x)
def test_anthropic_errors_map_to_safe_http_responses(monkeypatch, mocker, exc, status):
    patch_anthropic(mocker, exc)
    resp = _client(monkeypatch, "anthropic").post(
        "/api/v1/estimate", json={"transcription": LONG_TRANSCRIPTION}
    )
    assert resp.status_code == status
    assert SECRET not in resp.text and "internal" not in resp.text.lower()


def test_two_phase_failure_in_first_phase_is_controlled(monkeypatch, mocker):
    create = patch_openai(mocker, RuntimeError(INTERNAL))
    resp = _client(monkeypatch, "openai").post(
        "/api/v1/estimate",
        json={"transcription": LONG_TRANSCRIPTION, "preprocessing": "two_phase"},
    )
    assert resp.status_code == 502
    assert INTERNAL not in resp.text
    assert create.await_count == 1


def test_empty_provider_response_is_a_controlled_502(monkeypatch, mocker):
    patch_openai(mocker, openai_response("  "))
    resp = _client(monkeypatch, "openai").post(
        "/api/v1/estimate", json={"transcription": LONG_TRANSCRIPTION}
    )
    assert resp.status_code == 502


def test_disallowed_model_returns_422_and_never_calls_the_provider(monkeypatch, mocker):
    monkeypatch.setenv("ALLOWED_MODELS", "gpt-4o-mini")
    create = patch_openai(mocker, openai_response("x"))
    resp = _client(monkeypatch, "openai").post(
        "/api/v1/estimate", json={"transcription": LONG_TRANSCRIPTION, "model": "gpt-5-pro"}
    )
    assert resp.status_code == 422
    create.assert_not_awaited()


def test_end_to_end_success_exposes_metadata_and_no_key(monkeypatch, mocker):
    create = patch_anthropic(
        mocker,
        anthropic_response("req", input_tokens=10, output_tokens=5),
        anthropic_response(ESTIMATION_EXAMPLES[1]["estimation"], input_tokens=900, output_tokens=700),
    )
    resp = _client(monkeypatch, "anthropic").post(
        "/api/v1/estimate",
        json={"transcription": LONG_TRANSCRIPTION, "preprocessing": "two_phase", "max_tokens": 2000},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "anthropic"
    assert data["finish_reason"] == "end_turn"
    assert data["extracted_requirements"] == "req"
    assert data["usage"]["total_tokens"] == 10 + 5 + 900 + 700
    assert [p["phase"] for p in data["usage"]["phases"]] == ["preprocessing", "estimation"]
    assert data["evaluation"]["score"] == 1.0
    assert create.await_count == 2
    assert SECRET not in resp.text
