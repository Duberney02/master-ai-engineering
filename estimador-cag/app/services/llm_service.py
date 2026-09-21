import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from anthropic import (
    APITimeoutError as AnthropicTimeout,
    AsyncAnthropic,
    AuthenticationError as AnthropicAuthError,
    BadRequestError as AnthropicBadRequest,
    NotFoundError as AnthropicNotFound,
    RateLimitError as AnthropicRateLimit,
)
from fastapi import HTTPException
from openai import (
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

logger = logging.getLogger(__name__)

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


@dataclass
class _Completion:
    """Respuesta normalizada de un proveedor, independiente del SDK."""

    text: str
    model: str
    finish_reason: str
    input_tokens: int
    output_tokens: int
    latency_ms: int = 0


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
    if options.model is None:
        return settings.effective_model()
    allowed = settings.allowed_models_list()
    if allowed and options.model not in allowed:
        raise HTTPException(status_code=422, detail="Requested model is not allowed")
    return options.model


async def generate_estimation(
    transcription: str, options: GenerationOptions | None = None
) -> LLMEstimationResult:
    options = options or GenerationOptions()
    settings = get_settings()
    model = _resolve_model(settings, options)
    start = time.monotonic()

    logger.info(
        "Generating estimation provider=%s model=%s preprocessing=%s example_format=%s "
        "num_examples=%d use_examples=%s max_tokens=%s transcription_chars=%d",
        settings.llm_provider,
        model,
        options.preprocessing,
        options.example_format,
        options.num_examples,
        options.use_examples,
        options.max_tokens,
        len(transcription),
    )

    phases: list[PhaseResult] = []
    extracted: str | None = None

    if options.preprocessing == "two_phase":
        extraction = await _complete(
            settings, EXTRACTION_SYSTEM_PROMPT, transcription, model, EXTRACTION_MAX_TOKENS
        )
        extracted = extraction.text
        phases.append(_phase_result("preprocessing", extraction))

    system_prompt = build_system_prompt(
        example_format=options.example_format,
        num_examples=options.num_examples,
        use_examples=options.use_examples,
        inline_cleaning=options.preprocessing == "inline_cleaning",
    )
    completion = await _complete(
        settings,
        system_prompt,
        _estimation_user_message(transcription, extracted),
        model,
        options.max_tokens,
    )
    phases.append(_phase_result("estimation", completion))

    input_tokens = sum(p.input_tokens for p in phases)
    output_tokens = sum(p.output_tokens for p in phases)
    result = LLMEstimationResult(
        estimation=completion.text,
        model=completion.model,
        provider=settings.llm_provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_usd=None,
        generated_at=datetime.now(tz=timezone.utc),
        latency_ms=int((time.monotonic() - start) * 1000),
        finish_reason=completion.finish_reason,
        preprocessing=options.preprocessing,
        extracted_requirements=extracted,
        phases=phases,
    )
    logger.info(
        "Estimation complete provider=%s model=%s finish_reason=%s tokens=%d latency_ms=%d",
        result.provider,
        result.model,
        result.finish_reason,
        result.total_tokens,
        result.latency_ms,
    )
    return result


def _phase_result(phase: Phase, completion: _Completion) -> PhaseResult:
    return PhaseResult(
        phase=phase,
        model=completion.model,
        finish_reason=completion.finish_reason,
        input_tokens=completion.input_tokens,
        output_tokens=completion.output_tokens,
        total_tokens=completion.input_tokens + completion.output_tokens,
        latency_ms=completion.latency_ms,
    )


async def _complete(
    settings: Settings,
    system_prompt: str,
    user_message: str,
    model: str,
    max_tokens: int | None,
) -> _Completion:
    start = time.monotonic()
    if settings.llm_provider == "openai":
        completion = await _call_openai(system_prompt, user_message, settings, model, max_tokens)
    elif settings.llm_provider == "anthropic":
        completion = await _call_anthropic(system_prompt, user_message, settings, model, max_tokens)
    else:
        raise HTTPException(status_code=500, detail="Unsupported LLM provider")
    completion.latency_ms = int((time.monotonic() - start) * 1000)
    return completion


# ---------------------------------------------------------------------------
# Proveedores (clientes asíncronos: nunca bloquean el event loop)
# ---------------------------------------------------------------------------


def _finish_reason(value: object) -> str:
    return value if isinstance(value, str) and value else "unknown"


def _raise_provider_http_error(provider: str, exc: Exception, errors: dict) -> None:
    """Traduce una excepción del SDK a HTTPException sin exponer su mensaje (puede
    contener datos internos) ni la API key. Solo se registra el tipo de la excepción."""
    if isinstance(exc, errors["auth"]):
        logger.error("%s authentication failed", provider)
        raise HTTPException(status_code=502, detail="LLM authentication failed") from None
    if isinstance(exc, errors["timeout"]):
        logger.error("%s request timed out", provider)
        raise HTTPException(status_code=504, detail="LLM request timed out") from None
    if isinstance(exc, errors["rate_limit"]):
        logger.error("%s rate limit reached", provider)
        raise HTTPException(status_code=429, detail="LLM provider rate limit reached") from None
    if isinstance(exc, errors["invalid"]):
        logger.error("%s rejected the request: %s", provider, type(exc).__name__)
        raise HTTPException(
            status_code=400, detail="LLM provider rejected the request (check model and options)"
        ) from None
    logger.error("%s call failed: %s", provider, type(exc).__name__)
    raise HTTPException(status_code=502, detail="LLM provider error") from None


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
    client = AsyncOpenAI(api_key=settings.openai_api_key)
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
) -> _Completion:
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await client.messages.create(
            model=model,
            max_tokens=max_tokens or _ANTHROPIC_DEFAULT_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:
        _raise_provider_http_error("Anthropic", exc, _ANTHROPIC_ERRORS)

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
