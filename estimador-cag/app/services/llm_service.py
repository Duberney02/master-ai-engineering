import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException

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
