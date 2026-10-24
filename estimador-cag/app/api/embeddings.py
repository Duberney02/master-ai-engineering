"""`POST /embeddings/ingest` y `POST /embeddings/compare`. El prefijo `/embeddings` lo aplica `app.main`."""

from collections.abc import Callable

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings, get_settings
from app.dependencies import get_chunker, get_chunker_builder, get_embedder
from app.generation.rag.analysis.comparison import ChunkingComparator, CompareRequest, CompareResponse
from app.generation.rag.chunking.base import Chunker
from app.generation.rag.chunking.registry import FREE_STRATEGIES, StrategyUnavailableError, UnknownStrategyError
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
async def ingest(
    request: IngestRequest,
    chunker: JSONStructuralChunker = Depends(get_chunker),
    embedder: OpenAIEmbedder = Depends(get_embedder),
) -> IngestResponse:
    chunks = await chunker.chunk(request.budgets)
    try:
        embedded = await embedder.embed_many(chunks)
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


@router.post(
    "/compare",
    response_model=CompareResponse,
    responses={
        400: {"description": "Estrategia desconocida."},
        503: {"description": "Falta la clave del proveedor que necesita alguna estrategia o los embeddings."},
        500: {"description": "Fallo al calcular la comparación (mensaje genérico; el detalle va al log)."},
    },
)
async def compare(
    request: CompareRequest,
    embedder: OpenAIEmbedder = Depends(get_embedder),
    build_chunkers: Callable[[list[str]], list[Chunker]] = Depends(get_chunker_builder),
    settings: Settings = Depends(get_settings),
) -> CompareResponse:
    """Compara estrategias de chunking sobre los mismos presupuestos, sin persistir nada.

    Sin `strategies` se ejecutan solo las gratuitas: las de pago (semantic, propositional,
    contextual_retrieval) llaman a un LLM o a embeddings durante el chunking y hay que pedirlas por nombre.
    """
    names = request.strategies or list(FREE_STRATEGIES)
    try:
        chunkers = build_chunkers(names)
    except UnknownStrategyError as exc:
        raise HTTPException(status_code=400, detail=f"Estrategia desconocida: {exc.args[0]}") from exc
    except StrategyUnavailableError as exc:
        logger.error("embeddings_compare_failed", reason="strategy_unavailable", strategy=exc.strategy)
        raise HTTPException(status_code=503, detail=exc.reason) from exc

    if (request.queries or "semantic" in names) and not settings.openai_api_key:
        logger.error("embeddings_compare_failed", reason="embedder_unavailable")
        raise HTTPException(status_code=503, detail="Los embeddings requieren OPENAI_API_KEY.")

    logger.info(
        "embeddings_compare_received",
        total_budgets=len(request.budgets),
        strategies_count=len(names),
        queries_count=len(request.queries),
    )
    comparator = ChunkingComparator(chunkers, embedder)
    try:
        stats = await comparator.compute_stats(request.budgets)
        queries = await comparator.run_queries(request.budgets, request.queries, request.top_k)
    except Exception as exc:
        logger.error("embeddings_compare_failed", reason="comparison_error", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="No se pudo ejecutar la comparación de chunking.") from exc
    return CompareResponse(stats_per_strategy=stats, queries_per_strategy=queries)
