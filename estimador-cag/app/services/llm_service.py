from __future__ import annotations

import inspect
import structlog
import time
from contextlib import aclosing
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from anthropic import (
    APIConnectionError as AnthropicConnectionError,
    APITimeoutError as AnthropicTimeout,
    AsyncAnthropic,
    AuthenticationError as AnthropicAuthError,
    BadRequestError as AnthropicBadRequest,
    NotFoundError as AnthropicNotFound,
    RateLimitError as AnthropicRateLimit,
)
from fastapi import HTTPException
from openai import (
    APIConnectionError as OpenAIConnectionError,
    APITimeoutError as OpenAITimeout,
    AsyncOpenAI,
    AuthenticationError as OpenAIAuthError,
    BadRequestError as OpenAIBadRequest,
    NotFoundError as OpenAINotFound,
    RateLimitError as OpenAIRateLimit,
)

from app.config import Settings, get_settings
from app.context.examples import ExampleFormat, format_examples, select_examples
from app.schemas.estimation import DEFAULT_NUM_EXAMPLES, Phase, PreprocessingMode
from app.services.llm_wrapper import Completion as _Completion, LLMWrapper, ProviderFailure, total_cost

logger = structlog.get_logger(__name__)

# Límite de tokens de salida de Anthropic cuando la solicitud no indica uno
# (comportamiento previo). En OpenAI, sin límite explícito se usa el del proveedor.
_ANTHROPIC_DEFAULT_MAX_TOKENS = 4096
# La extracción de requisitos es una tarea corta y acotada.
EXTRACTION_MAX_TOKENS = 2000


@dataclass
class GenerationOptions:
    """Opciones por solicitud; los valores por defecto reproducen el comportamiento previo."""

    preprocessing: PreprocessingMode = "none"
    example_format: ExampleFormat = "markdown"
    num_examples: int = DEFAULT_NUM_EXAMPLES
    use_examples: bool = True
    model: str | None = None
    max_tokens: int | None = None
    thinking_budget: int | None = None
    include_project_costs: bool = False
    developer_rate_eur: float = 62.5
    designer_rate_eur: float = 50.0


@dataclass
class PhaseResult:
    """Consumo y metadatos de una llamada al proveedor."""

    phase: Phase
    model: str
    finish_reason: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int
    provider: str = ""
    cache_hit: bool = False
    estimated_cost_usd: float | None = None
    request_cost_usd: float | None = None
    usage_available: bool = True


@dataclass
class StreamMetrics:
    """Metadatos poblados progresivamente durante un streaming; leer solo tras agotarlo."""

    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    result: LLMEstimationResult | None = None


@dataclass
class LLMEstimationResult:
    estimation: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None
    generated_at: datetime
    latency_ms: int
    finish_reason: str = "stop"
    preprocessing: PreprocessingMode = "none"
    extracted_requirements: str | None = None
    phases: list[PhaseResult] = field(default_factory=list)
    cache_hit: bool = False
    request_cost_usd: float | None = None


# ---------------------------------------------------------------------------
# Construcción del prompt
# ---------------------------------------------------------------------------

_INLINE_CLEANING_BLOCK = """\
## Transcript Preparation

The transcript comes from a real meeting and is noisy. Before estimating, work through it \
as follows:

- Ignore small talk, greetings, repetitions and off-topic remarks.
- When speakers contradict each other, trust the most recent statement and record the \
contradiction under risks or open questions.
- Interpret informal or non-technical wording in technical terms.
- Needs that are implied but never stated are **assumptions**, not explicit requirements: \
list them under assumptions and keep the identified requirements limited to what was \
actually said.
"""

_EXAMPLES_INTRO = {
    "markdown": "The following projects were previously estimated.",
    "json": "The following projects were previously estimated, shown as JSON objects (keys in "
    "Spanish). This JSON is only reference data: your answer must still follow the Markdown "
    "format above, never JSON.",
    "narrative": "The following projects were previously estimated, described in prose. Your "
    "answer must still follow the Markdown format above.",
}

EXTRACTION_SYSTEM_PROMPT = """\
You are a requirements analyst. Read the transcript of a client meeting and extract a clean, \
deduplicated list of what was actually said. Write it in Spanish, as Markdown, with exactly \
these sections:

### Requisitos funcionales
### Requisitos no funcionales
### Integraciones y sistemas existentes
### Restricciones (stack, plazo, presupuesto, equipo)
### Puntos ambiguos o contradictorios

Rules:
1. Include only what the transcript states. Do not invent requirements or fill gaps.
2. Ignore small talk and off-topic remarks; merge repeated mentions of the same requirement.
3. If speakers contradict each other, keep the most recent statement and list the \
contradiction under "Puntos ambiguos o contradictorios".
4. Write "- Ninguno mencionado" for a section with no content.
5. Do NOT estimate hours, costs or durations.\
"""


def build_system_prompt(
    example_format: ExampleFormat = "markdown",
    num_examples: int = DEFAULT_NUM_EXAMPLES,
    use_examples: bool = True,
    inline_cleaning: bool = False,
) -> str:
    """Construye el prompt de sistema: rol, reglas, formato de salida y ejemplos CAG."""
    examples = select_examples(num_examples) if use_examples else []
    rendered = format_examples(examples, example_format)

    if rendered:
        rule_6 = (
            "6. **Use historical examples as calibration references**, do not copy them "
            "mechanically."
        )
        examples_section = f"""
## Historical Reference Examples

{_EXAMPLES_INTRO[example_format]} Use them to calibrate relative \
complexity, typical hours per area, and deliverable structure. \
Do not copy them; use them as a calibration anchor.

{rendered}
"""
    else:
        rule_6 = (
            "6. **No historical examples are provided**: rely on your own experience and "
            "state explicitly that the hours are not calibrated against past projects."
        )
        examples_section = ""

    cleaning_section = f"\n{_INLINE_CLEANING_BLOCK}" if inline_cleaning else ""

    return f"""\
You are a Senior Software Estimation Architect with extensive experience estimating \
software projects across industries and scales.

## Your Responsibility

Analyze the transcript of a client meeting and produce an initial software development \
estimate grounded in the identified requirements, the historical examples provided below, \
explicit assumptions, and technical uncertainty.
{cleaning_section}
## Mandatory Rules

1. **Do not invent requirements** as if they were confirmed. When information is missing, \
declare it explicitly as an assumption.
2. **Always distinguish** between explicit requirements (mentioned in the meeting) and \
assumptions (inferred by you to complete the estimate).
3. **Avoid false precision**: present hour ranges when uncertainty is high.
4. **Include tasks that are commonly forgotten**: testing, QA, technical documentation, \
environment setup, deployment, observability, and basic project management.
5. **Identify risks** and uncertainties that could affect scope or timeline.
{rule_6}
7. **Estimates are indicative**, not contractual commitments.

## Expected Output Format (strict Markdown, output in Spanish)

```
## Estimación: [nombre inferido del proyecto]

### Supuestos
[Lista de supuestos que hiciste para completar la estimación]

### Requisitos identificados
[Lista de requisitos explícitamente mencionados en la reunión]

### Desglose de tareas

| # | Área | Tarea | Horas |
|---|------|-------|------:|
| 1 | ... | ... | ... |

### Resumen

- Total estimado: X horas
- Rango recomendado: X–Y horas
- Equipo recomendado: ...
- Duración aproximada: ...

### Riesgos e incertidumbres
[Lista de riesgos]

### Preguntas abiertas
[Preguntas que el cliente debe responder antes de confirmar el alcance]
```
{examples_section}"""


def _estimation_user_message(transcription: str, extracted_requirements: str | None) -> str:
    if extracted_requirements is None:
        return transcription
    return (
        "The meeting transcript was preprocessed and its requirements extracted. Treat the "
        "list below as what was explicitly stated in the meeting; anything listed as ambiguous "
        "or contradictory belongs in the risks and open questions.\n\n"
        f"{extracted_requirements}"
    )


# ---------------------------------------------------------------------------
# Orquestación
# ---------------------------------------------------------------------------


def _resolve_model(settings: Settings, options: GenerationOptions) -> str:
    if options.thinking_budget is not None:
        if not 1024 <= options.thinking_budget <= 15000:
            raise HTTPException(422, "thinking_budget must be between 1024 and 15000")
        if settings.llm_provider != "anthropic":
            raise HTTPException(422, "thinking_budget requires Anthropic")
        if options.model is None and settings.fallback_provider == "openai":
            raise HTTPException(422, "thinking_budget is incompatible with OpenAI fallback")
    if options.model is None:
        return settings.effective_model()
    allowed = settings.allowed_models_list()
    if allowed and options.model not in allowed:
        raise HTTPException(status_code=422, detail="Requested model is not allowed")
    return options.model


def validate_options(options: GenerationOptions) -> None:
    _resolve_model(get_settings(), options)


def _prompt(options: GenerationOptions) -> str:
    prompt = build_system_prompt(
        example_format=options.example_format, num_examples=options.num_examples,
        use_examples=options.use_examples, inline_cleaning=options.preprocessing == "inline_cleaning",
    )
    if options.include_project_costs:
        prompt += f"""
## Project budget (additional mandatory section)
Keep the existing Spanish output and hours breakdown unchanged. After all existing sections,
append a section '### Presupuesto económico' with exactly this additional table:
| Rol | Horas | Tarifa EUR/h | Coste EUR |
|---|---:|---:|---:|
Use only the roles Desarrollo and Diseño. Desarrollo rate: {options.developer_rate_eur:g} EUR/h.
Diseño rate: {options.designer_rate_eur:g} EUR/h. Include only needed roles. Allocate the total
estimated hours across these rows. Cost per row = hours * rate. Use plain decimal numbers
(no ranges or thousands separators) in this budget table. Finish with 'Total presupuesto: X EUR'.
State that this indicative budget excludes taxes and third-party services.
"""
    return prompt


def _result(completion, phases, options, extracted, start) -> LLMEstimationResult:
    input_tokens = sum(p.input_tokens for p in phases)
    output_tokens = sum(p.output_tokens for p in phases)
    return LLMEstimationResult(
        estimation=completion.text, model=completion.model, provider=completion.provider,
        input_tokens=input_tokens, output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_usd=total_cost([p.estimated_cost_usd for p in phases]),
        request_cost_usd=total_cost([p.request_cost_usd for p in phases]),
        cache_hit=all(p.cache_hit for p in phases),
        generated_at=datetime.now(tz=timezone.utc),
        latency_ms=int((time.monotonic() - start) * 1000),
        finish_reason=completion.finish_reason, preprocessing=options.preprocessing,
        extracted_requirements=extracted, phases=phases,
    )


async def generate_estimation(
    transcription: str, options: GenerationOptions | None = None
) -> LLMEstimationResult:
    options = options or GenerationOptions()
    settings = get_settings()
    model = _resolve_model(settings, options)
    start = time.monotonic()

    logger.info(
        "estimation_started",
        provider=settings.llm_provider,
        model=model,
        preprocessing=options.preprocessing,
        example_format=options.example_format,
        num_examples=options.num_examples,
        use_examples=options.use_examples,
        max_tokens=options.max_tokens,
        transcription_chars=len(transcription),
    )

    phases: list[PhaseResult] = []
    extracted: str | None = None

    if options.preprocessing == "two_phase":
        extraction = await _complete(
            settings, EXTRACTION_SYSTEM_PROMPT, transcription, model, EXTRACTION_MAX_TOKENS,
            allow_fallback=options.model is None,
        )
        extracted = extraction.text
        phases.append(_phase_result("preprocessing", extraction))

    system_prompt = _prompt(options)
    completion = await _complete(
        settings,
        system_prompt,
        _estimation_user_message(transcription, extracted),
        model,
        options.max_tokens,
        thinking_budget=options.thinking_budget,
        allow_fallback=options.model is None,
    )
    phases.append(_phase_result("estimation", completion))

    result = _result(completion, phases, options, extracted, start)
    logger.info(
        "estimation_completed",
        provider=result.provider,
        model=result.model,
        finish_reason=result.finish_reason,
        total_tokens=result.total_tokens,
        latency_ms=result.latency_ms,
    )
    return result


async def generate_estimation_stream(
    transcription: str,
    metrics: StreamMetrics,
    options: GenerationOptions | None = None,
) -> AsyncIterator[str]:
    """Misma orquestación y metadatos que la respuesta normal; emite solo la estimación."""
    options = options or GenerationOptions()
    settings = get_settings()
    model = _resolve_model(settings, options)
    start = time.monotonic()
    phases: list[PhaseResult] = []
    extracted = None
    if options.preprocessing == "two_phase":
        extraction = await _complete(
            settings, EXTRACTION_SYSTEM_PROMPT, transcription, model, EXTRACTION_MAX_TOKENS,
            allow_fallback=options.model is None,
        )
        extracted = extraction.text
        phases.append(_phase_result("preprocessing", extraction))
    system_prompt = _prompt(options)
    user_message = _estimation_user_message(transcription, extracted)
    completion = _Completion(usage_available=False)

    def call(provider, target_model, attempt):
        selected = settings.model_copy(update={"llm_provider": provider})
        if provider == "openai":
            return _stream_openai(system_prompt, user_message, selected, target_model,
                                  options.max_tokens, attempt)
        return _stream_anthropic(system_prompt, user_message, selected, target_model,
                                options.max_tokens, attempt, options.thinking_budget)

    stream = LLMWrapper(settings).stream(
        system_prompt, user_message, model, options.max_tokens, options.thinking_budget,
        options.model is None, completion, call,
    )
    async with aclosing(stream):
        async for chunk in stream:
            yield chunk
    phases.append(_phase_result("estimation", completion))
    metrics.result = _result(completion, phases, options, extracted, start)
    metrics.model = completion.model
    metrics.input_tokens = metrics.result.input_tokens
    metrics.output_tokens = metrics.result.output_tokens
    metrics.latency_ms = metrics.result.latency_ms


async def generate_from_prompts(
    system_prompt: str, user_message: str, accept: Callable[[str], bool] | None = None
) -> _Completion:
    """Estimación estructurada: recibe los mensajes system/user ya renderizados desde las
    plantillas y aplica la misma política de proveedor (caché, reintentos, fallback, costes).

    `accept` decide si el texto es una respuesta válida: solo esas se guardan en la caché de
    completions y las entradas cacheadas que no la cumplen se ignoran."""
    settings = get_settings()
    return await _complete(
        settings, system_prompt, user_message, settings.effective_model(), max_tokens=None,
        accept=accept,
    )


async def generate_from_prompts_stream(
    system_prompt: str, user_message: str, result: _Completion
) -> AsyncIterator[str]:
    """Versión en streaming de `generate_from_prompts`. `result` se completa (modelo,
    tokens, costes, caché) solo cuando el stream termina con éxito."""
    settings = get_settings()

    def call(provider, target_model, attempt):
        selected = settings.model_copy(update={"llm_provider": provider})
        if provider == "openai":
            return _stream_openai(system_prompt, user_message, selected, target_model, None, attempt)
        return _stream_anthropic(system_prompt, user_message, selected, target_model, None, attempt)

    stream = LLMWrapper(settings).stream(
        system_prompt, user_message, settings.effective_model(), None, None, True, result, call,
    )
    async with aclosing(stream):
        async for chunk in stream:
            yield chunk


def _phase_result(phase: Phase, completion: _Completion) -> PhaseResult:
    return PhaseResult(
        phase=phase,
        model=completion.model,
        finish_reason=completion.finish_reason,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
        total_tokens=completion.input_tokens + completion.output_tokens,
        latency_ms=completion.latency_ms,
        provider=completion.provider,
        cache_hit=completion.cache_hit,
        estimated_cost_usd=completion.estimated_cost_usd,
        request_cost_usd=completion.request_cost_usd,
        usage_available=completion.usage_available,
    )


async def _complete(
    settings: Settings,
    system_prompt: str,
    user_message: str,
    model: str,
    max_tokens: int | None,
    thinking_budget: int | None = None,
    allow_fallback: bool = True,
    accept: Callable[[str], bool] | None = None,
) -> _Completion:
    async def call(provider, target_model):
        selected = settings.model_copy(update={"llm_provider": provider})
        if provider == "openai":
            return await _call_openai(system_prompt, user_message, selected, target_model, max_tokens)
        return await _call_anthropic(system_prompt, user_message, selected, target_model,
                                     max_tokens, thinking_budget)
    return await LLMWrapper(settings).complete(
        system_prompt, user_message, model, max_tokens, thinking_budget, allow_fallback, call,
        accept,
    )


# ---------------------------------------------------------------------------
# Proveedores (clientes asíncronos: nunca bloquean el event loop)
# ---------------------------------------------------------------------------


def _finish_reason(value: object) -> str:
    return value if isinstance(value, str) and value else "unknown"


def _raise_provider_http_error(provider: str, exc: Exception, errors: dict) -> None:
    """Traduce una excepción del SDK a HTTPException sin exponer su mensaje (puede
    contener datos internos) ni la API key. Solo se registra el tipo de la excepción."""
    if isinstance(exc, errors["auth"]):
        logger.error("llm_authentication_failed", provider=provider)
        raise ProviderFailure(502, "LLM authentication failed") from None
    if isinstance(exc, errors["timeout"]):
        logger.error("llm_timeout", provider=provider)
        raise ProviderFailure(504, "LLM request timed out", retryable=True) from None
    if isinstance(exc, errors["rate_limit"]):
        logger.error("llm_rate_limited", provider=provider)
        raise ProviderFailure(429, "LLM provider rate limit reached", retryable=True) from None
    if isinstance(exc, errors["invalid"]):
        logger.error("llm_request_rejected", provider=provider, error_type=type(exc).__name__)
        raise HTTPException(
            status_code=400, detail="LLM provider rejected the request (check model and options)"
        ) from None
    logger.error("llm_call_failed", provider=provider, error_type=type(exc).__name__)
    transient = isinstance(exc, (OpenAIConnectionError, AnthropicConnectionError)) or (
        isinstance(getattr(exc, "status_code", None), int) and exc.status_code >= 500
    )
    raise ProviderFailure(502, "LLM provider error", retryable=transient) from None


async def _close(resource) -> None:
    """SDK clients and streams own connections; also accepts minimal test doubles."""
    close = getattr(resource, "close", None)
    if close is not None:
        result = close()
        if inspect.isawaitable(result):
            await result


def _anthropic_options(max_tokens, thinking_budget):
    limit = max_tokens or _ANTHROPIC_DEFAULT_MAX_TOKENS
    if thinking_budget is None:
        return {"max_tokens": limit}
    return {"max_tokens": max(limit, thinking_budget + 1024),
            "thinking": {"type": "enabled", "budget_tokens": thinking_budget}}


_OPENAI_ERRORS = {
    "auth": OpenAIAuthError,
    "timeout": OpenAITimeout,
    "rate_limit": OpenAIRateLimit,
    "invalid": (OpenAIBadRequest, OpenAINotFound),
}
_ANTHROPIC_ERRORS = {
    "auth": AnthropicAuthError,
    "timeout": AnthropicTimeout,
    "rate_limit": AnthropicRateLimit,
    "invalid": (AnthropicBadRequest, AnthropicNotFound),
}


async def _call_openai(
    system_prompt: str,
    user_message: str,
    settings: Settings,
    model: str,
    max_tokens: int | None,
) -> _Completion:
    client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout,
                         max_retries=settings.llm_retries)
    kwargs: dict = {}
    if max_tokens is not None:
        kwargs["max_completion_tokens"] = max_tokens
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            **kwargs,
        )
    except Exception as exc:
        _raise_provider_http_error("OpenAI", exc, _OPENAI_ERRORS)
    finally:
        await _close(client)

    choice = response.choices[0] if response.choices else None
    text = ((choice.message.content if choice else None) or "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="LLM returned an empty response")

    usage = response.usage
    return _Completion(
        text=text,
        model=response.model,
        finish_reason=_finish_reason(choice.finish_reason),
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
    )


async def _call_anthropic(
    system_prompt: str,
    user_message: str,
    settings: Settings,
    model: str,
    max_tokens: int | None,
    thinking_budget: int | None = None,
) -> _Completion:
    client = AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=settings.llm_timeout,
                            max_retries=settings.llm_retries)
    try:
        response = await client.messages.create(
            model=model,
            **_anthropic_options(max_tokens, thinking_budget),
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:
        _raise_provider_http_error("Anthropic", exc, _ANTHROPIC_ERRORS)
    finally:
        await _close(client)

    # El contenido puede mezclar bloques (p. ej. de razonamiento): solo cuentan los de texto.
    blocks = [b.text for b in response.content or [] if isinstance(getattr(b, "text", None), str)]
    text = "".join(blocks).strip()
    if not text:
        raise HTTPException(status_code=502, detail="LLM returned an empty response")

    return _Completion(
        text=text,
        model=response.model,
        finish_reason=_finish_reason(response.stop_reason),
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )


async def _stream_openai(
    system_prompt: str,
    user_message: str,
    settings: Settings,
    model: str,
    max_tokens: int | None,
    metrics: _Completion,
) -> AsyncIterator[str]:
    client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout,
                         max_retries=settings.llm_retries)
    stream = None
    kwargs: dict = {}
    if max_tokens is not None:
        kwargs["max_completion_tokens"] = max_tokens
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            stream=True,
            stream_options={"include_usage": True},
            **kwargs,
        )
        async for chunk in stream:
            metrics.model = chunk.model or metrics.model
            if chunk.choices:
                choice = chunk.choices[0]
                reason = getattr(choice, "finish_reason", None)
                if reason:
                    metrics.finish_reason = _finish_reason(reason)
                delta = choice.delta.content
                if delta:
                    yield delta
            if chunk.usage:
                metrics.input_tokens = chunk.usage.prompt_tokens
                metrics.output_tokens = chunk.usage.completion_tokens
                metrics.usage_available = True
    except Exception as exc:
        _raise_provider_http_error("OpenAI", exc, _OPENAI_ERRORS)
    finally:
        try:
            await _close(stream)
        finally:
            await _close(client)


async def _stream_anthropic(
    system_prompt: str,
    user_message: str,
    settings: Settings,
    model: str,
    max_tokens: int | None,
    metrics: _Completion,
    thinking_budget: int | None = None,
) -> AsyncIterator[str]:
    client = AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=settings.llm_timeout,
                            max_retries=settings.llm_retries)
    try:
        async with client.messages.stream(
            model=model,
            **_anthropic_options(max_tokens, thinking_budget),
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            async for text in stream.text_stream:
                yield text
            final = await stream.get_final_message()
            metrics.model = final.model
            metrics.input_tokens = final.usage.input_tokens
            metrics.output_tokens = final.usage.output_tokens
            metrics.finish_reason = _finish_reason(final.stop_reason)
            metrics.usage_available = True
    except Exception as exc:
        _raise_provider_http_error("Anthropic", exc, _ANTHROPIC_ERRORS)
    finally:
        await _close(client)
