"""`POST /embeddings/ingest`. El prefijo `/embeddings` lo aplica `app.main` al registrar el router."""

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_chunker, get_embedder
from app.generation.rag.chunking.structural import JSONStructuralChunker
from app.generation.rag.embedding.embedder import OpenAIEmbedder, estimate_cost_usd
from app.generation.rag.schemas import IngestRequest, IngestResponse

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["embeddings"])


@router.post(
    "/ingest",
    response_model=IngestResponse,
    responses={500: {"description": "Error del proveedor de embeddings (mensaje genérico; el detalle va al log)."}},
)
def ingest(
    request: IngestRequest,
    chunker: JSONStructuralChunker = Depends(get_chunker),
    embedder: OpenAIEmbedder = Depends(get_embedder),
) -> IngestResponse:
    # `def` y no `async def`: el embedder es bloqueante y FastAPI lo ejecuta en su pool de hilos.
    chunks = chunker.chunk(request.budgets)
    try:
        embedded = embedder.embed_many(chunks)
    except Exception as exc:
        logger.error("embeddings_ingest_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="No se pudieron generar los embeddings.") from exc

    total_tokens = sum(chunk.token_count for chunk in embedded)
    stats = {
        "total_budgets": len(request.budgets),
        "total_chunks": len(embedded),
        "total_tokens": total_tokens,
        "estimated_cost_usd": estimate_cost_usd(total_tokens),
    }
    logger.info(
        "embeddings_ingest_completed",
        total_budgets=stats["total_budgets"],
        total_chunks=stats["total_chunks"],
        total_tokens=total_tokens,
        estimated_cost_usd=stats["estimated_cost_usd"],
    )
    return IngestResponse(chunks=embedded, stats=stats)
