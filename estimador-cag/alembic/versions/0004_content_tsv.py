"""Sesión 10: columna léxica `content_tsv` (rama léxica de la búsqueda híbrida) con índice GIN en `chunks`.

`content_tsv` es una columna generada (`GENERATED ALWAYS … STORED`): PostgreSQL recalcula el `tsvector` en cada
inserción o cambio de `content`, así que no hay *trigger* que mantener ni forma de que el índice léxico se desfase
del texto que indexa.

Configuración de texto: `english`. El corpus de ejemplo (`data/budgets_sample.json`, `data/task_corpus.json`) está en
inglés; con él, el stemming y las *stop-words* ingleses son los que mejoran el recall léxico. Cambiarla a `spanish`
solo exige cambiar la cadena en dos sitios (esta migración y `FTS_REGCONFIG` en `models.py`, que usa la consulta).

Revision ID: 0004_content_tsv
Revises: 0003_hnsw_indexes
Create Date: 2026-11-23 10:00:00
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0004_content_tsv"
down_revision: str | None = "0003_hnsw_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FTS_REGCONFIG = "english"


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgresql():  # `tsvector` y GIN solo existen en PostgreSQL
        return
    # DDL en bruto: Alembic no tiene un ayudante de primera clase para un tsvector generado.
    op.execute(
        "ALTER TABLE chunks ADD COLUMN content_tsv tsvector "
        f"GENERATED ALWAYS AS (to_tsvector('{FTS_REGCONFIG}', content)) STORED"
    )
    op.create_index("ix_chunks_content_tsv", "chunks", ["content_tsv"], postgresql_using="gin")


def downgrade() -> None:
    if not _is_postgresql():
        return
    op.drop_index("ix_chunks_content_tsv", table_name="chunks")
    op.drop_column("chunks", "content_tsv")
