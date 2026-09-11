import logging
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.llm_service import LLMEstimationResult, generate_estimation

logger = logging.getLogger(__name__)

router = APIRouter()


class EstimationRequest(BaseModel):
    transcription: str = Field(
        min_length=20,
        max_length=50_000,
        description="Transcripción de la reunión con el cliente.",
    )


class UsageInfo(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class EstimationResponse(BaseModel):
    estimation: str
    model: str
    provider: str
    usage: UsageInfo
    estimated_cost_usd: float | None
    latency_ms: int
    generated_at: datetime


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
