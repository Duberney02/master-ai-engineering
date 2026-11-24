"""Expansión incremental del corpus (Sesión 11): ampliar la colección `budget` sin volver a ingestar lo existente.

El corpus no puede crecer si cada ampliación obliga a repetir la ingesta completa. `CorpusExpansionService.run` procesa
un lote de presupuestos EN SEGUNDO PLANO (el endpoint responde `202` con un `job_id`) con el mismo modelo de embeddings
del corpus (re-embeber con otro exigiría una migración *blue-green*, fuera de alcance):

* Un presupuesto cuyo `source_path` ya existe (o cuyo `budget_id` ya está ingestado) se OMITE: un duplicado no tumba el
  lote.
* El progreso del trabajo (`documents_count`) se actualiza tras cada documento, con la tabla de jobs de la ingesta.
* Cualquier otro fallo marca el trabajo como `failed` con un mensaje GENÉRICO (el job se expone por HTTP): el detalle va
  al log. Los documentos ya confirmados se conservan (cada uno es su propia transacción).

Todo es asíncrono (sesión de SQLAlchemy y SDK de embeddings): no bloquea el event loop. Las tablas de transcripciones y
documentación técnica tienen HNSW (migración `0006`): los chunks nuevos se indexan sin reconstruir nada.
"""

import uuid
from collections.abc import Callable

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.foundation.persistence.models import Document
from app.foundation.persistence.repositories.jobs import JobsRepository
from app.generation.rag.chunking.base import Chunker
from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.retrieval.collections import COLLECTIONS
from app.generation.rag.schemas import (
    CollectionIndexStats,
    IndexRunRequest,
    IndexStatsResponse,
    IngestRequest,
)
from app.generation.rag.store.documents import DocumentAlreadyIngestedError, DocumentStore

logger = structlog.get_logger(__name__)

JOB_SOURCE_NAME = "index_run"
FAILURE_MESSAGE = "La expansión del corpus falló; el detalle está en el log del servicio."


def source_path_for(budget_id: str) -> str:
    """`source_path` estable de un presupuesto ampliado: reenviar el mismo lote lo omite en vez de duplicarlo."""
    return f"index_run#{budget_id}"


class CorpusExpansionService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        chunker: Chunker,
        embedder: OpenAIEmbedder | None,
        *,
        ef_search: int | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._chunker = chunker
        self._embedder = embedder
        self._ef_search = ef_search

    async def run(self, job_id: uuid.UUID, request: IndexRunRequest) -> None:
        """Cuerpo de la tarea en segundo plano: ingesta el lote y deja el trabajo en `completed` o `failed`."""
        indexed = skipped = 0
        async with self._session_factory() as jobs_session:
            jobs = JobsRepository(jobs_session)
            await jobs.mark_running(job_id)
            try:
                if self._embedder is None:
                    raise RuntimeError("embedder unavailable")
                async with self._session_factory() as session:
                    store = DocumentStore(session, self._chunker, self._embedder, ef_search=self._ef_search)
                    for budget in request.budgets:
                        if await self._already_indexed(session, budget.budget_id):
                            skipped += 1
                            continue
                        try:
                            await store.ingest(
                                IngestRequest(
                                    source_path=source_path_for(budget.budget_id),
                                    document_type=request.document_type,
                                    content=budget,
                                    chunk_type=request.chunk_type,
                                )
                            )
                        except DocumentAlreadyIngestedError:
                            skipped += 1  # otra ejecución ganó la carrera por el mismo `source_path`
                            continue
                        indexed += 1
                        await jobs.update_progress(job_id, documents_count=indexed)
                await jobs.mark_completed(job_id, documents_count=indexed)
            except Exception as exc:
                logger.error(
                    "corpus_expansion_failed",
                    job_id=str(job_id),
                    error_type=type(exc).__name__,
                    indexed=indexed,
                    skipped=skipped,
                )
                await jobs.mark_failed(job_id, error_message=FAILURE_MESSAGE)
                return
        logger.info("corpus_expansion_completed", job_id=str(job_id), indexed=indexed, skipped=skipped)

    @staticmethod
    async def _already_indexed(session: AsyncSession, budget_id: str) -> bool:
        """Duplicado por `source_path` de la expansión o por `budget_id` ya presente (p. ej. del corpus de ejemplo)."""
        found = await session.execute(
            select(Document.id)
            .where(
                (Document.source_path == source_path_for(budget_id))
                | (Document.metadata_["budget_id"].astext == budget_id)
            )
            .limit(1)
        )
        return found.scalar_one_or_none() is not None

    @staticmethod
    async def stats(session: AsyncSession) -> IndexStatsResponse:
        """Documentos, chunks e índice HNSW por colección, con la sesión de lectura de la solicitud."""
        collections: list[CollectionIndexStats] = []
        for collection, spec in COLLECTIONS.items():
            model = spec.model
            documents, chunks = (
                await session.execute(select(func.count(func.distinct(model.document_id)), func.count(model.id)))
            ).one()
            has_hnsw = (
                await session.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = current_schema() "
                        "AND tablename = :table AND indexdef ILIKE '%USING hnsw%')"
                    ),
                    {"table": model.__tablename__},
                )
            ).scalar_one()
            collections.append(
                CollectionIndexStats(
                    collection=collection.value, documents=documents, chunks=chunks, hnsw_index=bool(has_hnsw)
                )
            )
        return IndexStatsResponse(collections=collections, total_chunks=sum(c.chunks for c in collections))
