"""Repositorio de trabajos de ingesta.

Un trabajo pasa por `pending → running → completed | failed`: la API crea la fila, la tarea en
segundo plano la transita y el GET la lee. Los llamantes reciben dataclasses, no tipos del ORM.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.models import IngestionJobRow

JobStatusName = Literal["pending", "running", "completed", "failed"]
MAX_ERROR_CHARS = 2048


@dataclass(frozen=True)
class Job:
    job_id: uuid.UUID
    source_name: str
    status: JobStatusName
    documents_count: int
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None


class JobsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, source_name: str) -> Job:
        row = IngestionJobRow(source_name=source_name, status="pending")
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _to_job(row)

    async def get(self, job_id: uuid.UUID) -> Job | None:
        row = await self._session.get(IngestionJobRow, job_id)
        return _to_job(row) if row is not None else None

    async def mark_running(self, job_id: uuid.UUID) -> None:
        await self._update(job_id, status="running")

    async def mark_completed(self, job_id: uuid.UUID, *, documents_count: int) -> None:
        await self._update(
            job_id,
            status="completed",
            documents_count=documents_count,
            finished_at=datetime.now(timezone.utc),
        )

    async def mark_failed(self, job_id: uuid.UUID, *, error_message: str) -> None:
        await self._update(
            job_id,
            status="failed",
            error_message=error_message[:MAX_ERROR_CHARS],
            finished_at=datetime.now(timezone.utc),
        )

    async def _update(self, job_id: uuid.UUID, **fields) -> None:
        row = await self._session.get(IngestionJobRow, job_id)
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        await self._session.commit()


def _to_job(row: IngestionJobRow) -> Job:
    return Job(
        job_id=row.job_id,
        source_name=row.source_name,
        status=row.status,  # type: ignore[arg-type]
        documents_count=row.documents_count,
        error_message=row.error_message,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


async def list_jobs(session: AsyncSession, *, limit: int = 50) -> list[Job]:
    """Ayuda de depuración para pruebas y preflight; no se expone por HTTP."""
    rows = (
        (await session.execute(select(IngestionJobRow).order_by(IngestionJobRow.started_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return [_to_job(r) for r in rows]
