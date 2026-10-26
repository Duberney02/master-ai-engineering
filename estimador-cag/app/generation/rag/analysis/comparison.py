"""Framework de comparación de estrategias de chunking.

Dos señales informales (las métricas formales, como recall@k o NDCG, son de la Sesión 11):

1. **Estadísticas del corpus** por estrategia: número de chunks, distribución de tokens y cuántos chunks
   degenerados hay (huérfanos < 20 tokens, obesos > 800). De un vistazo se ve qué estrategia descompone con
   sentido y cuál se desmorona.
2. **Top-k por similitud coseno** sobre un conjunto fijo de consultas: los mejores chunks que recupera cada
   estrategia, con su puntuación, para juzgarlos a ojo.

Nada se persiste (la persistencia es de la Sesión 8). Cada estrategia se trocea **una sola vez** por conjunto
de presupuestos y el resultado se memoiza, de modo que pedir estadísticas y consultas a la vez nunca paga dos
veces las estrategias de pago; lo mismo ocurre con los embeddings de los chunks.
"""

import time
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.generation.rag.analysis.similarity import cosine_similarity, percentile
from app.generation.rag.chunking.base import Chunker
from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.schemas import Budget, Chunk, EmbeddedChunk

# Umbrales de degeneración, en tokens. Valores de partida: son los únicos parámetros del análisis.
ORPHAN_MAX_TOKENS = 20
OBESE_MIN_TOKENS = 800

PREVIEW_CHARS = 160


class TokenDistribution(BaseModel):
    min: int = 0
    p50: float = 0.0
    p95: float = 0.0
    max: int = 0


class ChunkingStats(BaseModel):
    strategy: str
    n_chunks: int
    token_distribution: TokenDistribution
    n_orphan_chunks: int
    n_obese_chunks: int
    ingestion_cost_usd: float
    extra_api_calls: int = 0
    ingestion_seconds: float


class TopChunk(BaseModel):
    chunk_id: str
    cosine: float
    text_preview: str
    # Solo en la estrategia jerárquica: «parent» o «child», y el padre de cada hijo.
    level: str | None = None
    parent_chunk_id: str | None = None


class QueryResult(BaseModel):
    strategy: str
    query: str
    top_k: list[TopChunk] = Field(default_factory=list)


class CompareRequest(BaseModel):
    budgets: list[Budget] = Field(min_length=1)
    queries: list[str] = Field(default_factory=list)
    # Vacío = las estrategias gratuitas. Las de pago (LLM o embeddings en la ingesta) son opt-in.
    strategies: list[str] = Field(default_factory=list)
    top_k: int = Field(default=3, ge=1, le=10)


class CompareResponse(BaseModel):
    stats_per_strategy: dict[str, ChunkingStats]
    queries_per_strategy: dict[str, list[QueryResult]]


def preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


@dataclass
class _Materialized:
    chunks: list[Chunk]
    seconds: float
    cost_usd: float
    extra_api_calls: int


class ChunkingComparator:
    """Ejecuta varias estrategias sobre el mismo corpus y las compara."""

    def __init__(self, chunkers: list[Chunker], embedder: OpenAIEmbedder) -> None:
        self._chunkers = chunkers
        self._embedder = embedder
        self._materialized: dict[str, _Materialized] | None = None
        self._materialized_for: list[Budget] | None = None
        self._embedded: dict[str, list[EmbeddedChunk]] = {}

    async def _materialize(self, budgets: list[Budget]) -> dict[str, _Materialized]:
        """Trocea cada estrategia una vez; se memoiza por objeto `budgets`."""
        if self._materialized is not None and self._materialized_for is budgets:
            return self._materialized
        result: dict[str, _Materialized] = {}
        for chunker in self._chunkers:
            started = time.perf_counter()
            chunks = await chunker.chunk(budgets)
            result[chunker.strategy_name] = _Materialized(
                chunks=chunks,
                seconds=time.perf_counter() - started,
                cost_usd=chunker.last_extra_cost_usd,
                extra_api_calls=chunker.last_extra_api_calls,
            )
        self._materialized, self._materialized_for, self._embedded = result, budgets, {}
        return result

    def use_embedder(self, embedder: OpenAIEmbedder) -> None:
        """Cambia de embedder (p. ej. otra dimensión) conservando el chunking ya pagado."""
        self._embedder = embedder
        self._embedded = {}

    async def chunks_of(self, budgets: list[Budget], strategy: str) -> list[Chunk]:
        return (await self._materialize(budgets))[strategy].chunks

    async def compute_stats(self, budgets: list[Budget]) -> dict[str, ChunkingStats]:
        materialized = await self._materialize(budgets)
        return {name: self._stats_for(name, data) for name, data in materialized.items()}

    async def run_queries(
        self, budgets: list[Budget], queries: list[str], top_k: int = 3
    ) -> dict[str, list[QueryResult]]:
        if not queries:
            return {}
        materialized = await self._materialize(budgets)
        query_vectors = dict(zip(queries, await self._embedder.embed_texts(queries), strict=True))
        results: dict[str, list[QueryResult]] = {}
        for name, data in materialized.items():
            if name not in self._embedded:
                self._embedded[name] = await self._embedder.embed_many(data.chunks)
            embedded = self._embedded[name]
            per_query: list[QueryResult] = []
            for query in queries:
                scored = sorted(
                    (
                        TopChunk(
                            chunk_id=chunk.chunk_id,
                            cosine=round(cosine_similarity(query_vectors[query], chunk.embedding), 4),
                            text_preview=preview(chunk.text),
                            level=chunk.metadata.get("level"),
                            parent_chunk_id=chunk.metadata.get("parent_chunk_id"),
                        )
                        for chunk in embedded
                    ),
                    key=lambda top: top.cosine,
                    reverse=True,
                )
                per_query.append(QueryResult(strategy=name, query=query, top_k=scored[:top_k]))
            results[name] = per_query
        return results

    @staticmethod
    def _stats_for(name: str, data: _Materialized) -> ChunkingStats:
        counts = [chunk.token_count for chunk in data.chunks]
        return ChunkingStats(
            strategy=name,
            n_chunks=len(counts),
            token_distribution=TokenDistribution(
                min=min(counts, default=0),
                p50=round(percentile(counts, 50), 1),
                p95=round(percentile(counts, 95), 1),
                max=max(counts, default=0),
            ),
            n_orphan_chunks=sum(1 for t in counts if t < ORPHAN_MAX_TOKENS),
            n_obese_chunks=sum(1 for t in counts if t > OBESE_MIN_TOKENS),
            ingestion_cost_usd=round(data.cost_usd, 6),
            extra_api_calls=data.extra_api_calls,
            ingestion_seconds=round(data.seconds, 3),
        )
