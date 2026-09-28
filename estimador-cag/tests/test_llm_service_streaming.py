"""Streaming con los adaptadores reales (SDK simulados) a través del servicio."""

import httpx
import pytest
from openai import APIConnectionError

from app.llm.errors import LLMStreamInterruptedError
from app.services.estimation_service import ContentDelta, EstimationCompleted
from tests._fakes import (
    LONG_TRANSCRIPTION,
    anthropic_response,
    anthropic_settings,
    anthropic_stream_sdk,
    make_resources,
    openai_settings,
    openai_stream_chunks,
    openai_stream_sdk,
)


async def _collect(service):
    deltas, final = [], None
    async for event in service.stream(LONG_TRANSCRIPTION):
        if isinstance(event, ContentDelta):
            deltas.append(event.text)
        elif isinstance(event, EstimationCompleted):
            final = event.result
    return deltas, final


async def test_stream_openai_yields_deltas_in_order_and_real_metadata():
    adapter, create, _ = openai_stream_sdk(
        openai_stream_chunks(["Hola ", "mundo"], model="gpt-4o-mini-2024-07-18",
                             prompt_tokens=120, completion_tokens=30)
    )
    service = make_resources(openai_settings(), {"openai": adapter}).service
    deltas, final = await _collect(service)

    assert deltas == ["Hola ", "mundo"]
    est = final.estimation_phase
    assert est.model == "gpt-4o-mini-2024-07-18"  # el que respondió, no el solicitado
    assert est.requested_model == "gpt-4o-mini"
    assert (est.input_tokens, est.output_tokens) == (120, 30)
    assert est.finish_reason == "stop"  # confirmado por el proveedor
    assert est.original_cost_usd is not None  # instantánea fechada con tarifa conocida
    kwargs = create.call_args.kwargs
    assert kwargs["stream"] is True and kwargs["stream_options"] == {"include_usage": True}
    assert "Senior Software Estimation Architect" in kwargs["messages"][0]["content"]


async def test_stream_without_usage_reports_unknown_tokens_and_cost_not_zero():
    adapter, _, _ = openai_stream_sdk(
        openai_stream_chunks(["Hola"], include_usage=False, finish_reason=None)
    )
    service = make_resources(openai_settings(), {"openai": adapter}).service
    _, final = await _collect(service)
    est = final.estimation_phase
    assert est.input_tokens is None and est.output_tokens is None and est.total_tokens is None
    assert est.original_cost_usd is None and est.incurred_cost_usd is None
    assert est.finish_reason == "unknown"


async def test_stream_anthropic_yields_deltas_and_metrics():
    final_message = anthropic_response("Hola mundo", model="claude-haiku-4-5",
                                       input_tokens=150, output_tokens=40)
    adapter, _ = anthropic_stream_sdk(["Hola ", "mundo"], final_message)
    service = make_resources(anthropic_settings(), {"anthropic": adapter}).service
    deltas, final = await _collect(service)
    assert deltas == ["Hola ", "mundo"]
    est = final.estimation_phase
    assert (est.model, est.input_tokens, est.output_tokens, est.finish_reason) == (
        "claude-haiku-4-5", 150, 40, "end_turn",
    )


async def test_provider_failure_after_content_interrupts_without_retry():
    error = APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"))
    chunks = openai_stream_chunks(["Parcial"])[:1]  # sin fin ni uso
    adapter, create, stream = openai_stream_sdk(chunks, error=error)
    service = make_resources(openai_settings(llm_max_retries=3), {"openai": adapter}).service
    with pytest.raises(LLMStreamInterruptedError):
        await _collect(service)
    assert create.await_count == 1  # no se reintenta tras emitir contenido
    assert stream.closed  # el stream del SDK se cierra
