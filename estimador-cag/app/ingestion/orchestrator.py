"""Orchestrator: glues catalog + loader + parser into a single ingestion run.

The contract is intentionally narrow:

    ingest_source(catalog, source_name, *, loader, registry, jobs_repo, job_id)
      → list[Document]

Three guarantees:

1. The source must exist in the catalog and have ``decision == include``.
   Anything else raises ``IngestionRejected`` — the router maps that to 400/404.
2. ``jobs_repo`` is updated as the run progresses: pending → running → completed
   or failed. The router can poll it via the GET endpoint.
3. It is a coroutine invoked from a FastAPI BackgroundTask with its own database
   session. File reading and parsing are synchronous, so they run in a worker
   thread to keep the event loop free.

Scope: it produces documents and records their count. It does not index them,
create embeddings, or run cleaning or pseudonymization.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import structlog

from app.foundation.persistence.repositories.jobs import JobsRepository
from app.ingestion.catalog.models import CatalogDecision, DataCatalog
from app.ingestion.documents.models import Document
from app.ingestion.loaders.filesystem import FileSystemLoader
from app.ingestion.parsers.protocol import ParseContext
from app.ingestion.parsers.registry import ParserRegistry

log = structlog.get_logger(__name__)


class IngestionRejected(Exception):
    """The source is unknown or excluded/review — the run cannot start."""


async def ingest_source(
    *,
    catalog: DataCatalog,
    source_name: str,
    loader: FileSystemLoader,
    registry: ParserRegistry,
    jobs_repo: JobsRepository,
    job_id: uuid.UUID,
) -> list[Document]:
    """Run the ingestion for a single included source.

    Side effects:
      * Updates the ``ingestion_jobs`` row referenced by ``job_id``.
      * Logs structured events at the source boundary.
    """
    bound = log.bind(job_id=str(job_id), source_name=source_name)

    source = catalog.find(source_name)
    if source is None:
        raise IngestionRejected(f"source {source_name!r} not found in catalog")
    if source.decision is not CatalogDecision.INCLUDE:
        raise IngestionRejected(
            f"source {source_name!r} has decision={source.decision.value!r}; only 'include' sources can be ingested"
        )

    await jobs_repo.mark_running(job_id)
    bound.info("ingestion.started", format=source.format)

    context = ParseContext(
        source=source,
        source_version=catalog.version,
        ingested_at=datetime.now(timezone.utc),
    )

    def _load_and_parse() -> list[Document]:
        parser = registry.get(source.format)
        return [
            document
            for blob in loader.iter_blobs(source.location, {source.format})
            for document in parser.parse(blob, context)
        ]

    try:
        documents = await asyncio.to_thread(_load_and_parse)
    except Exception as exc:
        bound.error("ingestion.failed", error_type=type(exc).__name__)
        await jobs_repo.mark_failed(job_id, error_message=str(exc))
        raise

    await jobs_repo.mark_completed(job_id, documents_count=len(documents))
    bound.info("ingestion.completed", documents_count=len(documents))
    return documents
