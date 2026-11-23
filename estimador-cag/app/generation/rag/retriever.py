"""Recuperación semántica filtrada con umbral de relevancia (Sesión 9).

Embebe la consulta con el MISMO modelo que la ingesta (mezclar modelos hace las distancias inútiles), aplica los
filtros estructurales sobre los metadatos JSONB del chunk (`client_sector`, `year`) y la columna `chunk_type` DENTRO
de la consulta SQL, y descarta los candidatos por encima del umbral de distancia. El `ORDER BY` usa la expresión
exacta del índice HNSW halfvec (`halfvec_embedding()`), así que la consulta filtrada sigue usando
`chunks_embedding_halfvec_idx`. Filtrar en Python tras el k-NN perdería recall con filtros selectivos.

Cuando nada supera el umbral la recuperación hace *soft-fail*: `chunks=[]` y `low_confidence=True`, no un error.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

import structlog
from sqlalchemy import Integer, Select, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.foundation.persistence.models import EMBEDDING_DIMENSIONS, Chunk, halfvec_embedding
from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.errors import EmbedderUnavailableError, RetrievalError
from app.generation.rag.schemas import RetrievalRequest, RetrievalResult, RetrievedChunk

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RetrievalFilters:
    """Filtros estructurales; `None` (o lista vacía) significa «no filtrar por este eje»."""

    sectors: list[str] | None = None
    project_year_min: int | None = None
    project_year_max: int | None = None
    chunk_types: list[str] | None = None

    @classmethod
    def from_request(cls, request: RetrievalRequest) -> "RetrievalFilters":
        return cls(
            sectors=request.sectors,
            project_year_min=request.project_year_min,
            project_year_max=request.project_year_max,
            chunk_types=request.chunk_types,
        )


def structural_filters(filters: RetrievalFilters) -> list:
    """Predicados SQL sobre `chunks.metadata` (JSONB) y `chunks.chunk_type`."""
    sector = Chunk.metadata_["client_sector"].astext
    year = cast(Chunk.metadata_["year"].astext, Integer)
    predicates = [Chunk.embedding.is_not(None)]
    if filters.sectors:
        predicates.append(sector.in_(filters.sectors))
    if filters.project_year_min is not None:
        predicates.append(year >= filters.project_year_min)
    if filters.project_year_max is not None:
        predicates.append(year <= filters.project_year_max)
    if filters.chunk_types:
        predicates.append(Chunk.chunk_type.in_(filters.chunk_types))
    return predicates


def filtered_search_statement(
    vector: list[float], top_k: int, distance_threshold: float, filters: RetrievalFilters
) -> Select:
    """Los `top_k` chunks más cercanos que cumplen los filtros y el umbral, ordenados por la expresión del índice."""
    distance = halfvec_embedding().cosine_distance(vector)
    return (
        select(
            Chunk.id,
            Chunk.document_id,
            Chunk.chunk_type,
            Chunk.content,
            Chunk.metadata_,
            distance.label("distance"),
        )
        .where(*structural_filters(filters))
        .where(distance <= distance_threshold)
        .order_by(distance)
        .limit(top_k)
    )


def candidates_statement(filters: RetrievalFilters) -> Select:
    """Cuántos chunks cumplen los filtros antes del umbral y el límite (cardinalidad a vigilar)."""
    return select(func.count()).select_from(Chunk).where(*structural_filters(filters))


def _year(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _to_chunk(row) -> RetrievedChunk:
    metadata = row.metadata_ or {}
    return RetrievedChunk(
        id=row.id,
        content=row.content,
        sector=str(metadata.get("client_sector") or "unknown"),
        project_year=_year(metadata.get("year")),
        chunk_type=row.chunk_type,
        distance=float(row.distance),
        budget_id=metadata.get("budget_id"),
        document_id=row.document_id,
    )


class ChunkRetriever:
    """k-NN filtrado sobre `chunks`; abre una sesión por búsqueda (las etapas sin búsqueda no tocan la base)."""

    def __init__(
        self, session_factory: Callable[[], AsyncSession], embedder: OpenAIEmbedder | None, *, ef_search: int
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder
        self._ef_search = ef_search

    async def embed(self, text_: str) -> list[float]:
        if self._embedder is None:
            raise EmbedderUnavailableError("embedding service is not configured")
        try:
            vector = await self._embedder.embed_one(text_)
        except Exception as exc:
            raise RetrievalError("query embedding failed") from exc
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise RetrievalError(f"expected {EMBEDDING_DIMENSIONS} dimensions, received {len(vector)}")
        return vector

    async def search(
        self, query_text: str, *, top_k: int, distance_threshold: float, filters: RetrievalFilters
    ) -> RetrievalResult:
        """Embebe `query_text` y recupera; `EmbedderUnavailableError` sin embeddings, `RetrievalError` ante fallos."""
        vector = await self.embed(query_text)
        return await self.search_by_vector(vector, top_k=top_k, distance_threshold=distance_threshold, filters=filters)

    async def search_by_vector(
        self, vector: list[float], *, top_k: int, distance_threshold: float, filters: RetrievalFilters
    ) -> RetrievalResult:
        started = time.perf_counter()
        try:
            # `SET LOCAL` no admite parámetros enlazados; `ef_search` es un `int` validado en `Settings`.
            async with self._session_factory() as session:
                await session.execute(text(f"SET LOCAL hnsw.ef_search = {int(self._ef_search)}"))
                candidates = int((await session.execute(candidates_statement(filters))).scalar_one())
                rows = (
                    await session.execute(filtered_search_statement(vector, top_k, distance_threshold, filters))
                ).all()
        except Exception as exc:
            logger.error("rag_retrieval_failed", error_type=type(exc).__name__)
            raise RetrievalError("vector store query failed") from exc

        chunks = [_to_chunk(row) for row in rows]
        logger.info(
            "rag_retrieval_completed",
            results_count=len(chunks),
            candidates_evaluated=candidates,
            top_k=top_k,
            distance_threshold=distance_threshold,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        return RetrievalResult(chunks=chunks, low_confidence=not chunks, candidates_evaluated=candidates)
