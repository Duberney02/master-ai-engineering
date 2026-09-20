import logging

from fastapi import APIRouter

from app.schemas.estimation import (
    EstimationRequest,
    EstimationResponse,
    PhaseUsage,
    UsageInfo,
)
from app.services.evaluation import evaluate_estimation
from app.services.llm_service import (
    GenerationOptions,
    LLMEstimationResult,
    generate_estimation,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/estimate", response_model=EstimationResponse)
async def estimate(request: EstimationRequest) -> EstimationResponse:
    logger.debug(
        "Received estimation request transcription_chars=%d preprocessing=%s",
        len(request.transcription),
        request.preprocessing,
    )
    options = GenerationOptions(
        preprocessing=request.preprocessing,
        example_format=request.example_format,
        num_examples=request.num_examples,
        use_examples=request.use_examples,
        model=request.model,
        max_tokens=request.max_tokens,
    )
    result: LLMEstimationResult = await generate_estimation(request.transcription, options)

    evaluation = None
    if request.evaluate:
        preprocessing_phase = next((p for p in result.phases if p.phase == "preprocessing"), None)
        evaluation = evaluate_estimation(
            result.estimation,
            result.finish_reason,
            preprocessing_finish_reason=(
                preprocessing_phase.finish_reason if preprocessing_phase else None
            ),
        )

    return EstimationResponse(
        estimation=result.estimation,
        model=result.model,
        provider=result.provider,
        finish_reason=result.finish_reason,
        usage=UsageInfo(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
            phases=[PhaseUsage(**vars(p)) for p in result.phases],
        ),
        estimated_cost_usd=result.estimated_cost_usd,
        latency_ms=result.latency_ms,
        generated_at=result.generated_at,
        preprocessing=result.preprocessing,
        extracted_requirements=result.extracted_requirements,
        evaluation=evaluation,
    )
