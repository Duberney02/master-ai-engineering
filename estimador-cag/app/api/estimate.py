"""`POST /v1/estimate/from-transcript`: transcripción → estimación fundamentada con citas (Sesión 9).

Es el endpoint más estricto del servicio —límite de 10/min e idempotencia— porque cada llamada puede encadenar
varias llamadas al LLM. Transporte fino: validación en `EstimateRequest` (422), clave en `require_estimate_key` (401),
límite en el decorador (429). Cualquier fallo del pipeline es un 502 genérico; la cabecera `X-Request-ID` permite
localizar el detalle en el log.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.rate_limiting import ESTIMATE_LIMIT, limiter
from app.api.security import require_estimate_key
from app.dependencies import get_grounded_estimator
from app.generation.rag.estimator import GroundedEstimator
from app.generation.rag.schemas import Estimate, EstimateRequest

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/estimate", tags=["estimate"], dependencies=[Depends(require_estimate_key)])


@router.post(
    "/from-transcript",
    response_model=Estimate,
    responses={
        401: {"description": "Clave de API ausente o no válida."},
        429: {"description": "Límite de peticiones superado (`Retry-After`)."},
        502: {"description": "Fallo del pipeline (mensaje genérico; `X-Request-ID` localiza el detalle en el log)."},
    },
)
@limiter.limit(ESTIMATE_LIMIT)
async def from_transcript(
    request: Request, payload: EstimateRequest, estimator: GroundedEstimator = Depends(get_grounded_estimator)
) -> Estimate:
    """Estimación fundamentada desde una transcripción cruda (idempotente con `idempotency_key`)."""
    try:
        return await estimator.estimate_from_transcript(payload.transcript, idempotency_key=payload.idempotency_key)
    except Exception as exc:
        logger.error("rag_estimate_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=502, detail="No se pudo generar la estimación.") from exc
