"""`POST /v1/retrieval/search`: recuperación semántica con umbral y filtros por metadatos (Sesión 9).

Sesión 10: acepta `search_mode` (`vector|hybrid`) y `rerank` opcionales; sin ellos se resuelven con el runtime
(`/api/v1/config/retrieval`) y `Settings`. El resto del contrato no cambia.

Endpoint canónico de búsqueda. `POST /search` (Sesión 8, sin filtros ni umbral) se mantiene por compatibilidad
(Chunking Lab, demos). Transporte fino: validación en `RetrievalRequest` (422), clave en `require_retrieval_key`
(401), límite en el decorador (429). El *soft-fail* (nada supera el umbral) es un 200 con `low_confidence=true`.
"""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.rate_limiting import RETRIEVAL_LIMIT, limiter
from app.api.security import require_retrieval_key
from app.config import get_settings
from app.dependencies import get_advanced_retriever, get_grounded_estimator, get_runtime_retrieval_config
from app.foundation.llm.runtime_config import RuntimeRetrievalConfig
from app.generation.rag.errors import EmbedderUnavailableError
from app.generation.rag.estimator import GroundedEstimator
from app.generation.rag.retrieval.advanced_pipeline import AdvancedRetriever, StageConfig
from app.generation.rag.retrieval.collections import HardFilters
from app.generation.rag.retriever import RetrievalFilters
from app.generation.rag.schemas import (
    AdvancedSearchRequest,
    AdvancedSearchResult,
    RetrievalRequest,
    RetrievalResult,
    RoutingInfo,
    SubQueryInfo,
)

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
            search_mode=payload.search_mode,
            rerank=payload.rerank,
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


@router.post("/advanced-search", response_model=AdvancedSearchResult, responses=RETRIEVAL_RESPONSES)
@limiter.limit(RETRIEVAL_LIMIT)
async def advanced_search(
    request: Request,
    payload: AdvancedSearchRequest,
    retriever: AdvancedRetriever = Depends(get_advanced_retriever),
    runtime: RuntimeRetrievalConfig = Depends(get_runtime_retrieval_config),
) -> AdvancedSearchResult:
    """Búsqueda multi-índice con *routing*, transformación de consulta, filtros duros, fusión, reranking y *decay*.

    Cada etapa se resuelve con la precedencia petición → runtime (`/api/v1/config/retrieval`) → `Settings`. La respuesta
    incluye el diagnóstico: nivel y motivo del *routing*, técnica, subconsultas y cardinalidad por colección.
    """
    stages = StageConfig.resolve(
        get_settings(),
        await runtime.effective(),
        search_mode=payload.search_mode,
        rerank=payload.rerank,
        routing_enabled=payload.routing_enabled,
        query_transform_enabled=payload.query_transform_enabled,
        temporal_decay_enabled=payload.temporal_decay_enabled,
        top_k=payload.top_k,
    )
    hard_filters = HardFilters(
        technologies=tuple(payload.technologies or ()),
        sectors=tuple(payload.sectors or ()),
        min_date=payload.min_date,
        version=payload.doc_version,
    )
    try:
        outcome = await retriever.search(
            payload.query_text,
            stages=stages,
            reference_date=datetime.now(UTC).date(),
            explicit_collections=payload.collections,
            hard_filters=hard_filters,
        )
    except EmbedderUnavailableError as exc:
        logger.error("advanced_retrieval_failed", reason="embedder_unavailable")
        raise HTTPException(status_code=500, detail="El servicio de embeddings no está disponible.") from exc
    except Exception as exc:
        logger.error("advanced_retrieval_failed", reason="search_error", error_type=type(exc).__name__)
        raise HTTPException(status_code=502, detail="No se pudo ejecutar la recuperación.") from exc

    return AdvancedSearchResult(
        chunks=outcome.chunks,
        low_confidence=outcome.low_confidence,
        routing=RoutingInfo(
            level=outcome.routing.level, targets=outcome.routing.targets, reason=outcome.routing.reason
        ),
        technique=outcome.technique,
        subqueries=[SubQueryInfo(topic=sq.topic, query=sq.query) for sq in outcome.subqueries],
        cardinality=outcome.cardinality,
    )
