"""Modelos ORM de la ingesta (sesión 6): dos tablas estrechas y de escritura infrecuente.

* `pseudonym_mappings`: correspondencia valor → seudónimo, con clave `(entity_type, original_hash)`.
  El hash es HMAC-SHA256 del valor original con una sal del servidor; guardar el hash y no el texto
  implica que leer la tabla no permite reconstruir el original. No hay desseudonimización: `forget`
  solo elimina el mapping.
* `ingestion_jobs`: seguimiento de `POST /api/v1/ingestion/runs`. Una tarea en segundo plano lo
  actualiza a `running`, `completed` o `failed` y `GET /api/v1/ingestion/jobs/{id}` lo lee.

Usa una base declarativa propia (no la del historial) para que Alembic solo gestione estas tablas.
"""

import uuid
from datetime import datetime

from sqlalchemy import Index, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import DateTime


class Base(DeclarativeBase):
    """Base declarativa única, descubierta por `alembic/env.py`."""


class PseudonymMappingRow(Base):
    __tablename__ = "pseudonym_mappings"
    __table_args__ = (
        UniqueConstraint("entity_type", "original_hash", name="uq_mappings_entity_hash"),
        Index("idx_mappings_lookup", "entity_type", "original_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    original_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    pseudonym: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IngestionJobRow(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (Index("idx_jobs_status", "status"),)

    job_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    documents_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
