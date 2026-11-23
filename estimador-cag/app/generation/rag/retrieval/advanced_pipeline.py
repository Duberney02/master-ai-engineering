"""Pipeline de recuperación avanzada multi-índice (Sesión 10).

Ensambla las técnicas en el orden «lo barato y excluyente, al principio; lo caro y fino, al final; lo blando, al
cierre»:

    transformación de consulta → routing → filtros duros → búsqueda híbrida → fusión
                               → reranking → decay temporal → top-k

Cada etapa se activa con `StageConfig`: el pipeline es el camino MÁXIMO, no el obligatorio, y cada técnica se puede
medir aislada. El endpoint construye el `StageConfig` con la precedencia petición → runtime → `Settings`; el script de
evaluación construye `StageConfig` con nombre como DATOS.

La fusión se diferencia por técnica: las variantes de una expansión se fusionan por consenso (RRF), las subconsultas de
una descomposición por cobertura (*round-robin*). Entre colecciones el reparto es también *round-robin*, con clave
`(colección, id)` porque los ids de chunk solo son únicos DENTRO de una colección. Cada chunk conserva su procedencia.

Los errores se sanean: cualquier fallo de embeddings, base de datos o reranker es `RetrievalError` y el detalle va al
log (la API responde 502 genérico).
"""

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.foundation.llm.runtime_config import RetrievalToggles
from app.foundation.llm.structured import Generator
from app.foundation.persistence.models import EMBEDDING_DIMENSIONS
from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.errors import EmbedderUnavailableError, RetrievalError
from app.generation.rag.retrieval.collections import Collection, HardFilters, spec_for
from app.generation.rag.retrieval.fusion import reciprocal_rank_fusion, round_robin_merge
from app.generation.rag.retrieval.query_transform import DECOMPOSE, SubQuery, Technique, transform_query
from app.generation.rag.retrieval.reranker import Reranker, rerank_with_scores
from app.generation.rag.retrieval.router import RoutingDecision, route
from app.generation.rag.retrieval.temporal import apply_temporal_decay
from app.generation.rag.retriever import CollectionHits, RetrievalFilters, hybrid_search_one
from app.generation.rag.schemas import RetrievedChunk

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class StageConfig:
    """Qué etapas avanzadas se ejecutan y con qué parámetros. Solo datos (sin E/S)."""

    routing_enabled: bool = True
    query_transform_enabled: bool = True
    search_mode: str = "hybrid"
    rerank: bool = True
    temporal_decay_enabled: bool = False
    top_k: int = 5
    recall_k: int = 50
    distance_threshold: float = 0.6
    rrf_k: int = 60
    half_life_days: int = 900
    max_subqueries: int = 4
    max_targets: int = 3
    router_model: str | None = None
    query_transform_model: str | None = None

    @classmethod
    def resolve(
        cls,
        settings: Settings,
        toggles: RetrievalToggles,
        *,
        search_mode: str | None = None,
        rerank: bool | None = None,
        routing_enabled: bool | None = None,
        query_transform_enabled: bool | None = None,
        temporal_decay_enabled: bool | None = None,
        top_k: int | None = None,
        distance_threshold: float | None = None,
    ) -> "StageConfig":
        """Configuración efectiva: campo explícito de la petición → runtime (`toggles`) → `Settings`.

        `toggles` ya mezcla el runtime con `Settings`; cada argumento explícito (no `None`) lo sustituye.
        """

        def pick(explicit, runtime):
            return runtime if explicit is None else explicit

        return cls(
            routing_enabled=pick(routing_enabled, toggles.routing_enabled),
            query_transform_enabled=pick(query_transform_enabled, toggles.query_transform_enabled),
            search_mode=pick(search_mode, toggles.search_mode),
            rerank=pick(rerank, toggles.rerank),
            temporal_decay_enabled=pick(temporal_decay_enabled, toggles.temporal_decay_enabled),
            top_k=top_k or settings.rerank_top_n,
            recall_k=settings.retrieval_recall_top_k,
            distance_threshold=pick(distance_threshold, settings.retrieval_distance_threshold),
            rrf_k=settings.rrf_k,
            half_life_days=settings.temporal_decay_half_life_days,
            max_subqueries=settings.query_max_subqueries,
            max_targets=settings.router_max_targets,
            router_model=settings.router_model,
            query_transform_model=settings.query_transform_model,
        )


@dataclass
class AdvancedRetrievalOutcome:
    """Lo que expone el endpoint: resultados y cómo se obtuvieron."""

    chunks: list[RetrievedChunk]
    routing: RoutingDecision
    technique: Technique
    subqueries: list[SubQuery]
    cardinality: dict[str, int] = field(default_factory=dict)
    low_confidence: bool = True


def _chunk_key(chunk: RetrievedChunk) -> tuple[str, int]:
    """Identidad de deduplicación entre colecciones (los ids solo son únicos dentro de una)."""
    return (chunk.collection, chunk.id)


def sigmoid(value: float) -> float:
    """Logit del cross-encoder → puntuación no negativa en (0, 1) para que el *decay* (multiplicador 0..1) conserve el
    orden en vez de invertir las puntuaciones negativas."""
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1.0 + exp)


def fuse_collection(
    hits_per_subquery: list[CollectionHits], *, technique: str, search_mode: str, rrf_k: int
) -> list[RetrievedChunk]:
    """Fusiona en una lista ordenada los resultados por subconsulta de UNA colección.

    Expansión o directa → RRF (consenso entre reformulaciones); descomposición → *round-robin* (cobertura por tema).
    """
    candidates: dict[int, RetrievedChunk] = {}
    for hits in hits_per_subquery:
        for chunk_id, chunk in hits.candidates.items():
            # Con una misma fila en varias subconsultas se conserva la de menor distancia vectorial.
            if chunk_id not in candidates or chunk.distance < candidates[chunk_id].distance:
                candidates[chunk_id] = chunk
    orders = [hits.fused_order(search_mode=search_mode, rrf_k=rrf_k) for hits in hits_per_subquery]

    if technique == DECOMPOSE:
        return round_robin_merge(orders, key=lambda chunk: chunk.id)

    fused = reciprocal_rank_fusion([[chunk.id for chunk in order] for order in orders], k=rrf_k)
    return [candidates[chunk_id] for chunk_id, _score in fused]


class AdvancedRetriever:
    """Ejecuta el pipeline avanzado. Todas las dependencias entran por el constructor (se sustituyen en las pruebas)."""

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        embedder: OpenAIEmbedder | None,
        *,
        generate: Generator,
        reranker: Reranker | None,
        ef_search: int,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder
        self._generate = generate
        self._reranker = reranker
        self._ef_search = ef_search

    async def _embed(self, queries: list[str]) -> list[list[float]]:
        if self._embedder is None:
            raise EmbedderUnavailableError("embedding service is not configured")
        try:
            vectors = await self._embedder.embed_texts(queries)
        except Exception as exc:
            raise RetrievalError("query embedding failed") from exc
        if len(vectors) != len(queries) or any(len(vector) != EMBEDDING_DIMENSIONS for vector in vectors):
            raise RetrievalError(f"expected {len(queries)} vectors of {EMBEDDING_DIMENSIONS} dimensions")
        return vectors

    async def _search(
        self,
        collection: Collection,
        subquery: SubQuery,
        vector: list[float],
        *,
        stages: StageConfig,
        filters: HardFilters,
    ) -> CollectionHits:
        """Una (colección, subconsulta) en su propia sesión: el abanico es realmente paralelo y seguro."""
        spec = spec_for(collection)
        wide = stages.rerank or stages.search_mode == "hybrid"
        async with self._session_factory() as session:
            # `SET LOCAL` no admite parámetros enlazados; `ef_search` es un `int` validado en `Settings`.
            await session.execute(text(f"SET LOCAL hnsw.ef_search = {int(self._ef_search)}"))
            return await hybrid_search_one(
                session,
                collection=collection,
                vector=vector,
                query_text=subquery.query,
                search_mode=stages.search_mode,
                vector_limit=stages.recall_k if wide else stages.top_k,
                lexical_limit=stages.recall_k,
                distance_threshold=stages.distance_threshold,
                # Cada colección solo recupera sus propios `chunk_type` (la tabla `chunks` también guarda las tareas
                # históricas de la estimación por horas).
                filters=RetrievalFilters(chunk_types=[spec.chunk_type]),
                extra_filters=spec.hard_filter_clauses(filters),
            )

    async def search(
        self,
        query_text: str,
        *,
        stages: StageConfig,
        reference_date: date,
        explicit_collections: list[Collection] | None = None,
        hard_filters: HardFilters | None = None,
    ) -> AdvancedRetrievalOutcome:
        started = time.perf_counter()
        hard_filters = hard_filters or HardFilters()
        if stages.rerank and self._reranker is None:
            raise RetrievalError("reranker is not configured")

        # Etapas 1 y 2: transformación de consulta y routing (independientes, concurrentes).
        plan, routing = await asyncio.gather(
            transform_query(
                query_text,
                generate=self._generate,
                enabled=stages.query_transform_enabled,
                model=stages.query_transform_model,
                max_subqueries=stages.max_subqueries,
            ),
            route(
                query_text,
                generate=self._generate,
                explicit=explicit_collections,
                enabled=stages.routing_enabled,
                max_targets=stages.max_targets,
                model=stages.router_model,
            ),
        )

        # Cada subconsulta se embebe una sola vez (una llamada por lotes al proveedor).
        vectors = await self._embed([subquery.query for subquery in plan.subqueries])

        # Etapas 3 y 4: filtros duros + búsqueda híbrida por (colección, subconsulta).
        try:
            flat = await asyncio.gather(
                *(
                    self._search(collection, subquery, vector, stages=stages, filters=hard_filters)
                    for collection in routing.targets
                    for subquery, vector in zip(plan.subqueries, vectors, strict=True)
                )
            )
        except Exception as exc:
            logger.error("advanced_search_failed", error_type=type(exc).__name__)
            raise RetrievalError("vector store query failed") from exc

        # Las subconsultas de cada colección son contiguas: se reagrupan por colección.
        width = len(plan.subqueries)
        per_collection = {
            collection: flat[index * width : (index + 1) * width] for index, collection in enumerate(routing.targets)
        }

        # Etapa 5: fusión dentro de cada colección y *round-robin* entre colecciones (cobertura; procedencia intacta).
        cardinality: dict[str, int] = {}
        orders: list[list[RetrievedChunk]] = []
        for collection, hits_list in per_collection.items():
            cardinality[collection.value] = hits_list[0].candidates_evaluated
            logger.info(
                "advanced_collection_cardinality", collection=collection.value, candidates=cardinality[collection.value]
            )
            ordered = fuse_collection(
                list(hits_list), technique=plan.technique, search_mode=stages.search_mode, rrf_k=stages.rrf_k
            )
            if ordered:
                orders.append(ordered)
        pool = round_robin_merge(orders, key=_chunk_key)[: stages.recall_k]

        # Etapa 6: reranking (puntuaciones del cross-encoder) o puntuación posicional.
        if stages.rerank and pool:
            try:
                reranked = await rerank_with_scores(self._reranker, query_text, pool, top_n=len(pool))
            except Exception as exc:
                logger.error("advanced_rerank_failed", error_type=type(exc).__name__)
                raise RetrievalError("reranking failed") from exc
            scored = [(chunk, sigmoid(score)) for chunk, score in reranked]
        else:
            scored = [(chunk, 1.0 / (position + 1)) for position, chunk in enumerate(pool)]

        # Etapa 7: decay temporal (blando, al cierre) y corte final a top-k.
        if stages.temporal_decay_enabled:
            scored = apply_temporal_decay(scored, half_life_days=stages.half_life_days, reference_date=reference_date)
        chunks = [chunk.model_copy(update={"relevance_score": score}) for chunk, score in scored[: stages.top_k]]

        logger.info(
            "advanced_retrieve_done",
            technique=plan.technique,
            routing_level=routing.level,
            targets=[target.value for target in routing.targets],
            subqueries=len(plan.subqueries),
            pool=len(pool),
            results=len(chunks),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        return AdvancedRetrievalOutcome(
            chunks=chunks,
            routing=routing,
            technique=plan.technique,
            subqueries=plan.subqueries,
            cardinality=cardinality,
            low_confidence=not chunks,
        )
