"""`POST /v1/retrieval/search`: recuperación semántica con umbral y filtros por metadatos (Sesión 9).

Endpoint canónico de búsqueda. `POST /search` (Sesión 8, sin filtros ni umbral) se mantiene por compatibilidad
(Chunking Lab, demos). Transporte fino: validación en `RetrievalRequest` (422), clave en `require_retrieval_key`
(401), límite en el decorador (429). El *soft-fail* (nada supera el umbral) es un 200 con `low_confidence=true`.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.rate_limiting import RETRIEVAL_LIMIT, limiter
from app.api.security import require_retrieval_key
from app.dependencies import get_grounded_estimator
from app.generation.rag.errors import EmbedderUnavailableError
from app.generation.rag.estimator import GroundedEstimator
from app.generation.rag.retriever import RetrievalFilters
from app.generation.rag.schemas import RetrievalRequest, RetrievalResult

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/retrieval", tags=["retrieval"], dependencies=[Depends(require_retrieval_key)])

RETRIEVAL_RESPONSES = {
    401: {"description": "Clave de API ausente o no válida."},
    429: {"description": "Límite de peticiones superado (`Retry-After`)."},
    500: {"description": "Servicio de embeddings no disponible (mensaje genérico)."},
    502: {"description": "Fallo del proveedor de embeddings o de la base (mensaje genérico; detalle en el log)."},
}


async def run_retrieval(estimator: GroundedEstimator, payload: RetrievalRequest) -> RetrievalResult:
    """Recuperación compartida por este router y la etapa `retrieve`, con los errores saneados."""
    try:
        return await estimator.retrieve(
            payload.query_text,
            top_k=payload.top_k,
            distance_threshold=payload.distance_threshold,
            filters=RetrievalFilters.from_request(payload),
        )
    except EmbedderUnavailableError as exc:
        logger.error("rag_retrieval_failed", reason="embedder_unavailable")
        raise HTTPException(status_code=500, detail="El servicio de embeddings no está disponible.") from exc
    except Exception as exc:
        logger.error("rag_retrieval_failed", reason="search_error", error_type=type(exc).__name__)
        raise HTTPException(status_code=502, detail="No se pudo ejecutar la recuperación.") from exc


@router.post("/search", response_model=RetrievalResult, responses=RETRIEVAL_RESPONSES)
@limiter.limit(RETRIEVAL_LIMIT)
async def search(
    request: Request, payload: RetrievalRequest, estimator: GroundedEstimator = Depends(get_grounded_estimator)
) -> RetrievalResult:
    """Como máximo `top_k` chunks con distancia ≤ umbral que cumplen los filtros, de menor a mayor distancia."""
    return await run_retrieval(estimator, payload)
