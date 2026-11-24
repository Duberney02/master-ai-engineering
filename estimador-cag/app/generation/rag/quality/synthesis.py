"""Síntesis de rangos de horas (Sesión 11): hacer visible la incertidumbre cuando los precedentes se contradicen.

Un promedio de vecinos que dicen 40 h y 90 h da «65 h», una cifra que parece precisa y no lo es. Cuando la dispersión de
los vecinos (coeficiente de variación, ya calculado por `task_hours.weighted_consensus`) supera el umbral, la tarea
añade un `hours_range` con un motivo, SIN cambiar la cifra puntual.

* El rango es DETERMINISTA: mínimo y máximo de las horas vecinas (reproducible y comprobable sin LLM).
* El motivo lo redacta el LLM (una frase que nombra el conflicto); si falla, se usa un motivo de plantilla. La síntesis
  nunca rompe la estimación de horas.
"""

import structlog
from pydantic import BaseModel, Field

from app.foundation.llm.structured import Generator, generate_structured
from app.foundation.prompts.loader import render_rag_template
from app.generation.rag.schemas import HoursRange, TaskHoursEstimate

logger = structlog.get_logger(__name__)

_MAX_TOKENS = 300


class RangeReason(BaseModel):
    reason: str = Field(min_length=1, max_length=600)


def is_contradictory(estimate: TaskHoursEstimate, threshold: float) -> bool:
    """True si la tarea tiene vecinos y su dispersión supera `threshold`."""
    return estimate.has_match and len(estimate.neighbors) > 1 and (estimate.dispersion or 0.0) > threshold


def deterministic_bounds(estimate: TaskHoursEstimate) -> tuple[float, float]:
    """Mínimo y máximo de las horas de los vecinos."""
    hours = [neighbor.estimated_hours for neighbor in estimate.neighbors]
    return min(hours), max(hours)


def template_reason(estimate: TaskHoursEstimate, low: float, high: float) -> str:
    return (
        f"Los precedentes de «{estimate.task}» se contradicen: de {low:g} h a {high:g} h "
        f"(dispersión {estimate.dispersion:.2f}); la cifra puntual promedia ambos extremos."
    )


async def synthesize_range(
    estimate: TaskHoursEstimate, *, threshold: float, generate: Generator | None, model: str | None = None
) -> TaskHoursEstimate:
    """La estimación con `hours_range` si sus vecinos se contradicen; si no, la misma estimación sin tocar."""
    if not is_contradictory(estimate, threshold):
        return estimate
    low, high = deterministic_bounds(estimate)
    reason = template_reason(estimate, low, high)
    if generate is not None:
        messages = [
            {"role": "system", "content": render_rag_template("range_synthesis", "system", {})},
            {
                "role": "user",
                "content": render_rag_template(
                    "range_synthesis",
                    "user",
                    {
                        "task": estimate.task,
                        "module": estimate.module,
                        "hours": [f"{neighbor.estimated_hours:g}" for neighbor in estimate.neighbors],
                        "low": f"{low:g}",
                        "high": f"{high:g}",
                    },
                ),
            },
        ]
        options: dict = {"max_tokens": _MAX_TOKENS}
        if model:
            options["model"] = model
        try:
            result, _ = await generate_structured(generate, messages, RangeReason, **options)
            reason = result.reason.strip()
        except Exception as exc:
            logger.warning("range_synthesis_llm_failed", error_type=type(exc).__name__)
    return estimate.model_copy(update={"hours_range": HoursRange(low=low, high=high, reason=reason)})
