"""`POST /embeddings/ingest` y `POST /embeddings/compare`. El prefijo `/embeddings` lo aplica `app.main`."""

from collections.abc import Callable

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.dependencies import get_chunker_builder, get_document_store, get_embedder
from app.generation.rag.analysis.comparison import ChunkingComparator, CompareRequest, CompareResponse
from app.generation.rag.chunking.base import Chunker
from app.generation.rag.chunking.registry import FREE_STRATEGIES, StrategyUnavailableError, UnknownStrategyError
from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.schemas import IngestRequest, IngestResponse
from app.generation.rag.store.documents import DocumentAlreadyIngestedError, DocumentStore

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["embeddings"])


@router.post(
    "/ingest",
    response_model=IngestResponse,
    responses={
        409: {"description": "Ya existe un documento con ese `source_path` (incluye su `document_id`)."},
        503: {"description": "No hay base de datos configurada (`DATABASE_URL`)."},
        500: {"description": "Error del proveedor de embeddings o de la base (mensaje genérico; detalle en el log)."},
    },
)
async def ingest(
    request: IngestRequest, store: DocumentStore = Depends(get_document_store)
) -> IngestResponse | JSONResponse:
    """Persiste un presupuesto como `document` + `chunks` con embedding, todo en una sola transacción."""
    try:
        return await store.ingest(request)
    except DocumentAlreadyIngestedError as exc:
        return JSONResponse(
            status_code=409, content={"detail": "Document already ingested", "document_id": exc.document_id}
        )
    except Exception as exc:
        logger.error("embeddings_ingest_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail="No se pudo ingestar el presupuesto.") from exc


@router.post(
    "/compare",
    response_model=CompareResponse,
    responses={
        400: {"description": "Estrategia desconocida."},
        503: {"description": "Falta la clave del proveedor que necesita alguna estrategia o los embeddings."},
        500: {"description": "Fallo al calcular la comparación (mensaje genérico; detalle en el log)."},
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
