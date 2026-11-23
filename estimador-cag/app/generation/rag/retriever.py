"""Recuperación filtrada con umbral, híbrida y con reranking (Sesiones 9 y 10).

Embebe la consulta con el MISMO modelo que la ingesta (mezclar modelos hace las distancias inútiles), aplica los
filtros estructurales sobre los metadatos JSONB del chunk (`client_sector`, `year`) y la columna `chunk_type` DENTRO
de la consulta SQL, y descarta los candidatos por encima del umbral de distancia. El `ORDER BY` usa la expresión
exacta del índice HNSW halfvec (`halfvec_embedding()`), así que la consulta filtrada sigue usando
`chunks_embedding_halfvec_idx`. Filtrar en Python tras el k-NN perdería recall con filtros selectivos.

Sesión 10 añade, sin tocar el comportamiento por defecto (`search_mode="vector"`, `rerank=False`):

* **Híbrido**: una rama léxica (`content_tsv` + GIN) que se fusiona con la vectorial mediante RRF. Un candidato que solo
  aporta la rama léxica entra en la fusión; el umbral de distancia sigue aplicándose a la rama vectorial.
* **Recall-then-rerank**: con `rerank=True` se recuperan `recall_top_k` candidatos de forma barata y un cross-encoder
  devuelve los `rerank_top_n` mejores con su `relevance_score`.

Cuando nada se recupera la recuperación hace *soft-fail*: `chunks=[]` y `low_confidence=True`, no un error.
`hybrid_search_one` es la primitiva por colección que reutiliza el pipeline avanzado (multi-índice, subconsultas).
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import structlog
from sqlalchemy import Integer, Select, Text, cast, func, select, text
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.ext.asyncio import AsyncSession

from app.foundation.persistence.models import EMBEDDING_DIMENSIONS, FTS_REGCONFIG, Chunk, halfvec_embedding
from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.errors import EmbedderUnavailableError, RetrievalError
from app.generation.rag.retrieval.collections import Collection, spec_for
from app.generation.rag.retrieval.fusion import DEFAULT_RRF_K, reciprocal_rank_fusion
from app.generation.rag.retrieval.reranker import Reranker, rerank_with_scores
from app.generation.rag.schemas import RetrievalRequest, RetrievalResult, RetrievedChunk

logger = structlog.get_logger(__name__)

# Distancia que se asigna a un candidato aportado SOLO por la rama léxica: nunca entró en el ranking vectorial, así que
# no tiene distancia coseno. Es un valor centinela de presentación (1.0 = «lejos»); fusión y reranking lo ignoran.
NO_VECTOR_DISTANCE = 1.0

SEARCH_MODES = ("vector", "hybrid")


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


def structural_filters(filters: RetrievalFilters, model: type = Chunk, *, require_embedding: bool = True) -> list:
    """Predicados SQL sobre `<tabla>.metadata` (JSONB) y `<tabla>.chunk_type`.

    `require_embedding=False` es para la rama léxica: un chunk sin vectorizar puede casar léxicamente.
    """
    sector = model.metadata_["client_sector"].astext
    year = cast(model.metadata_["year"].astext, Integer)
    predicates = [model.embedding.is_not(None)] if require_embedding else []
    if filters.sectors:
        predicates.append(sector.in_(filters.sectors))
    if filters.project_year_min is not None:
        predicates.append(year >= filters.project_year_min)
    if filters.project_year_max is not None:
        predicates.append(year <= filters.project_year_max)
    if filters.chunk_types:
        predicates.append(model.chunk_type.in_(filters.chunk_types))
    return predicates


def filtered_search_statement(
    vector: list[float],
    top_k: int,
    distance_threshold: float,
    filters: RetrievalFilters,
    *,
    model: type = Chunk,
    extra_filters: Sequence = (),
) -> Select:
    """Los `top_k` chunks más cercanos que cumplen los filtros y el umbral, ordenados por la expresión del índice."""
    distance = halfvec_embedding(model).cosine_distance(vector)
    return (
        select(
            model.id,
            model.document_id,
            model.chunk_type,
            model.content,
            model.metadata_,
            distance.label("distance"),
        )
        .where(*structural_filters(filters, model), *extra_filters)
        .where(distance <= distance_threshold)
        .order_by(distance)
        .limit(top_k)
    )


def candidates_statement(filters: RetrievalFilters, *, model: type = Chunk, extra_filters: Sequence = ()) -> Select:
    """Cuántos chunks cumplen los filtros antes del umbral y el límite (cardinalidad a vigilar)."""
    return select(func.count()).select_from(model).where(*structural_filters(filters, model), *extra_filters)


def lexical_tsquery(query_text: str):
    """`tsquery` de la consulta con los lexemas unidos por OR (`|`).

    `plainto_tsquery` los une con AND: con una consulta larga (el texto de búsqueda de una transcripción) casi nada
    cumple TODOS los lexemas y la rama léxica quedaría vacía justo cuando más aporta (un identificador literal entre
    muchas palabras). Con OR casa cualquier chunk con algún lexema y `ts_rank_cd` ordena por cobertura. La
    configuración de texto es la misma de la columna generada (`FTS_REGCONFIG`), o el índice GIN no se usaría.
    """
    plain = func.plainto_tsquery(FTS_REGCONFIG, query_text)
    return cast(func.replace(cast(plain, Text), " & ", " | "), TSQUERY)


def lexical_search_statement(
    query_text: str, top_k: int, filters: RetrievalFilters, *, model: type = Chunk, extra_filters: Sequence = ()
) -> Select:
    """Los `top_k` chunks con mejor `ts_rank_cd` (mayor es mejor) que casan léxicamente y cumplen los filtros."""
    tsquery = lexical_tsquery(query_text)
    rank = func.ts_rank_cd(model.content_tsv, tsquery)
    return (
        select(
            model.id,
            model.document_id,
            model.chunk_type,
            model.content,
            model.metadata_,
            rank.label("rank"),
        )
        .where(model.content_tsv.op("@@")(tsquery))
        .where(*structural_filters(filters, model, require_embedding=False), *extra_filters)
        .order_by(rank.desc(), model.id)
        .limit(top_k)
    )


class CollectionHits:
    """Salida del recall de una (colección, consulta): candidatos y el orden de cada rama.

    `candidates` mapea `id → RetrievedChunk` (los ids son únicos DENTRO de una colección). `vector_ids` y `lexical_ids`
    son los órdenes por rama que quien llama fusiona (RRF para expansión, *round-robin* para descomposición).
    """

    def __init__(
        self,
        *,
        collection: Collection,
        candidates: dict[int, RetrievedChunk],
        vector_ids: list[int],
        lexical_ids: list[int],
        candidates_evaluated: int,
    ) -> None:
        self.collection = collection
        self.candidates = candidates
        self.vector_ids = vector_ids
        self.lexical_ids = lexical_ids
        self.candidates_evaluated = candidates_evaluated

    def fused_order(self, *, search_mode: str, rrf_k: int = DEFAULT_RRF_K) -> list[RetrievedChunk]:
        """Chunks de mejor a peor: RRF de ambas ramas en `hybrid`; por distancia en `vector`."""
        if search_mode == "hybrid":
            fused = reciprocal_rank_fusion([self.vector_ids, self.lexical_ids], k=rrf_k)
            return [self.candidates[chunk_id] for chunk_id, _score in fused]
        return [self.candidates[chunk_id] for chunk_id in self.vector_ids]


async def hybrid_search_one(
    session: AsyncSession,
    *,
    collection: Collection,
    vector: list[float],
    query_text: str,
    search_mode: str,
    vector_limit: int,
    lexical_limit: int,
    distance_threshold: float,
    filters: RetrievalFilters,
    extra_filters: Sequence = (),
) -> CollectionHits:
    """Ramas vectorial y (en `hybrid`) léxica sobre UNA colección, con los mismos filtros en las dos."""
    spec = spec_for(collection)
    count = candidates_statement(filters, model=spec.model, extra_filters=extra_filters)
    candidates_total = int((await session.execute(count)).scalar_one())
    vector_rows = (
        await session.execute(
            filtered_search_statement(
                vector, vector_limit, distance_threshold, filters, model=spec.model, extra_filters=extra_filters
            )
        )
    ).all()
    lexical_rows = []
    if search_mode == "hybrid":
        lexical_rows = (
            await session.execute(
                lexical_search_statement(
                    query_text, lexical_limit, filters, model=spec.model, extra_filters=extra_filters
                )
            )
        ).all()

    candidates: dict[int, RetrievedChunk] = {}
    for row in vector_rows:
        candidates[row.id] = spec.to_chunk(row, distance=float(row.distance))
    for row in lexical_rows:
        candidates.setdefault(row.id, spec.to_chunk(row, distance=NO_VECTOR_DISTANCE))
    return CollectionHits(
        collection=collection,
        candidates=candidates,
        vector_ids=[row.id for row in vector_rows],
        lexical_ids=[row.id for row in lexical_rows],
        candidates_evaluated=candidates_total,
    )


class ChunkRetriever:
    """k-NN filtrado (y híbrido/rerank) sobre `chunks`; abre una sesión por búsqueda."""

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        embedder: OpenAIEmbedder | None,
        *,
        ef_search: int,
        reranker: Reranker | None = None,
        recall_top_k: int = 50,
        rerank_top_n: int = 5,
        rrf_k: int = DEFAULT_RRF_K,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder
        self._ef_search = ef_search
        self._reranker = reranker
        self._recall_top_k = recall_top_k
        self._rerank_top_n = rerank_top_n
        self._rrf_k = rrf_k

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
        self,
        query_text: str,
        *,
        top_k: int,
        distance_threshold: float,
        filters: RetrievalFilters,
        search_mode: str = "vector",
        rerank: bool = False,
        rerank_top_n: int | None = None,
    ) -> RetrievalResult:
        """Embebe `query_text` y recupera; `EmbedderUnavailableError` sin embeddings, `RetrievalError` ante fallos.

        `rerank_top_n` sustituye, solo en esta búsqueda, los mejores que devuelve el cross-encoder (por defecto, el del
        recuperador): las horas por tarea lo fijan a su propio `top_k`.
        """
        vector = await self.embed(query_text)
        return await self.search_by_vector(
            vector,
            top_k=top_k,
            distance_threshold=distance_threshold,
            filters=filters,
            query_text=query_text,
            search_mode=search_mode,
            rerank=rerank,
            rerank_top_n=rerank_top_n,
        )

    async def search_by_vector(
        self,
        vector: list[float],
        *,
        top_k: int,
        distance_threshold: float,
        filters: RetrievalFilters,
        query_text: str = "",
        search_mode: str = "vector",
        rerank: bool = False,
        rerank_top_n: int | None = None,
    ) -> RetrievalResult:
        if search_mode not in SEARCH_MODES:
            raise RetrievalError(f"unknown search mode: {search_mode}")
        if rerank and self._reranker is None:
            raise RetrievalError("reranker is not configured")

        started = time.perf_counter()
        # Recall ancho cuando una etapa posterior (fusión o reranking) reordena; exactamente `top_k` solo en la ruta
        # vectorial simple, donde el orden ya es el final.
        wide = rerank or search_mode == "hybrid"
        vector_limit = self._recall_top_k if wide else top_k
        try:
            # `SET LOCAL` no admite parámetros enlazados; `ef_search` es un `int` validado en `Settings`.
            async with self._session_factory() as session:
                await session.execute(text(f"SET LOCAL hnsw.ef_search = {int(self._ef_search)}"))
                hits = await hybrid_search_one(
                    session,
                    collection=Collection.BUDGET,
                    vector=vector,
                    query_text=query_text,
                    search_mode=search_mode,
                    vector_limit=vector_limit,
                    lexical_limit=self._recall_top_k,
                    distance_threshold=distance_threshold,
                    filters=filters,
                )
        except Exception as exc:
            logger.error("rag_retrieval_failed", error_type=type(exc).__name__)
            raise RetrievalError("vector store query failed") from exc

        ordered = hits.fused_order(search_mode=search_mode, rrf_k=self._rrf_k)
        if rerank and ordered:
            try:
                reranked = await rerank_with_scores(
                    self._reranker,
                    query_text,
                    ordered[: self._recall_top_k],
                    top_n=rerank_top_n or self._rerank_top_n,
                )
            except Exception as exc:
                logger.error("rag_rerank_failed", error_type=type(exc).__name__)
                raise RetrievalError("reranking failed") from exc
            chunks = [chunk.model_copy(update={"relevance_score": score}) for chunk, score in reranked]
        else:
            chunks = ordered[:top_k]

        logger.info(
            "rag_retrieval_completed",
            results_count=len(chunks),
            candidates_evaluated=hits.candidates_evaluated,
            top_k=top_k,
            distance_threshold=distance_threshold,
            search_mode=search_mode,
            rerank=rerank,
            vector_hits=len(hits.vector_ids),
            lexical_hits=len(hits.lexical_ids),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        return RetrievalResult(chunks=chunks, low_confidence=not chunks, candidates_evaluated=hits.candidates_evaluated)
