"""`POST /v1/estimate/stages/*`: el pipeline RAG, una etapa cada vez (Sesión 9).

El pipeline completo oculta sus artefactos intermedios (brief, chunks, bloque de contexto). Este router expone cada
etapa como un endpoint independiente y SIN ESTADO: el cliente pasa la salida de una etapa como entrada de la
siguiente. Cada endpoint reutiliza los métodos del orquestador (`GroundedEstimator`); no reimplementa lógica.

`generate` no replica los reintentos correctivos del pipeline completo: devuelve las señales de fundamentación (ids
inventados y coherencia) para que la interfaz las muestre. Mismo esquema de errores que los routers hermanos: 401,
422, 429 y 502 genérico; cada etapa registra su nombre y duración con el `X-Request-ID`.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.rate_limiting import STAGES_LIMIT, limiter
from app.api.retrieval import RETRIEVAL_RESPONSES, run_retrieval
from app.api.security import require_estimate_key
from app.dependencies import get_grounded_estimator
from app.generation.rag.estimator import GroundedEstimator
from app.generation.rag.observability import log_stage
from app.generation.rag.schemas import (
    AssembleRequest,
    AssembleResult,
    GenerateRequest,
    GenerateResult,
    ReformulateRequest,
    ReformulationResult,
    RetrievalRequest,
    RetrievalResult,
    StructureRequest,
    StructureResult,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/v1/estimate/stages", tags=["estimate-stages"], dependencies=[Depends(require_estimate_key)]
)

_PIPELINE_ERRORS = {
    401: {"description": "Clave de API ausente o no válida."},
    429: {"description": "Límite de peticiones superado (`Retry-After`)."},
    502: {"description": "Fallo de la etapa (mensaje genérico; detalle en el log)."},
}


@router.post("/reformulate", response_model=ReformulationResult, responses=_PIPELINE_ERRORS)
@limiter.limit(STAGES_LIMIT)
async def reformulate(
    request: Request, payload: ReformulateRequest, estimator: GroundedEstimator = Depends(get_grounded_estimator)
) -> ReformulationResult:
    """Etapa 1: transcripción → brief estructurado (`query`) + texto de búsqueda (`search_text`)."""
    try:
        with log_stage("reformulation", transcription_chars=len(payload.transcript)):
            return await estimator.reformulate(payload.transcript)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudo reformular la transcripción.") from exc


@router.post("/retrieve", response_model=RetrievalResult, responses=RETRIEVAL_RESPONSES)
@limiter.limit(STAGES_LIMIT)
async def retrieve(
    request: Request, payload: RetrievalRequest, estimator: GroundedEstimator = Depends(get_grounded_estimator)
) -> RetrievalResult:
    """Etapa 2: mismo contrato que `/v1/retrieval/search` (el `search_text` va en `query_text`)."""
    with log_stage("retrieval", sector_filtered=bool(payload.sectors)):
        return await run_retrieval(estimator, payload)


@router.post("/assemble", response_model=AssembleResult, responses=_PIPELINE_ERRORS)
@limiter.limit(STAGES_LIMIT)
async def assemble(
    request: Request, payload: AssembleRequest, estimator: GroundedEstimator = Depends(get_grounded_estimator)
) -> AssembleResult:
    """Etapa 3: truncado al presupuesto de tokens (chunks completos) y bloque `<source>`."""
    try:
        with log_stage("augmentation", chunks_count=len(payload.chunks)):
            return estimator.assemble(payload.chunks, payload.max_context_tokens)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudo ensamblar el contexto.") from exc


@router.post("/generate", response_model=GenerateResult, responses=_PIPELINE_ERRORS)
@limiter.limit(STAGES_LIMIT)
async def generate(
    request: Request, payload: GenerateRequest, estimator: GroundedEstimator = Depends(get_grounded_estimator)
) -> GenerateResult:
    """Etapa 4: estimación + ids inventados + regla de coherencia, sin reintentos automáticos."""
    try:
        with log_stage("generation", chunks_count=len(payload.kept_chunks)):
            estimate = await estimator.generate(payload.context_block, payload.query)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudo generar la estimación.") from exc
    fabricated, coherent = estimator.review(estimate, payload.kept_chunks)
    return GenerateResult(estimate=estimate, fabricated_source_ids=fabricated, coherent=coherent)


@router.post("/structure", response_model=StructureResult, responses=_PIPELINE_ERRORS)
@limiter.limit(STAGES_LIMIT)
async def structure(
    request: Request, payload: StructureRequest, estimator: GroundedEstimator = Depends(get_grounded_estimator)
) -> StructureResult:
    """Sesión 10: módulos y tareas del brief reformulado, SIN horas (`engineer_days` nulo en todas las tareas).

    Es una descomposición libre del brief, sin recuperación ni citas; las horas se piden después a
    `POST /v1/estimate/tasks/hours`.
    """
    try:
        with log_stage("structure", modules_hint=len(payload.query.technologies)):
            return await estimator.structure(payload.query)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudo generar la estructura.") from exc
