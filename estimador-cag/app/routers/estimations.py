"""Transporte HTTP/SSE: validación de entrada, traducción de errores y serialización.

La lógica de negocio vive en `EstimationService`; este módulo no construye prompts
ni llama a proveedores.
"""

import asyncio
import logging
import re
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

from app.context.examples import MAX_EXAMPLES, ExampleFormat, select_examples
from app.dependencies import AppResources, get_request_id, get_resources
from app.llm.errors import LLMError, ModelSelectionError
from app.llm.routing import ModelRoute
from app.schemas.estimation import (
    DEFAULT_NUM_EXAMPLES,
    MAX_OUTPUT_TOKENS,
    MAX_TRANSCRIPTION_CHARS,
    MIN_TRANSCRIPTION_CHARS,
    ContextResponse,
    EstimationRequest,
    EstimationResponse,
    ExampleSummary,
    PreprocessingMode,
    PublicModelConfig,
    StreamEstimationRequest,
)
from app.services.estimation_service import (
    ContentDelta,
    EstimationCompleted,
    EstimationService,
    ExtractionCompleted,
    GenerationOptions,
)
from app.services.prompts import EXTRACTION_SYSTEM_PROMPT
from app.services.reporting import build_metadata, build_response
from app.transport.errors import public_error
from app.transport.sse import SSE_HEADERS, format_sse, with_heartbeat

logger = logging.getLogger(__name__)

router = APIRouter()

_SAFE_FIELD = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _options(body: EstimationRequest) -> GenerationOptions:
    return GenerationOptions(
        preprocessing=body.preprocessing,
        example_format=body.example_format,
        num_examples=body.num_examples,
        use_examples=body.use_examples,
        model=body.model,
        max_tokens=body.max_tokens,
        allow_fallback=body.allow_fallback,
        evaluate=body.evaluate,
    )


def _http_error(exc: Exception) -> HTTPException:
    err = public_error(exc)
    logger.error(
        "estimation_failed",
        extra={"error_type": type(exc).__name__, "code": err.code, "status": err.status},
    )
    return HTTPException(status_code=err.status, detail=err.message)


@router.post("/estimate", response_model=EstimationResponse)
async def estimate(
    body: EstimationRequest,
    response: Response,
    resources: AppResources = Depends(get_resources),
    request_id: str | None = Depends(get_request_id),
) -> EstimationResponse:
    ignored = body.ignored_fields()
    if ignored:
        safe = [f for f in ignored if _SAFE_FIELD.match(f)][:20]
        logger.warning("request_fields_ignored", extra={"fields": safe, "count": len(ignored)})
        response.headers["X-Ignored-Fields"] = ",".join(safe) or "unprintable"
    try:
        result = await resources.service.generate(body.transcription, _options(body))
    except (LLMError, ModelSelectionError) as exc:
        raise _http_error(exc) from None
    return build_response(
        result, pricing_source=resources.llm.pricing.source, request_id=request_id
    )


@router.post(
    "/estimate/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": (
                "Stream SSE: `start`, [`extraction`], `delta`*, `metadata`, `done` | `error`. "
                "Ver README («Contrato SSE»)."
            ),
            "content": {"text/event-stream": {}},
        },
        422: {"description": "Solicitud inválida (se valida antes de abrir el stream)."},
    },
)
async def estimate_stream(
    body: StreamEstimationRequest,
    resources: AppResources = Depends(get_resources),
    request_id: str | None = Depends(get_request_id),
) -> StreamingResponse:
    options = _options(body)
    try:
        route = resources.service.resolve_route(options)  # 422 antes de abrir el stream
    except ModelSelectionError as exc:
        raise _http_error(exc) from None
    events = _sse_events(
        resources.service,
        body.transcription,
        options,
        route,
        pricing_source=resources.llm.pricing.source,
        request_id=request_id,
    )
    return StreamingResponse(
        with_heartbeat(events, resources.settings.sse_heartbeat_seconds),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


async def _sse_events(
    service: EstimationService,
    transcription: str,
    options: GenerationOptions,
    route: ModelRoute,
    *,
    pricing_source: str,
    request_id: str | None,
) -> AsyncIterator[str]:
    emitted_content = False
    completed = False
    yield format_sse(
        "start",
        {"request_id": request_id, "preprocessing": options.preprocessing, "route": route.describe()},
    )
    stream = service.stream(transcription, options, route)
    try:
        async for event in stream:
            if isinstance(event, ExtractionCompleted):
                yield format_sse(
                    "extraction",
                    {"phase": "preprocessing", "text": event.text, "cache": event.phase.llm.cache_status},
                )
            elif isinstance(event, ContentDelta):
                emitted_content = True
                yield format_sse("delta", {"text": event.text})
            elif isinstance(event, EstimationCompleted):
                metadata = build_metadata(
                    event.result, pricing_source=pricing_source, request_id=request_id
                )
                yield format_sse("metadata", metadata.model_dump(mode="json"))
                completed = True
                yield format_sse("done", {"status": "completed"})
                logger.info("stream_completed", extra={"cache": metadata.cache.status})
    except (asyncio.CancelledError, GeneratorExit):
        if not completed:
            logger.warning(
                "stream_interrupted",
                extra={"reason": "client_disconnected", "emitted_content": emitted_content},
            )
        raise
    except Exception as exc:  # noqa: BLE001 - todo error tras abrir el stream va por SSE
        err = public_error(exc)
        logger.error(
            "stream_failed",
            extra={"error_type": type(exc).__name__, "code": err.code,
                   "emitted_content": emitted_content},
        )
        yield format_sse(
            "error",
            {
                "code": err.code,
                "message": err.message,
                "status": err.status,
                "retryable": err.retryable,
                "partial": emitted_content,
            },
        )
    finally:
        await stream.aclose()


@router.get("/context", response_model=ContextResponse)
async def context(
    preprocessing: PreprocessingMode = "none",
    example_format: ExampleFormat = "markdown",
    num_examples: int = Query(DEFAULT_NUM_EXAMPLES, ge=0, le=MAX_EXAMPLES),
    use_examples: bool = True,
    resources: AppResources = Depends(get_resources),
) -> ContextResponse:
    """Prompt activo para las opciones dadas, ejemplos y configuración pública (sin claves)."""
    options = GenerationOptions(
        preprocessing=preprocessing,
        example_format=example_format,
        num_examples=num_examples,
        use_examples=use_examples,
    )
    policy = resources.service.policy
    examples = select_examples(num_examples) if use_examples else []
    return ContextResponse(
        system_prompt=resources.service.system_prompt(options),
        extraction_prompt=EXTRACTION_SYSTEM_PROMPT if preprocessing == "two_phase" else None,
        examples=[
            ExampleSummary(title=e.title, meeting_summary=e.meeting_summary, total_hours=e.total_hours)
            for e in examples
        ],
        models=PublicModelConfig(
            primary=str(policy.primary),
            fallback=str(policy.fallback) if policy.fallback else None,
            allowed_models=sorted(str(m) for m in policy.allowed),
            explicit_model_policy=(
                "Con `model` se usa exactamente ese modelo; `allow_fallback=true` permite "
                "pasar al modelo secundario ante errores recuperables."
            ),
        ),
        cache_enabled=resources.cache.enabled,
        limits={
            "transcription_min_chars": MIN_TRANSCRIPTION_CHARS,
            "transcription_max_chars": MAX_TRANSCRIPTION_CHARS,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "max_examples": MAX_EXAMPLES,
            "default_num_examples": DEFAULT_NUM_EXAMPLES,
        },
        options={
            "preprocessing": ["none", "inline_cleaning", "two_phase"],
            "example_format": ["markdown", "json", "narrative"],
        },
    )
