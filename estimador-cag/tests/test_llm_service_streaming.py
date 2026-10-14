import pytest

from app.services.llm_service import StreamMetrics, generate_estimation_stream
from tests._fakes import (
    LONG_TRANSCRIPTION,
    anthropic_final_message,
    anthropic_settings,
    openai_settings,
    openai_stream_chunks,
    patch_anthropic_stream,
    patch_openai_stream,
    patch_settings,
)


@pytest.mark.asyncio
async def test_stream_openai_yields_deltas_in_order(mocker):
    patch_settings(mocker, openai_settings())
    patch_openai_stream(mocker, openai_stream_chunks(["Hola ", "mundo"]))

    metrics = StreamMetrics()
    chunks = [c async for c in generate_estimation_stream(LONG_TRANSCRIPTION, metrics)]

    assert chunks == ["Hola ", "mundo"]


@pytest.mark.asyncio
async def test_stream_openai_populates_metrics(mocker):
    patch_settings(mocker, openai_settings())
    patch_openai_stream(
        mocker,
        openai_stream_chunks(["Hola"], model="gpt-4o-mini", prompt_tokens=120, completion_tokens=30),
    )

    metrics = StreamMetrics()
    async for _ in generate_estimation_stream(LONG_TRANSCRIPTION, metrics):
        pass

    assert metrics.model == "gpt-4o-mini"
    assert metrics.input_tokens == 120
    assert metrics.output_tokens == 30
    assert metrics.latency_ms >= 0


@pytest.mark.asyncio
async def test_stream_anthropic_yields_deltas_and_metrics(mocker):
    patch_settings(mocker, anthropic_settings())
    final = anthropic_final_message("Hola mundo", model="claude-haiku-4-5", input_tokens=150, output_tokens=40)
    patch_anthropic_stream(mocker, ["Hola ", "mundo"], final)

    metrics = StreamMetrics()
    chunks = [c async for c in generate_estimation_stream(LONG_TRANSCRIPTION, metrics)]

    assert chunks == ["Hola ", "mundo"]
    assert metrics.model == "claude-haiku-4-5"
    assert metrics.input_tokens == 150
    assert metrics.output_tokens == 40


@pytest.mark.asyncio
async def test_stream_uses_shared_system_prompt(mocker):
    patch_settings(mocker, openai_settings())
    create = patch_openai_stream(mocker, openai_stream_chunks(["ok"]))

    metrics = StreamMetrics()
    async for _ in generate_estimation_stream(LONG_TRANSCRIPTION, metrics):
        pass

    kwargs = create.call_args.kwargs
    assert kwargs["stream"] is True
    assert kwargs["messages"][0]["role"] == "system"
    assert "Senior Software Estimation Architect" in kwargs["messages"][0]["content"]
