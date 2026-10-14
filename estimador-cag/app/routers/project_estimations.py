"""`POST /api/v1/estimate[/stream]`: estimación estructurada a partir de una solicitud tipada.

El router solo traduce HTTP: la orquestación (guardrails, cachés, generación y validación)
vive en `EstimationPipeline`, inyectado con `Depends`.
"""

import json
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.prompts.loader import DEFAULT_PROMPT_VERSION
from app.schemas import (
    EstimationRequest,
    EstimationResponse,
    EstimationStreamMetadata,
)
from app.services.history import EstimationHistory, get_history
from app.services.pipeline import EstimationPipeline, PipelineOutcome, get_pipeline

logger = structlog.get_logger(__name__)

router = APIRouter()

PromptVersionQuery = Query(
    DEFAULT_PROMPT_VERSION,
    max_length=10,
    description="Versión de las plantillas de prompt (directorio app/prompts/estimation/<versión>).",
)


def _log_completed(outcome: PipelineOutcome, streamed: bool) -> None:
    logger.info(
        "structured_estimation_completed",
        prompt_version=outcome.prompt_version,
        provider=outcome.provider,
        model=outcome.model,
        cached=outcome.cached,
        attempts=outcome.attempts,
        out_of_scope=outcome.result.out_of_scope,
        streamed=streamed,
    )


@router.post(
    "/estimate",
    response_model=EstimationResponse,
    responses={400: {"description": "Entrada rechazada por los guardrails: `{reason, message}`."}},
)
async def estimate(
    request: EstimationRequest,
    prompt_version: str = PromptVersionQuery,
    pipeline: EstimationPipeline = Depends(get_pipeline),
    history: EstimationHistory = Depends(get_history),
) -> EstimationResponse:
    requested_at = datetime.now(timezone.utc)
    outcome = await pipeline.run(request, prompt_version)
    estimation_id = await history.save(request, outcome, requested_at)
    _log_completed(outcome, streamed=False)
    return EstimationResponse(
        result=outcome.result,
        prompt_version=outcome.prompt_version,
        cached=outcome.cached,
        cache_source=outcome.cache_source,
        estimation_id=estimation_id,
        metrics=outcome.metrics(),
    )


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _metadata(outcome: PipelineOutcome, estimation_id: int | None) -> EstimationStreamMetadata:
    return EstimationStreamMetadata(
        **outcome.metrics().model_dump(),
        prompt_version=outcome.prompt_version,
        cache_source=outcome.cache_source,
        estimation_id=estimation_id,
    )


@router.post(
    "/estimate/stream",
    response_class=StreamingResponse,
    responses={400: {"description": "Entrada rechazada por los guardrails: `{reason, message}`."}},
)
async def estimate_stream(
    request: EstimationRequest,
    prompt_version: str = PromptVersionQuery,
    pipeline: EstimationPipeline = Depends(get_pipeline),
    history: EstimationHistory = Depends(get_history),
) -> StreamingResponse:
    # Versión y guardrails antes de abrir el stream: son un 422/400, no un evento.
    await pipeline.check_input(request, prompt_version)

    async def events():
        try:
            requested_at = datetime.now(timezone.utc)
            outcome = await pipeline.run(request, prompt_version, input_checked=True)
            estimation_id = await history.save(request, outcome, requested_at)
            _log_completed(outcome, streamed=True)
            yield _event("result", outcome.result.model_dump(mode="json"))
            yield _event("metadata", _metadata(outcome, estimation_id).model_dump(mode="json"))
            yield _event("done", {"status": "complete"})
        except HTTPException as exc:
            # Los detalles provienen del mapeo saneado de errores del proveedor.
            yield _event("error", {"status_code": exc.status_code, "message": exc.detail})
        except Exception as exc:
            logger.error("structured_stream_failed", error_type=type(exc).__name__)
            yield _event("error", {"status_code": 502, "message": "Estimation stream failed"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
