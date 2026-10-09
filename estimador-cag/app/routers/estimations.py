import json
from contextlib import aclosing

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

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
    StreamMetrics,
    generate_estimation,
    generate_estimation_stream,
    validate_options,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


def _options(request: EstimationRequest) -> GenerationOptions:
    return GenerationOptions(**request.model_dump(exclude={"transcription", "evaluate"}))


@router.post("/estimate", response_model=EstimationResponse)
async def estimate(request: EstimationRequest) -> EstimationResponse:
    logger.debug(
        "estimation_requested",
        transcription_chars=len(request.transcription),
        preprocessing=request.preprocessing,
    )
    options = _options(request)
    result: LLMEstimationResult = await generate_estimation(request.transcription, options)
    return _response(result, request)


def _response(result: LLMEstimationResult, request: EstimationRequest) -> EstimationResponse:

    evaluation = None
    if request.evaluate:
        preprocessing_phase = next((p for p in result.phases if p.phase == "preprocessing"), None)
        evaluation = evaluate_estimation(
            result.estimation,
            result.finish_reason,
            preprocessing_finish_reason=(preprocessing_phase.finish_reason if preprocessing_phase else None),
            project_rates=(
                {"Desarrollo": request.developer_rate_eur, "Diseño": request.designer_rate_eur}
                if request.include_project_costs
                else None
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
        request_cost_usd=result.request_cost_usd,
        cache_hit=result.cache_hit,
        latency_ms=result.latency_ms,
        generated_at=result.generated_at,
        preprocessing=result.preprocessing,
        extracted_requirements=result.extracted_requirements,
        evaluation=evaluation,
    )


def _event(name: str, data) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/estimate/stream", response_class=StreamingResponse)
async def estimate_stream(request: EstimationRequest) -> StreamingResponse:
    options = _options(request)
    validate_options(options)

    async def events():
        metrics = StreamMetrics()
        try:
            async with aclosing(generate_estimation_stream(request.transcription, metrics, options)) as stream:
                async for chunk in stream:
                    yield _event("token", {"text": chunk})
            if metrics.result is None:
                raise RuntimeError("Missing completed result")
            metadata = _response(metrics.result, request).model_dump(mode="json", exclude={"estimation"})
            yield _event("metadata", metadata)
            yield _event("done", {"status": "complete"})
        except HTTPException as exc:
            # Details originate in our sanitized provider/validation mapping.
            yield _event("error", {"status_code": exc.status_code, "message": exc.detail})
        except Exception as exc:
            logger.error("stream_failed", error_type=type(exc).__name__)
            yield _event("error", {"status_code": 502, "message": "Estimation stream failed"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
