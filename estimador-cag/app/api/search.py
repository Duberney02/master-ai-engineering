"""`POST /search`: búsqueda semántica sobre los presupuestos ingestados (distancia coseno, sin índice vectorial)."""

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_document_store
from app.generation.rag.schemas import SearchRequest, SearchResponse
from app.generation.rag.store.documents import DocumentStore

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["search"])


@router.post(
    "/search",
    response_model=SearchResponse,
    responses={
        503: {"description": "No hay base de datos configurada (`DATABASE_URL`)."},
        500: {"description": "Error del proveedor de embeddings o de la base (mensaje genérico; detalle en el log)."},
    },
)
async def search(request: SearchRequest, store: DocumentStore = Depends(get_document_store)) -> SearchResponse:
    """Los `k` chunks más cercanos a la consulta, de menor a mayor distancia coseno."""
    try:
        return await store.search(request.query, request.k)
    except Exception as exc:
        logger.error("search_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="No se pudo ejecutar la búsqueda.") from exc
