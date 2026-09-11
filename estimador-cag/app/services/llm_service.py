import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from anthropic import (
    AsyncAnthropic,
    APITimeoutError as AnthropicTimeout,
    AuthenticationError as AnthropicAuthError,
)
from fastapi import HTTPException
from openai import (
    AsyncOpenAI,
    APITimeoutError as OpenAITimeout,
    AuthenticationError as OpenAIAuthError,
)

from app.config import Settings, get_settings
from app.context.examples import ESTIMATION_EXAMPLES

logger = logging.getLogger(__name__)

_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"


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


def build_system_prompt() -> str:
    """Build the full system prompt including role, rules, format spec, and all examples."""
    return f"""\
You are a Senior Software Estimation Architect with extensive experience estimating \
software projects across industries and scales.

## Your Responsibility

Analyze the transcript of a client meeting and produce an initial software development \
estimate grounded in the identified requirements, the historical examples provided below, \
explicit assumptions, and technical uncertainty.

## Mandatory Rules

1. **Do not invent requirements** as if they were confirmed. When information is missing, \
declare it explicitly as an assumption.
2. **Always distinguish** between explicit requirements (mentioned in the meeting) and \
assumptions (inferred by you to complete the estimate).
3. **Avoid false precision**: present hour ranges when uncertainty is high.
4. **Include tasks that are commonly forgotten**: testing, QA, technical documentation, \
environment setup, deployment, observability, and basic project management.
5. **Identify risks** and uncertainties that could affect scope or timeline.
6. **Use historical examples as calibration references**, do not copy them mechanically.
7. **Estimates are indicative**, not contractual commitments.

## Expected Output Format (strict Markdown, output in Spanish)

```
## Estimación: [nombre inferido del proyecto]

### Resumen del alcance
[2-3 oraciones describiendo qué se construirá]

### Requisitos identificados
[Lista de requisitos explícitamente mencionados en la reunión]

### Supuestos
[Lista de supuestos que hiciste para completar la estimación]

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

## Historical Reference Examples

The following projects were previously estimated. Use them to calibrate relative \
complexity, typical hours per area, and deliverable structure. \
Do not copy them; use them as a calibration anchor.

{_format_examples()}
"""


def _format_examples() -> str:
    parts: list[str] = []
    for i, ex in enumerate(ESTIMATION_EXAMPLES, start=1):
        parts.append(
            f"### Historical Example {i}\n\n"
            f"**Meeting Summary:**\n{ex['meeting_summary']}\n\n"
            f"**Generated Estimation:**\n{ex['estimation']}\n"
        )
    return "\n---\n\n".join(parts)


async def generate_estimation(transcription: str) -> LLMEstimationResult:
    settings = get_settings()
    system_prompt = build_system_prompt()
    start = time.monotonic()

    logger.info(
        "Generating estimation provider=%s model=%s transcription_chars=%d",
        settings.llm_provider,
        settings.effective_model(),
        len(transcription),
    )

    if settings.llm_provider == "openai":
        result = await _call_openai(system_prompt, transcription, settings)
    elif settings.llm_provider == "anthropic":
        result = await _call_anthropic(system_prompt, transcription, settings)
    else:
        raise HTTPException(status_code=500, detail="Unsupported LLM provider")

    result.latency_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "Estimation complete provider=%s model=%s tokens=%d latency_ms=%d",
        result.provider,
        result.model,
        result.total_tokens,
        result.latency_ms,
    )
    return result


async def _call_openai(
    system_prompt: str, transcription: str, settings: Settings
) -> LLMEstimationResult:
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        response = await client.chat.completions.create(
            model=settings.effective_model(),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcription},
            ],
            temperature=0.3,
        )
    except OpenAIAuthError:
        logger.error("OpenAI authentication failed")
        raise HTTPException(status_code=502, detail="LLM authentication failed")
    except OpenAITimeout:
        logger.error("OpenAI request timed out")
        raise HTTPException(status_code=504, detail="LLM request timed out")
    except Exception as exc:
        logger.error("OpenAI call failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="LLM provider error")

    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="LLM returned an empty response")

    usage = response.usage
    return LLMEstimationResult(
        estimation=text,
        model=response.model,
        provider="openai",
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        estimated_cost_usd=None,
        generated_at=datetime.now(tz=timezone.utc),
        latency_ms=0,
    )


async def _call_anthropic(
    system_prompt: str, transcription: str, settings: Settings
) -> LLMEstimationResult:
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await client.messages.create(
            model=settings.effective_model(),
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": transcription}],
        )
    except AnthropicAuthError:
        logger.error("Anthropic authentication failed")
        raise HTTPException(status_code=502, detail="LLM authentication failed")
    except AnthropicTimeout:
        logger.error("Anthropic request timed out")
        raise HTTPException(status_code=504, detail="LLM request timed out")
    except Exception as exc:
        logger.error("Anthropic call failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="LLM provider error")

    text = (response.content[0].text if response.content else "").strip()
    if not text:
        raise HTTPException(status_code=502, detail="LLM returned an empty response")

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    return LLMEstimationResult(
        estimation=text,
        model=response.model,
        provider="anthropic",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_usd=None,
        generated_at=datetime.now(tz=timezone.utc),
        latency_ms=0,
    )
