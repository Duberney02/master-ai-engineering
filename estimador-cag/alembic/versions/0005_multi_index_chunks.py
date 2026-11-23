"""Sesión 10: tablas de chunks de transcripciones y documentación técnica (multi-índice).

El corpus es heterogéneo y cada colección tiene su propio esquema de metadatos (transcripciones: participantes y fecha
de reunión; documentación: versión), así que cada una vive en su tabla en vez de un único `chunks` donde el tipo
dominante inunda el top-k. `chunks` NO se renombra: sigue siendo la colección `budget` y conserva su contrato con
`POST /search` y su índice `chunks_embedding_halfvec_idx`.

Las tablas nuevas tienen las mismas columnas estructurales que `chunks` (FK a `documents` con `ON DELETE CASCADE`,
`chunk_type`, `content`, `embedding vector(1536)`, `metadata` JSONB, `created_at`, `content_tsv` generada) y sus
índices GIN sobre `metadata` y `content_tsv`. Sin índice HNSW a propósito: lo añade la Sesión 11; a escala de curso
basta el *scan* secuencial.

Revision ID: 0005_multi_index_chunks
Revises: 0004_content_tsv
Create Date: 2026-11-23 10:05:00
"""
from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_multi_index_chunks"
down_revision: str | None = "0004_content_tsv"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FTS_REGCONFIG = "english"
NEW_COLLECTIONS = ("transcript_chunks", "technical_doc_chunks")
EMPTY_JSON = sa.text("'{}'::jsonb")


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _create_chunk_table(table: str) -> None:
    op.create_table(
        table,
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
    op.execute(
        f"ALTER TABLE {table} ADD COLUMN content_tsv tsvector "
        f"GENERATED ALWAYS AS (to_tsvector('{FTS_REGCONFIG}', content)) STORED"
    )
    op.create_index(f"ix_{table}_document_id", table, ["document_id"])
    op.create_index(f"ix_{table}_chunk_type", table, ["chunk_type"])
    op.create_index(f"ix_{table}_metadata_gin", table, ["metadata"], postgresql_using="gin")
    op.create_index(f"ix_{table}_content_tsv", table, ["content_tsv"], postgresql_using="gin")


def _drop_chunk_table(table: str) -> None:
    op.drop_index(f"ix_{table}_content_tsv", table_name=table)
    op.drop_index(f"ix_{table}_metadata_gin", table_name=table)
    op.drop_index(f"ix_{table}_chunk_type", table_name=table)
    op.drop_index(f"ix_{table}_document_id", table_name=table)
    op.drop_table(table)


def upgrade() -> None:
    if not _is_postgresql():
        return
    for table in NEW_COLLECTIONS:
        _create_chunk_table(table)


def downgrade() -> None:
    if not _is_postgresql():
        return
    for table in reversed(NEW_COLLECTIONS):
        _drop_chunk_table(table)
