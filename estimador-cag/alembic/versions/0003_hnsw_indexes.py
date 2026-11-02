"""Sesión 8 (refinada): índices vectoriales HNSW sobre `chunks.embedding`.

* `chunks_embedding_halfvec_idx`: HNSW sobre `embedding::halfvec(1536)` (`halfvec_cosine_ops`). Es el que usa `/search`;
  ocupa ≈50 % del índice `vector` con un recall casi idéntico. La columna sigue siendo `vector(1536)`.
* `chunks_embedding_idx`: HNSW sobre `embedding` (`vector_cosine_ops`), solo para comparar tamaños y overlap.

Se crean con `CREATE INDEX CONCURRENTLY` (no bloquea escrituras), que no puede ejecutarse dentro de una transacción:
de ahí el `autocommit_block()`. Si un build concurrente falla deja un índice `INVALID`; `IF NOT EXISTS` no lo
repara, hay que borrarlo (`downgrade`) o reconstruirlo (`REINDEX INDEX CONCURRENTLY`).

Revision ID: 0003_hnsw_indexes
Revises: 0002_pgvector_documents_chunks
Create Date: 2026-11-02 12:00:00
"""
from collections.abc import Sequence

from alembic import op
from app.foundation.persistence.models import EMBEDDING_DIMENSIONS

revision: str = "0003_hnsw_indexes"
down_revision: str | None = "0002_pgvector_documents_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HALFVEC_INDEX = "chunks_embedding_halfvec_idx"
VECTOR_INDEX = "chunks_embedding_idx"
HNSW_PARAMS = "WITH (m = 16, ef_construction = 128)"


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgresql():  # pgvector solo existe en PostgreSQL
        return
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {HALFVEC_INDEX} ON chunks "
            f"USING hnsw ((embedding::halfvec({EMBEDDING_DIMENSIONS})) halfvec_cosine_ops) {HNSW_PARAMS}"
        )
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {VECTOR_INDEX} ON chunks "
            f"USING hnsw (embedding vector_cosine_ops) {HNSW_PARAMS}"
        )


def downgrade() -> None:
    if not _is_postgresql():
        return
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {VECTOR_INDEX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {HALFVEC_INDEX}")
