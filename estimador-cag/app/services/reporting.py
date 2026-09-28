"""Construcción de metadatos (tokens, costes, caché) con semántica explícita.

- **Generación original** (`usage.*_tokens`, `cost.original_generation_usd`): lo que
  costó producir el resultado desde cero, aunque hoy se haya servido desde caché.
- **Incurrido** (`usage.incurred_*`, `cost.incurred_usd`, `estimated_cost_usd`): lo que
  consumió ESTA solicitud. Una fase reutilizada (hit/shared) cuenta 0.
- **Ahorro** (`cost.saved_usd`): coste original de las fases reutilizadas.
- Cualquier agregado que dependa de un valor desconocido es `null`, nunca 0.
"""

from collections.abc import Iterable

from app.llm.types import LLMResult
from app.schemas.estimation import (
    CacheInfo,
    CostInfo,
    EstimationMetadata,
    EstimationResponse,
    PhaseCost,
    PhaseUsage,
    UsageInfo,
)
from app.services.estimation_service import EstimationResult


def _sum(values: Iterable[int | float | None]) -> int | float | None:
    total = 0
    for value in values:
        if value is None:
            return None
        total += value
    return total


def _money(value: float | None) -> float | None:
    return None if value is None else round(value, 8)


def phase_usage(phase: str, llm: LLMResult) -> PhaseUsage:
    return PhaseUsage(
        phase=phase,
        provider=llm.provider,
        model=llm.model,
        requested_model=llm.requested_model,
        finish_reason=llm.finish_reason,
        input_tokens=llm.input_tokens,
        output_tokens=llm.output_tokens,
        total_tokens=llm.total_tokens,
        latency_ms=llm.latency_ms,
        original_latency_ms=llm.original_latency_ms,
        cache=llm.cache_status,
        generated_at=llm.generated_at,
        fallback_used=llm.fallback_used,
        attempts=llm.attempts,
        cost=PhaseCost(
            original_generation_usd=_money(llm.original_cost_usd),
            incurred_usd=_money(llm.incurred_cost_usd),
        ),
    )


def cache_summary(statuses: list[str]) -> str:
    reused = [s in ("hit", "shared") for s in statuses]
    if statuses and all(reused):
        return "hit"
    if any(reused):
        return "partial"
    if statuses and all(s == "disabled" for s in statuses):
        return "disabled"
    if any(s == "error" for s in statuses):
        return "error"
    return "miss"


def build_metadata(
    result: EstimationResult, *, pricing_source: str, request_id: str | None = None
) -> EstimationMetadata:
    llms = [p.llm for p in result.phases]
    fresh = [llm for llm in llms if not llm.reused]
    reused = [llm for llm in llms if llm.reused]
    estimation = result.estimation_phase

    usage = UsageInfo(
        input_tokens=_sum(llm.input_tokens for llm in llms),
        output_tokens=_sum(llm.output_tokens for llm in llms),
        total_tokens=_sum(llm.total_tokens for llm in llms),
        incurred_input_tokens=_sum(llm.input_tokens for llm in fresh),
        incurred_output_tokens=_sum(llm.output_tokens for llm in fresh),
        incurred_total_tokens=_sum(llm.total_tokens for llm in fresh),
        phases=[phase_usage(p.phase, p.llm) for p in result.phases],
    )
    incurred = _money(_sum(llm.incurred_cost_usd for llm in llms))
    cost = CostInfo(
        pricing_source=pricing_source,
        original_generation_usd=_money(_sum(llm.original_cost_usd for llm in llms)),
        incurred_usd=incurred,
        saved_usd=_money(_sum(llm.original_cost_usd for llm in reused)),
    )
    return EstimationMetadata(
        request_id=request_id,
        model=estimation.model,
        provider=estimation.provider,
        finish_reason=estimation.finish_reason,
        usage=usage,
        estimated_cost_usd=incurred,
        cost=cost,
        cache=CacheInfo(
            status=cache_summary([llm.cache_status for llm in llms]),
            phases={p.phase: p.llm.cache_status for p in result.phases},
        ),
        fallback_used=any(llm.fallback_used for llm in llms),
        latency_ms=result.latency_ms,
        generated_at=result.generated_at,
        preprocessing=result.preprocessing,
        extracted_requirements=result.extracted_requirements,
        evaluation=result.evaluation,
    )


def build_response(
    result: EstimationResult, *, pricing_source: str, request_id: str | None = None
) -> EstimationResponse:
    metadata = build_metadata(result, pricing_source=pricing_source, request_id=request_id)
    return EstimationResponse(estimation=result.estimation, **metadata.model_dump())
