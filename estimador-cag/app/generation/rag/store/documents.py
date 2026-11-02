"""Almacén vectorial sobre PostgreSQL + pgvector: ingesta transaccional de presupuestos y búsqueda semántica.

La ingesta usa una sola sesión y una sola transacción: el `document` y sus `chunks` se confirman juntos o no se
confirma nada (un fallo del embedder no deja documentos huérfanos). La búsqueda ordena por distancia coseno con la
expresión del índice HNSW halfvec (migración `0003`) y fija `hnsw.ef_search` en su transacción.
"""

import time

import structlog
from sqlalchemy import Select, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.foundation.persistence.models import EMBEDDING_DIMENSIONS, Chunk, Document, halfvec_embedding
from app.generation.rag.chunking.base import Chunker
from app.generation.rag.chunking.structural import budget_metadata
from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.schemas import IngestRequest, IngestResponse, SearchResponse, SearchResult

logger = structlog.get_logger(__name__)

CHUNK_TYPE = "budget_component"


class DocumentAlreadyIngestedError(Exception):
    def __init__(self, document_id: int) -> None:
        super().__init__(f"document {document_id} already ingested")
        self.document_id = document_id


class EmbeddingDimensionError(Exception):
    """El embedder devolvió vectores que no caben en la columna `vector(1536)`."""


def _check_dimension(vector: list[float]) -> None:
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise EmbeddingDimensionError(f"expected {EMBEDDING_DIMENSIONS} dimensions, received {len(vector)}")


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def search_statement(vector: list[float], k: int) -> Select:
    """Los `k` chunks más cercanos por distancia coseno, con la expresión EXACTA del índice HNSW halfvec.

    `CAST(embedding AS HALFVEC(1536)) <=> :q` coincide con `chunks_embedding_halfvec_idx` (`halfvec_cosine_ops`); con
    otra expresión u operador Postgres ignora el índice y vuelve al *sequential scan* sin avisar.
    """
    distance = halfvec_embedding().cosine_distance(vector).label("distance")
    return (
        select(Chunk.id, Chunk.document_id, Chunk.chunk_type, Chunk.content, Chunk.metadata_, distance)
        .where(Chunk.embedding.is_not(None))  # un chunk sin vectorizar no tiene distancia
        .order_by(distance)
        .limit(k)
    )


class DocumentStore:
    def __init__(
        self, session: AsyncSession, chunker: Chunker, embedder: OpenAIEmbedder, ef_search: int | None = None
    ) -> None:
        self._session = session
        self._chunker = chunker
        self._embedder = embedder
        self._configured_ef_search = ef_search

    def _ef_search(self) -> int:
        return self._configured_ef_search or get_settings().hnsw_ef_search

    async def ingest(self, request: IngestRequest) -> IngestResponse:
        """Persiste el presupuesto como un `document` y sus `chunks` con embedding, en una sola transacción."""
        started = time.perf_counter()
        session = self._session
        existing = await self._document_id(request.source_path)
        if existing is not None:
            raise DocumentAlreadyIngestedError(existing)

        budget = request.content
        document = Document(
            source_path=request.source_path,
            document_type=request.document_type,
            metadata_={
                **budget_metadata(budget),
                "project_summary": budget.project_summary,
                "total_estimated_hours": budget.total_estimated_hours,
            },
        )
        try:
            session.add(document)
            await session.flush()  # asigna `document.id`; sigue dentro de la transacción
            chunks = await self._chunker.chunk([budget])
            embedded = await self._embedder.embed_many(chunks)
            for item in embedded:
                _check_dimension(item.embedding)
            session.add_all(
                Chunk(
                    document_id=document.id,
                    chunk_type=CHUNK_TYPE,
                    content=item.text,
                    embedding=item.embedding,
                    metadata_={**item.metadata, "chunk_id": item.chunk_id, "token_count": item.token_count},
                )
                for item in embedded
            )
            await session.commit()
        except IntegrityError:
            # Otra ingesta del mismo `source_path` ganó la carrera (índice único).
            await session.rollback()
            winner = await self._document_id(request.source_path)
            if winner is None:
                raise
            raise DocumentAlreadyIngestedError(winner) from None
        except Exception:
            await session.rollback()
            raise

        response = IngestResponse(
            document_id=document.id,
            chunks_created=len(embedded),
            embedding_dimension=EMBEDDING_DIMENSIONS,
            ingestion_time_ms=_elapsed_ms(started),
        )
        logger.info(
            "document_ingested",
            document_id=response.document_id,
            chunks_created=response.chunks_created,
            ingestion_time_ms=response.ingestion_time_ms,
        )
        return response

    async def search(self, query: str, k: int) -> SearchResponse:
        """Los `k` chunks más cercanos a la consulta por distancia coseno (operador `<=>`, índice HNSW halfvec)."""
        started = time.perf_counter()
        vector = await self._embedder.embed_one(query)
        _check_dimension(vector)

        statement = search_statement(vector, k)
        # `SET LOCAL` dura lo que la transacción; no admite parámetros enlazados, pero `ef_search` es un `int` validado.
        await self._session.execute(text(f"SET LOCAL hnsw.ef_search = {int(self._ef_search())}"))
        rows = (await self._session.execute(statement)).all()
        results = [
            SearchResult(
                chunk_id=row.id,
                document_id=row.document_id,
                chunk_type=row.chunk_type,
                content=row.content,
                distance=row.distance,
                metadata=row.metadata_,
            )
            for row in rows
        ]
        elapsed = _elapsed_ms(started)
        logger.info("semantic_search_completed", k=k, results_count=len(results), search_time_ms=elapsed)
        return SearchResponse(query=query, k=k, search_time_ms=elapsed, results=results)

    async def _document_id(self, source_path: str) -> int | None:
        statement = select(Document.id).where(Document.source_path == source_path)
        return (await self._session.execute(statement)).scalar_one_or_none()
