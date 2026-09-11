from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.context.examples import ESTIMATION_EXAMPLES
from app.services.llm_service import LLMEstimationResult, build_system_prompt, generate_estimation


def test_prompt_contains_role():
    prompt = build_system_prompt()
    assert "Senior Software Estimation Architect" in prompt


def test_prompt_contains_all_example_summaries():
    prompt = build_system_prompt()
    for ex in ESTIMATION_EXAMPLES:
        assert ex["meeting_summary"][:60] in prompt


def test_prompt_contains_all_example_estimations():
    prompt = build_system_prompt()
    for ex in ESTIMATION_EXAMPLES:
        assert ex["estimation"][:60] in prompt


def test_prompt_contains_output_format_markers():
    # The output template uses Spanish headers (output language is Spanish)
    prompt = build_system_prompt()
    assert "Estimación:" in prompt
    assert "Supuestos" in prompt
    assert "Riesgos" in prompt
    assert "Preguntas abiertas" in prompt


def test_prompt_instructs_assumptions_over_invention():
    # Instructions are in English
    prompt = build_system_prompt()
    lower = prompt.lower()
    assert "assumption" in lower


def test_prompt_is_substantial():
    prompt = build_system_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 800


# ---------------------------------------------------------------------------
# Task 5: async dispatch tests
# ---------------------------------------------------------------------------

def _openai_settings() -> Settings:
    return Settings(
        llm_provider="openai",
        openai_api_key="sk-test",
        llm_model="gpt-4o-mini",
        _env_file=None,
    )


def _anthropic_settings() -> Settings:
    return Settings(
        llm_provider="anthropic",
        anthropic_api_key="sk-ant-test",
        llm_model="gpt-4o-mini",  # OpenAI default — must be substituted to claude-haiku-4-5
        _env_file=None,
    )


@pytest.mark.asyncio
async def test_generate_estimation_openai(mocker):
    mocker.patch("app.services.llm_service.get_settings", return_value=_openai_settings())

    usage = MagicMock(prompt_tokens=120, completion_tokens=80, total_tokens=200)
    choice = MagicMock()
    choice.message.content = "## Estimación: Test\nContenido"
    mock_response = MagicMock(choices=[choice], usage=usage, model="gpt-4o-mini")

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mocker.patch("app.services.llm_service.AsyncOpenAI", return_value=mock_client)

    result = await generate_estimation("Transcripción suficientemente larga para ser válida en el test")

    assert isinstance(result, LLMEstimationResult)
    assert result.provider == "openai"
    assert result.model == "gpt-4o-mini"
    assert result.estimation == "## Estimación: Test\nContenido"
    assert result.input_tokens == 120
    assert result.output_tokens == 80
    assert result.total_tokens == 200
    assert result.estimated_cost_usd is None
    assert isinstance(result.generated_at, datetime)
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_generate_estimation_anthropic_substitutes_default_model(mocker):
    mocker.patch("app.services.llm_service.get_settings", return_value=_anthropic_settings())

    usage = MagicMock(input_tokens=150, output_tokens=90)
    content_block = MagicMock()
    content_block.text = "## Estimación: Test Anthropic\nContenido"
    mock_response = MagicMock(content=[content_block], usage=usage, model="claude-haiku-4-5")

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    mocker.patch("app.services.llm_service.AsyncAnthropic", return_value=mock_client)

    result = await generate_estimation("Transcripción suficientemente larga para ser válida en el test")

    assert result.provider == "anthropic"
    assert result.model == "claude-haiku-4-5"
    assert result.estimation == "## Estimación: Test Anthropic\nContenido"
    assert result.input_tokens == 150
    assert result.output_tokens == 90
    assert result.total_tokens == 240
    assert result.estimated_cost_usd is None


@pytest.mark.asyncio
async def test_generate_estimation_raises_502_on_empty_response(mocker):
    mocker.patch("app.services.llm_service.get_settings", return_value=_openai_settings())

    choice = MagicMock()
    choice.message.content = "   "  # whitespace only — counts as empty
    mock_response = MagicMock(
        choices=[choice],
        usage=MagicMock(prompt_tokens=10, completion_tokens=0, total_tokens=10),
        model="gpt-4o-mini",
    )
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    mocker.patch("app.services.llm_service.AsyncOpenAI", return_value=mock_client)

    with pytest.raises(HTTPException) as exc_info:
        await generate_estimation("Transcripción suficientemente larga para ser válida en el test")
    assert exc_info.value.status_code == 502
