"""`POST /api/v1/estimate[/stream]`: estimación a partir de una solicitud estructurada.

El prompt se renderiza desde plantillas versionadas (`app/prompts`) y se envía
al modelo como dos mensajes separados, system y user.
"""

import json
from contextlib import aclosing

import structlog
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.prompts.loader import (
    DEFAULT_PROMPT_VERSION,
    UnknownPromptVersionError,
    available_versions,
    render_estimation_prompt,
)
from app.schemas import (
    EstimationRequest,
    EstimationResponse,
    EstimationStreamMetadata,
    StreamUsage,
)
from app.services.llm_service import generate_from_prompts, generate_from_prompts_stream
from app.services.llm_wrapper import Completion

logger = structlog.get_logger(__name__)

router = APIRouter()

PromptVersionQuery = Query(
    DEFAULT_PROMPT_VERSION,
    max_length=10,
    description="Versión de las plantillas de prompt (directorio app/prompts/estimation/<versión>).",
)


def _render(request: EstimationRequest, prompt_version: str) -> tuple[str, str]:
    try:
        return render_estimation_prompt(request, version=prompt_version)
    except UnknownPromptVersionError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown prompt_version. Available: {', '.join(available_versions())}",
        ) from None


def _log_completed(prompt_version: str, completion: Completion, streamed: bool) -> None:
    logger.info(
        "structured_estimation_completed",
        prompt_version=prompt_version,
        provider=completion.provider,
        model=completion.model,
        cache_hit=completion.cache_hit,
        streamed=streamed,
    )


@router.post("/estimate", response_model=EstimationResponse)
async def estimate(
    request: EstimationRequest, prompt_version: str = PromptVersionQuery
) -> EstimationResponse:
    system, user = _render(request, prompt_version)
    completion = await generate_from_prompts(system, user)
    _log_completed(prompt_version, completion, streamed=False)
    return EstimationResponse(text=completion.text, prompt_version=prompt_version)


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/estimate/stream", response_class=StreamingResponse)
async def estimate_stream(
    request: EstimationRequest, prompt_version: str = PromptVersionQuery
) -> StreamingResponse:
    # Se renderiza antes de abrir el stream: una versión inválida es un 422, no un evento.
    system, user = _render(request, prompt_version)

    async def events():
        result = Completion(usage_available=False)
        try:
            async with aclosing(generate_from_prompts_stream(system, user, result)) as stream:
                async for chunk in stream:
                    yield _event("token", {"text": chunk})
            _log_completed(prompt_version, result, streamed=True)
            metadata = EstimationStreamMetadata(
                prompt_version=prompt_version,
                model=result.model,
                provider=result.provider,
                finish_reason=result.finish_reason,
                usage=StreamUsage(
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    total_tokens=result.input_tokens + result.output_tokens,
                ),
                latency_ms=result.latency_ms,
                cache_hit=result.cache_hit,
                estimated_cost_usd=result.estimated_cost_usd,
                request_cost_usd=result.request_cost_usd,
            )
            yield _event("metadata", metadata.model_dump(mode="json"))
            yield _event("done", {"status": "complete"})
        except HTTPException as exc:
            # Los detalles provienen del mapeo saneado de errores del proveedor.
            yield _event("error", {"status_code": exc.status_code, "message": exc.detail})
        except Exception as exc:
            logger.error("structured_stream_failed", error_type=type(exc).__name__)
            yield _event("error", {"status_code": 502, "message": "Estimation stream failed"})

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })
