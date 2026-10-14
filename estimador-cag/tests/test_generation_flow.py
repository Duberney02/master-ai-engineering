"""Flujo de generación: opciones por solicitud, modos de preprocesamiento y metadatos."""

import asyncio
import time

import pytest
from fastapi import HTTPException

from app.context.examples import ESTIMATION_EXAMPLES
from app.services.llm_service import (
    EXTRACTION_MAX_TOKENS,
    EXTRACTION_SYSTEM_PROMPT,
    GenerationOptions,
    generate_estimation,
)
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

ESTIMATION = ESTIMATION_EXAMPLES[0]["estimation"].strip()
REQUIREMENTS = "### Requisitos funcionales\n- Login con roles\n- Exportar a Excel"


def _system(create, call=0) -> str:
    return create.call_args_list[call].kwargs["messages"][0]["content"]


def _user(create, call=0) -> str:
    return create.call_args_list[call].kwargs["messages"][1]["content"]


# --- valores por defecto: comportamiento previo ------------------------------


async def test_defaults_make_one_call_with_previous_behaviour(mocker):
    patch_settings(mocker, openai_settings())
    create = patch_openai(mocker, openai_response(ESTIMATION))

    result = await generate_estimation(LONG_TRANSCRIPTION)

    assert create.await_count == 1
    kwargs = create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["temperature"] == 0.3
    assert "max_completion_tokens" not in kwargs  # sin límite explícito, como antes
    assert _user(create) == LONG_TRANSCRIPTION
    assert _system(create).count("### Historical Example") == 2
    assert "Transcript Preparation" not in _system(create)
    assert result.preprocessing == "none"
    assert result.extracted_requirements is None
    assert [p.phase for p in result.phases] == ["estimation"]


async def test_anthropic_default_max_tokens_is_4096(mocker):
    patch_settings(mocker, anthropic_settings())
    create = patch_anthropic(mocker, anthropic_response(ESTIMATION))
    await generate_estimation(LONG_TRANSCRIPTION)
    assert create.call_args.kwargs["max_tokens"] == 4096
    assert create.call_args.kwargs["model"] == "claude-haiku-4-5"


# --- opciones por solicitud ---------------------------------------------------


async def test_model_and_max_tokens_overrides_reach_openai(mocker):
    patch_settings(mocker, openai_settings())
    create = patch_openai(mocker, openai_response(ESTIMATION, model="gpt-4o"))
    result = await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(model="gpt-4o", max_tokens=1234))
    assert create.call_args.kwargs["model"] == "gpt-4o"
    assert create.call_args.kwargs["max_completion_tokens"] == 1234
    assert result.model == "gpt-4o"


async def test_model_and_max_tokens_overrides_reach_anthropic(mocker):
    patch_settings(mocker, anthropic_settings())
    create = patch_anthropic(mocker, anthropic_response(ESTIMATION, model="claude-opus-4-8"))
    await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(model="claude-opus-4-8", max_tokens=900))
    assert create.call_args.kwargs["model"] == "claude-opus-4-8"
    assert create.call_args.kwargs["max_tokens"] == 900


async def test_example_options_shape_the_system_prompt(mocker):
    patch_settings(mocker, openai_settings())
    create = patch_openai(mocker, openai_response(ESTIMATION), openai_response(ESTIMATION))

    await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(num_examples=4, example_format="json"))
    assert '"desglose_de_tareas"' in _system(create, 0)

    await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(use_examples=False))
    assert "Historical Reference Examples" not in _system(create, 1)


async def test_model_outside_allowlist_is_rejected_before_calling_the_provider(mocker):
    patch_settings(mocker, openai_settings(allowed_models="gpt-4o-mini,gpt-4o"))
    create = patch_openai(mocker, openai_response(ESTIMATION))
    with pytest.raises(HTTPException) as exc:
        await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(model="o1-pro"))
    assert exc.value.status_code == 422
    create.assert_not_awaited()


async def test_allowlisted_model_is_accepted(mocker):
    patch_settings(mocker, openai_settings(allowed_models="gpt-4o-mini,gpt-4o"))
    create = patch_openai(mocker, openai_response(ESTIMATION))
    await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(model="gpt-4o"))
    assert create.call_args.kwargs["model"] == "gpt-4o"


# --- preprocesamiento: limpieza en el prompt ----------------------------------


async def test_inline_cleaning_adds_instructions_but_keeps_a_single_call(mocker):
    patch_settings(mocker, openai_settings())
    create = patch_openai(mocker, openai_response(ESTIMATION))

    result = await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(preprocessing="inline_cleaning"))

    assert create.await_count == 1
    assert "Transcript Preparation" in _system(create)
    assert "Do not invent requirements" in _system(create)  # reglas originales intactas
    assert _user(create) == LONG_TRANSCRIPTION  # la transcripción viaja sin modificar
    assert result.preprocessing == "inline_cleaning"
    assert result.extracted_requirements is None
    assert len(result.phases) == 1


# --- preprocesamiento: dos fases ------------------------------------------------


async def test_two_phase_extracts_requirements_then_estimates_from_them(mocker):
    patch_settings(mocker, openai_settings())
    create = patch_openai(
        mocker,
        openai_response(REQUIREMENTS, prompt_tokens=300, completion_tokens=40),
        openai_response(ESTIMATION, prompt_tokens=2000, completion_tokens=900),
    )

    result = await generate_estimation(
        LONG_TRANSCRIPTION, GenerationOptions(preprocessing="two_phase", max_tokens=3000)
    )

    assert create.await_count == 2
    # Fase 1: prompt de extracción, transcripción original, límite propio.
    assert _system(create, 0) == EXTRACTION_SYSTEM_PROMPT
    assert _user(create, 0) == LONG_TRANSCRIPTION
    assert create.call_args_list[0].kwargs["max_completion_tokens"] == EXTRACTION_MAX_TOKENS
    # Fase 2: estimación con el prompt normal a partir de los requisitos extraídos.
    assert "Senior Software Estimation Architect" in _system(create, 1)
    assert "Transcript Preparation" not in _system(create, 1)
    assert REQUIREMENTS in _user(create, 1)
    assert LONG_TRANSCRIPTION not in _user(create, 1)
    assert create.call_args_list[1].kwargs["max_completion_tokens"] == 3000

    assert result.preprocessing == "two_phase"
    assert result.extracted_requirements == REQUIREMENTS
    assert result.estimation == ESTIMATION


async def test_two_phase_reports_usage_per_phase_and_aggregates_totals(mocker):
    patch_settings(mocker, openai_settings())
    patch_openai(
        mocker,
        openai_response(REQUIREMENTS, prompt_tokens=300, completion_tokens=40, finish_reason="length"),
        openai_response(ESTIMATION, prompt_tokens=2000, completion_tokens=900),
    )
    result = await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(preprocessing="two_phase"))
    pre, est = result.phases
    assert (pre.phase, pre.input_tokens, pre.output_tokens, pre.total_tokens) == (
        "preprocessing",
        300,
        40,
        340,
    )
    assert pre.finish_reason == "length"
    assert (est.phase, est.input_tokens, est.output_tokens, est.total_tokens) == (
        "estimation",
        2000,
        900,
        2900,
    )
    assert result.input_tokens == 2300
    assert result.output_tokens == 940
    assert result.total_tokens == 3240
    assert result.finish_reason == "stop"  # el de la estimación, no el de la extracción
    assert all(p.latency_ms >= 0 for p in result.phases)


async def test_two_phase_works_with_anthropic(mocker):
    patch_settings(mocker, anthropic_settings())
    create = patch_anthropic(
        mocker,
        anthropic_response(REQUIREMENTS, input_tokens=200, output_tokens=30),
        anthropic_response(ESTIMATION, input_tokens=1500, output_tokens=700),
    )
    result = await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(preprocessing="two_phase"))
    assert create.call_args_list[0].kwargs["system"] == EXTRACTION_SYSTEM_PROMPT
    assert create.call_args_list[0].kwargs["max_tokens"] == EXTRACTION_MAX_TOKENS
    assert REQUIREMENTS in create.call_args_list[1].kwargs["messages"][0]["content"]
    assert result.total_tokens == 200 + 30 + 1500 + 700


async def test_two_phase_empty_extraction_fails_without_estimating(mocker):
    patch_settings(mocker, openai_settings())
    create = patch_openai(mocker, openai_response("   "), openai_response(ESTIMATION))
    with pytest.raises(HTTPException) as exc:
        await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(preprocessing="two_phase"))
    assert exc.value.status_code == 502
    assert create.await_count == 1


async def test_two_phase_provider_error_in_second_phase_is_controlled(mocker):
    patch_settings(mocker, openai_settings())
    patch_openai(mocker, openai_response(REQUIREMENTS), RuntimeError("secreto interno"))
    with pytest.raises(HTTPException) as exc:
        await generate_estimation(LONG_TRANSCRIPTION, GenerationOptions(preprocessing="two_phase"))
    assert exc.value.status_code == 502
    assert "secreto" not in str(exc.value.detail)


# --- metadatos de respuesta -----------------------------------------------------


async def test_finish_reason_is_reported_for_openai_and_anthropic(mocker):
    patch_settings(mocker, openai_settings())
    patch_openai(mocker, openai_response(ESTIMATION, finish_reason="length"))
    assert (await generate_estimation(LONG_TRANSCRIPTION)).finish_reason == "length"

    patch_settings(mocker, anthropic_settings())
    patch_anthropic(mocker, anthropic_response(ESTIMATION, stop_reason="max_tokens"))
    assert (await generate_estimation(LONG_TRANSCRIPTION)).finish_reason == "max_tokens"


async def test_missing_finish_reason_is_reported_as_unknown(mocker):
    patch_settings(mocker, openai_settings())
    patch_openai(mocker, openai_response(ESTIMATION, finish_reason=None))
    assert (await generate_estimation(LONG_TRANSCRIPTION)).finish_reason == "unknown"


async def test_anthropic_ignores_non_text_blocks(mocker):
    from types import SimpleNamespace

    thinking = SimpleNamespace(type="thinking", thinking="razonando...")
    patch_settings(mocker, anthropic_settings())
    patch_anthropic(mocker, anthropic_response(ESTIMATION, extra_blocks=(thinking,)))
    assert (await generate_estimation(LONG_TRANSCRIPTION)).estimation == ESTIMATION


# --- el proveedor se espera sin bloquear el event loop ---------------------------


async def test_concurrent_requests_overlap_because_provider_calls_are_awaited(mocker):
    patch_settings(mocker, openai_settings())

    async def slow_create(**kwargs):
        await asyncio.sleep(0.3)
        return openai_response(ESTIMATION)

    from unittest.mock import AsyncMock, MagicMock

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=slow_create)
    mocker.patch("app.services.llm_service.AsyncOpenAI", return_value=client)

    start = time.monotonic()
    await asyncio.gather(*(generate_estimation(LONG_TRANSCRIPTION) for _ in range(4)))
    elapsed = time.monotonic() - start
    # En serie serían ≥1.2 s; si el event loop no se bloquea, ronda los 0.3 s.
    assert elapsed < 0.9
