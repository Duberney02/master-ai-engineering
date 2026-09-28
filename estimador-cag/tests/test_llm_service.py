"""Prompts y adaptadores reales de OpenAI/Anthropic sobre SDK simulados."""

from datetime import datetime

import httpx
import pytest
from anthropic import APITimeoutError as AnthropicTimeout
from anthropic import AuthenticationError as AnthropicAuthError
from openai import APITimeoutError as OpenAITimeout
from openai import AuthenticationError as OpenAIAuthError

from app.context.examples import ESTIMATION_EXAMPLES
from app.llm.errors import LLMAuthError, LLMEmptyResponseError, LLMTimeoutError
from app.services.estimation_service import EstimationResult
from app.services.prompts import build_system_prompt
from tests._fakes import (
    LONG_TRANSCRIPTION,
    anthropic_response,
    anthropic_sdk,
    anthropic_settings,
    make_resources,
    openai_response,
    openai_sdk,
    openai_settings,
)


def test_prompt_contains_role():
    assert "Senior Software Estimation Architect" in build_system_prompt()


def test_prompt_contains_default_example_summaries():
    prompt = build_system_prompt()
    for ex in ESTIMATION_EXAMPLES[:2]:
        assert ex["meeting_summary"][:60] in prompt


def test_prompt_contains_default_example_estimations():
    prompt = build_system_prompt()
    for ex in ESTIMATION_EXAMPLES[:2]:
        assert ex["estimation"][:60] in prompt


def test_prompt_contains_output_format_markers():
    prompt = build_system_prompt()
    for marker in ("Estimación:", "Supuestos", "Riesgos", "Preguntas abiertas"):
        assert marker in prompt


def test_prompt_instructs_assumptions_over_invention():
    assert "assumption" in build_system_prompt().lower()


def test_prompt_is_substantial():
    assert len(build_system_prompt()) > 800


# --------------------------------------------------------------------------- dispatch


def _service(settings, **providers):
    return make_resources(settings, providers).service


async def test_generate_estimation_openai():
    adapter, _ = openai_sdk(
        openai_response("## Estimación: Test\nContenido", prompt_tokens=120, completion_tokens=80)
    )
    result = await _service(openai_settings(), openai=adapter).generate(LONG_TRANSCRIPTION)

    assert isinstance(result, EstimationResult)
    est = result.estimation_phase
    assert est.provider == "openai"
    assert est.model == "gpt-4o-mini"
    assert result.estimation == "## Estimación: Test\nContenido"
    assert (est.input_tokens, est.output_tokens, est.total_tokens) == (120, 80, 200)
    assert est.original_cost_usd == pytest.approx((120 * 0.15 + 80 * 0.60) / 1e6)
    assert isinstance(result.generated_at, datetime)
    assert result.latency_ms >= 0


async def test_generate_estimation_anthropic_substitutes_default_model():
    adapter, create = anthropic_sdk(
        anthropic_response("## Estimación: Test Anthropic\nContenido", input_tokens=150, output_tokens=90)
    )
    settings = anthropic_settings(llm_model="gpt-4o-mini")  # default OpenAI → claude-haiku-4-5
    result = await _service(settings, anthropic=adapter).generate(LONG_TRANSCRIPTION)

    assert create.call_args.kwargs["model"] == "claude-haiku-4-5"
    est = result.estimation_phase
    assert (est.provider, est.model) == ("anthropic", "claude-haiku-4-5")
    assert est.total_tokens == 240


async def test_empty_response_raises_controlled_error():
    adapter, _ = openai_sdk(openai_response("   "))
    with pytest.raises(LLMEmptyResponseError):
        await _service(openai_settings(), openai=adapter).generate(LONG_TRANSCRIPTION)


def _openai_auth():
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return OpenAIAuthError("invalid key", response=httpx.Response(401, request=req), body={})


def _anthropic_auth():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return AnthropicAuthError("invalid key", response=httpx.Response(401, request=req), body={})


async def test_openai_auth_error_is_translated():
    adapter, _ = openai_sdk(_openai_auth())
    with pytest.raises(LLMAuthError):
        await _service(openai_settings(), openai=adapter).generate(LONG_TRANSCRIPTION)


async def test_openai_timeout_is_translated_and_retried_within_the_limit():
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    adapter, create = openai_sdk(OpenAITimeout(request=req), OpenAITimeout(request=req))
    with pytest.raises(LLMTimeoutError):
        await _service(openai_settings(llm_max_retries=1), openai=adapter).generate(LONG_TRANSCRIPTION)
    assert create.await_count == 2  # 1 intento + 1 reintento


async def test_anthropic_auth_error_is_translated_and_not_retried():
    adapter, create = anthropic_sdk(_anthropic_auth())
    with pytest.raises(LLMAuthError):
        await _service(anthropic_settings(), anthropic=adapter).generate(LONG_TRANSCRIPTION)
    assert create.await_count == 1


async def test_anthropic_timeout_is_translated():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    adapter, _ = anthropic_sdk(AnthropicTimeout(request=req))
    with pytest.raises(LLMTimeoutError):
        await _service(anthropic_settings(llm_max_retries=0), anthropic=adapter).generate(
            LONG_TRANSCRIPTION
        )
