"""Sesión 8: extensión pgvector, `documents` y `chunks` (sin índice vectorial).

Revision ID: 0002_pgvector_documents_chunks
Revises: 0001_session6_initial
Create Date: 2026-11-02 00:00:00
"""
from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_pgvector_documents_chunks"
down_revision: str | None = "0001_session6_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMPTY_JSON = sa.text("'{}'::jsonb")


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgresql():  # pgvector solo existe en PostgreSQL; las pruebas con SQLite aplican solo la 0001
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source_path", sa.Text, nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default=EMPTY_JSON),
    )
    op.create_index("ix_documents_source_path", "documents", ["source_path"], unique=True)

    op.create_table(
        "chunks",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "document_id", sa.BigInteger, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("chunk_type", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(1536), nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default=EMPTY_JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])
    op.create_index("ix_chunks_chunk_type", "chunks", ["chunk_type"])
    op.create_index("ix_chunks_metadata_gin", "chunks", ["metadata"], postgresql_using="gin")
    # Sin índice vectorial (HNSW/IVFFlat): el sequential scan es la línea base de las mediciones.


def downgrade() -> None:
    if not _is_postgresql():
        return
    op.drop_index("ix_chunks_metadata_gin", table_name="chunks")
    op.drop_index("ix_chunks_chunk_type", table_name="chunks")
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_index("ix_documents_source_path", table_name="documents")
    op.drop_table("documents")
    # La extensión `vector` se conserva: otras bases o esquemas pueden depender de ella.
