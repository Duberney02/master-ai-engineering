"""Sesión 11: índices vectoriales HNSW halfvec en todas las colecciones.

La Sesión 10 dejó `transcript_chunks` y `technical_doc_chunks` sin índice vectorial (a escala de curso bastaba el *scan*
secuencial). Con la expansión incremental del corpus (`POST /embeddings/index/runs`) las tablas crecen, así que se les
da el MISMO índice que `chunks` tiene desde la migración `0003`: HNSW sobre `(embedding::halfvec(1536))` con
`halfvec_cosine_ops`, `m = 16` y `ef_construction = 128`. La expresión es la misma que usa la consulta de recuperación
(`models.halfvec_embedding()`); con otra, Postgres ignora el índice sin avisar. `chunks` ya tiene el suyo
(`chunks_embedding_halfvec_idx`) y no se toca.

Los chunks insertados después se indexan solos (HNSW es incremental): no hay que reconstruir nada al ampliar el corpus.

`CREATE INDEX CONCURRENTLY` no puede ejecutarse dentro de una transacción: de ahí el `autocommit_block()`, igual que la
`0003`. Un build concurrente que falla deja un índice `INVALID` que `IF NOT EXISTS` no repara: bórralo con `downgrade` o
reconstrúyelo con `REINDEX INDEX CONCURRENTLY`. Se omite fuera de PostgreSQL (pgvector solo existe allí).

Revision ID: 0006_hnsw_multi_index
Revises: 0005_multi_index_chunks
Create Date: 2026-11-23 18:00:00
"""
from collections.abc import Sequence

from alembic import op
from app.foundation.persistence.models import EMBEDDING_DIMENSIONS

revision: str = "0006_hnsw_multi_index"
down_revision: str | None = "0005_multi_index_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# tabla -> nombre del índice (mismo patrón que `chunks_embedding_halfvec_idx` de la Sesión 8).
HALFVEC_INDEXES = {
    "transcript_chunks": "transcript_chunks_embedding_halfvec_idx",
    "technical_doc_chunks": "technical_doc_chunks_embedding_halfvec_idx",
}
HNSW_PARAMS = "WITH (m = 16, ef_construction = 128)"


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgresql():
        return
    with op.get_context().autocommit_block():
        for table, index in HALFVEC_INDEXES.items():
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {index} ON {table} "
                f"USING hnsw ((embedding::halfvec({EMBEDDING_DIMENSIONS})) halfvec_cosine_ops) {HNSW_PARAMS}"
            )


def downgrade() -> None:
    if not _is_postgresql():
        return
    with op.get_context().autocommit_block():
        for index in reversed(list(HALFVEC_INDEXES.values())):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index}")
