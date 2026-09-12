import logging

from fastapi import APIRouter

from app.schemas.estimation import EstimationRequest, EstimationResponse, UsageInfo
from app.services.llm_service import LLMEstimationResult, generate_estimation

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/estimate", response_model=EstimationResponse)
async def estimate(request: EstimationRequest) -> EstimationResponse:
    logger.debug(
        "Received estimation request transcription_chars=%d", len(request.transcription)
    )
    result: LLMEstimationResult = await generate_estimation(request.transcription)
    return EstimationResponse(
        estimation=result.estimation,
        model=result.model,
        provider=result.provider,
        usage=UsageInfo(
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
        ),
        estimated_cost_usd=result.estimated_cost_usd,
        latency_ms=result.latency_ms,
        generated_at=result.generated_at,
    )
