"""Flujo de generación: opciones por solicitud, modos de preprocesamiento y metadatos."""

import asyncio
import time

import pytest

from app.context.examples import ESTIMATION_EXAMPLES
from app.llm.errors import LLMEmptyResponseError, LLMProviderError, ModelSelectionError
from app.services.estimation_service import GenerationOptions
from app.services.prompts import EXTRACTION_MAX_TOKENS, EXTRACTION_SYSTEM_PROMPT
from app.services.reporting import build_metadata
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

ESTIMATION = ESTIMATION_EXAMPLES[0]["estimation"].strip()
REQUIREMENTS = "### Requisitos funcionales\n- Login con roles\n- Exportar a Excel"


class _Harness:
    """Servicio real con el adaptador real sobre un SDK simulado."""

    def __init__(self):
        self.settings = None
        self.providers = {}

    def settings_(self, settings):
        self.settings = settings

    async def __call__(self, transcription, options=None):
        service = make_resources(self.settings, dict(self.providers)).service
        return await service.generate(transcription, options)


@pytest.fixture
def h():
    return _Harness()


def patch_settings(h, settings):
    h.settings_(settings)


def patch_openai(h, *outcomes):
    adapter, create = openai_sdk(*outcomes)
    h.providers["openai"] = adapter
    return create


def patch_anthropic(h, *outcomes):
    adapter, create = anthropic_sdk(*outcomes)
    h.providers["anthropic"] = adapter
    return create


def _system(create, call=0) -> str:
    return create.call_args_list[call].kwargs["messages"][0]["content"]


def _user(create, call=0) -> str:
    return create.call_args_list[call].kwargs["messages"][1]["content"]


# --- valores por defecto: comportamiento previo ------------------------------


async def test_defaults_make_one_call_with_previous_behaviour(h):
    patch_settings(h, openai_settings())
    create = patch_openai(h, openai_response(ESTIMATION))

    result = await h(LONG_TRANSCRIPTION)

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


async def test_anthropic_default_max_tokens_is_4096(h):
    patch_settings(h, anthropic_settings())
    create = patch_anthropic(h, anthropic_response(ESTIMATION))
    await h(LONG_TRANSCRIPTION)
    assert create.call_args.kwargs["max_tokens"] == 4096
    assert create.call_args.kwargs["model"] == "claude-haiku-4-5"


# --- opciones por solicitud ---------------------------------------------------


async def test_model_and_max_tokens_overrides_reach_openai(h):
    patch_settings(h, openai_settings())
    create = patch_openai(h, openai_response(ESTIMATION, model="gpt-4o"))
    result = await h(
        LONG_TRANSCRIPTION, GenerationOptions(model="gpt-4o", max_tokens=1234)
    )
    assert create.call_args.kwargs["model"] == "gpt-4o"
    assert create.call_args.kwargs["max_completion_tokens"] == 1234
    assert result.estimation_phase.model == "gpt-4o"


async def test_model_and_max_tokens_overrides_reach_anthropic(h):
    patch_settings(h, anthropic_settings())
    create = patch_anthropic(h, anthropic_response(ESTIMATION, model="claude-opus-4-8"))
    await h(
        LONG_TRANSCRIPTION, GenerationOptions(model="claude-opus-4-8", max_tokens=900)
    )
    assert create.call_args.kwargs["model"] == "claude-opus-4-8"
    assert create.call_args.kwargs["max_tokens"] == 900


async def test_example_options_shape_the_system_prompt(h):
    patch_settings(h, openai_settings())
    create = patch_openai(h, openai_response(ESTIMATION), openai_response(ESTIMATION))

    await h(
        LONG_TRANSCRIPTION, GenerationOptions(num_examples=4, example_format="json")
    )
    assert '"desglose_de_tareas"' in _system(create, 0)

    await h(LONG_TRANSCRIPTION, GenerationOptions(use_examples=False))
    assert "Historical Reference Examples" not in _system(create, 1)


async def test_model_outside_allowlist_is_rejected_before_calling_the_provider(h):
    patch_settings(h, openai_settings(allowed_models="gpt-4o-mini,gpt-4o"))
    create = patch_openai(h, openai_response(ESTIMATION))
    with pytest.raises(ModelSelectionError):
        await h(LONG_TRANSCRIPTION, GenerationOptions(model="o1-pro"))
    create.assert_not_awaited()


async def test_allowlisted_model_is_accepted(h):
    patch_settings(h, openai_settings(allowed_models="gpt-4o-mini,gpt-4o"))
    create = patch_openai(h, openai_response(ESTIMATION))
    await h(LONG_TRANSCRIPTION, GenerationOptions(model="gpt-4o"))
    assert create.call_args.kwargs["model"] == "gpt-4o"


# --- preprocesamiento: limpieza en el prompt ----------------------------------


async def test_inline_cleaning_adds_instructions_but_keeps_a_single_call(h):
    patch_settings(h, openai_settings())
    create = patch_openai(h, openai_response(ESTIMATION))

    result = await h(
        LONG_TRANSCRIPTION, GenerationOptions(preprocessing="inline_cleaning")
    )

    assert create.await_count == 1
    assert "Transcript Preparation" in _system(create)
    assert "Do not invent requirements" in _system(create)  # reglas originales intactas
    assert _user(create) == LONG_TRANSCRIPTION  # la transcripción viaja sin modificar
    assert result.preprocessing == "inline_cleaning"
    assert result.extracted_requirements is None
    assert len(result.phases) == 1


# --- preprocesamiento: dos fases ------------------------------------------------


async def test_two_phase_extracts_requirements_then_estimates_from_them(h):
    patch_settings(h, openai_settings())
    create = patch_openai(
        h,
        openai_response(REQUIREMENTS, prompt_tokens=300, completion_tokens=40),
        openai_response(ESTIMATION, prompt_tokens=2000, completion_tokens=900),
    )

    result = await h(
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


async def test_two_phase_reports_usage_per_phase_and_aggregates_totals(h):
    patch_settings(h, openai_settings())
    patch_openai(
        h,
        openai_response(REQUIREMENTS, prompt_tokens=300, completion_tokens=40, finish_reason="length"),
        openai_response(ESTIMATION, prompt_tokens=2000, completion_tokens=900),
    )
    result = await h(
        LONG_TRANSCRIPTION, GenerationOptions(preprocessing="two_phase")
    )
    pre, est = result.phases
    assert (pre.phase, pre.llm.input_tokens, pre.llm.output_tokens, pre.llm.total_tokens) == (
        "preprocessing", 300, 40, 340,
    )
    assert pre.llm.finish_reason == "length"
    assert (est.phase, est.llm.input_tokens, est.llm.output_tokens, est.llm.total_tokens) == (
        "estimation", 2000, 900, 2900,
    )
    meta = build_metadata(result, pricing_source="test")
    assert meta.usage.input_tokens == 2300
    assert meta.usage.output_tokens == 940
    assert meta.usage.total_tokens == 3240
    assert meta.finish_reason == "stop"  # el de la estimación, no el de la extracción
    assert all(p.llm.latency_ms >= 0 for p in result.phases)


async def test_two_phase_works_with_anthropic(h):
    patch_settings(h, anthropic_settings())
    create = patch_anthropic(
        h,
        anthropic_response(REQUIREMENTS, input_tokens=200, output_tokens=30),
        anthropic_response(ESTIMATION, input_tokens=1500, output_tokens=700),
    )
    result = await h(
        LONG_TRANSCRIPTION, GenerationOptions(preprocessing="two_phase")
    )
    assert create.call_args_list[0].kwargs["system"] == EXTRACTION_SYSTEM_PROMPT
    assert create.call_args_list[0].kwargs["max_tokens"] == EXTRACTION_MAX_TOKENS
    assert REQUIREMENTS in create.call_args_list[1].kwargs["messages"][0]["content"]
    assert build_metadata(result, pricing_source="t").usage.total_tokens == 200 + 30 + 1500 + 700


async def test_two_phase_empty_extraction_fails_without_estimating(h):
    patch_settings(h, openai_settings())
    create = patch_openai(h, openai_response("   "), openai_response(ESTIMATION))
    with pytest.raises(LLMEmptyResponseError):
        await h(LONG_TRANSCRIPTION, GenerationOptions(preprocessing="two_phase"))
    assert create.await_count == 1


async def test_two_phase_provider_error_in_second_phase_is_controlled(h):
    patch_settings(h, openai_settings())
    patch_openai(h, openai_response(REQUIREMENTS), RuntimeError("secreto interno"))
    with pytest.raises(LLMProviderError) as exc:
        await h(LONG_TRANSCRIPTION, GenerationOptions(preprocessing="two_phase"))
    assert "secreto" not in str(exc.value)


# --- metadatos de respuesta -----------------------------------------------------


async def test_finish_reason_is_reported_for_openai_and_anthropic(h):
    patch_settings(h, openai_settings())
    patch_openai(h, openai_response(ESTIMATION, finish_reason="length"))
    assert (await h(LONG_TRANSCRIPTION)).estimation_phase.finish_reason == "length"

    patch_settings(h, anthropic_settings())
    patch_anthropic(h, anthropic_response(ESTIMATION, stop_reason="max_tokens"))
    assert (await h(LONG_TRANSCRIPTION)).estimation_phase.finish_reason == "max_tokens"


async def test_missing_finish_reason_is_reported_as_unknown(h):
    patch_settings(h, openai_settings())
    patch_openai(h, openai_response(ESTIMATION, finish_reason=None))
    assert (await h(LONG_TRANSCRIPTION)).estimation_phase.finish_reason == "unknown"


async def test_anthropic_ignores_non_text_blocks(h):
    from types import SimpleNamespace

    thinking = SimpleNamespace(type="thinking", thinking="razonando...")
    patch_settings(h, anthropic_settings())
    patch_anthropic(h, anthropic_response(ESTIMATION, extra_blocks=(thinking,)))
    assert (await h(LONG_TRANSCRIPTION)).estimation == ESTIMATION


# --- el proveedor se espera sin bloquear el event loop ---------------------------


async def test_concurrent_requests_overlap_because_provider_calls_are_awaited(h):
    patch_settings(h, openai_settings())

    async def slow_create(**kwargs):
        await asyncio.sleep(0.3)
        return openai_response(ESTIMATION)

    create = patch_openai(h)
    create.side_effect = slow_create
    service = make_resources(h.settings, dict(h.providers)).service

    start = time.monotonic()
    # Transcripciones distintas: las idénticas se deduplicarían (ver test_llm_client).
    await asyncio.gather(
        *(service.generate(f"{LONG_TRANSCRIPTION} #{i}") for i in range(4))
    )
    elapsed = time.monotonic() - start
    assert create.await_count == 4
    # En serie serían ≥1.2 s; si el event loop no se bloquea, ronda los 0.3 s.
    assert elapsed < 0.9
