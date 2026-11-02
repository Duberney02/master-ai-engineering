"""Modelos ORM de la ingesta (sesión 6): dos tablas estrechas y de escritura infrecuente.

* `pseudonym_mappings`: correspondencia valor → seudónimo, con clave `(entity_type, original_hash)`.
  El hash es HMAC-SHA256 del valor original con una sal del servidor; guardar el hash y no el texto
  implica que leer la tabla no permite reconstruir el original. No hay desseudonimización: `forget`
  solo elimina el mapping.
* `ingestion_jobs`: seguimiento de `POST /api/v1/ingestion/runs`. Una tarea en segundo plano lo
  actualiza a `running`, `completed` o `failed` y `GET /api/v1/ingestion/jobs/{id}` lo lee.

Sesión 8: presupuestos vectorizados para la búsqueda semántica.

* `documents`: un presupuesto ingestado (`source_path` único) con sus metadatos estables.
* `chunks`: sus fragmentos con el embedding (`vector(1536)`, `text-embedding-3-small`); `ON DELETE CASCADE`.
  Índices HNSW (migración `0003`) sobre la *expresión* `embedding::halfvec(1536)`: la columna sigue en full precision y
  solo el índice usa media precisión (≈50 % de tamaño). Declararlos aquí no es posible sin que `alembic check` los
  vea como diferencias, así que viven solo en la migración; `halfvec_embedding()` da la expresión exacta del índice.

Usa una base declarativa propia (no la del historial) para que Alembic solo gestione estas tablas.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import HALFVEC, Vector
from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid, cast, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime

# Dimensión fija de `chunks.embedding`: la del modelo `text-embedding-3-small`. Cambiar de modelo exige migrar.
EMBEDDING_DIMENSIONS = 1536


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


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_source_path", "source_path", unique=True),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    # `metadata` está reservado por SQLAlchemy: el atributo se llama `metadata_` y la columna `metadata`.
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", passive_deletes=True)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_chunk_type", "chunk_type"),
        Index("ix_chunks_metadata_gin", "metadata", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Nulable: permite guardar el chunk antes de vectorizarlo (reintentos, re-embedding con otro modelo).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="chunks")


def halfvec_embedding():
    """`embedding::halfvec(1536)`: la expresión EXACTA del índice HNSW halfvec.

    Si el `ORDER BY` de una búsqueda no usa esta expresión con el operador `<=>`, Postgres ignora el índice sin avisar.
    """
    return cast(Chunk.embedding, HALFVEC(EMBEDDING_DIMENSIONS))
