#!/usr/bin/env python3
"""Informe de los índices de `chunks`: tipo (btree/gin/hnsw), tamaño y uso (`idx_scan`, `last_idx_scan`).

    docker compose run --rm estimador-cag python scripts/report_index_sizes_s08.py

Un índice vectorial con `idx_scan = 0` suele indicar un operador o una expresión desalineados con el `ORDER BY`.
"""

from __future__ import annotations

import asyncio
import sys

from s08_common import format_table, session_scope
from sqlalchemy import text

REPORT_SQL = text(
    """
    SELECT i.indexrelname AS name,
           am.amname AS kind,
           pg_relation_size(i.indexrelid) AS bytes,
           pg_size_pretty(pg_relation_size(i.indexrelid)) AS size,
           i.idx_scan,
           i.last_idx_scan
    FROM pg_stat_user_indexes i
    JOIN pg_class c ON c.oid = i.indexrelid
    JOIN pg_am am ON am.oid = c.relam
    WHERE i.relname = 'chunks'
    ORDER BY bytes DESC
    """
)


async def main() -> int:
    async with session_scope() as session:
        rows = (await session.execute(REPORT_SQL)).all()
        table_size = (await session.execute(text("SELECT pg_size_pretty(pg_table_size('chunks'))"))).scalar_one()
        chunks = (await session.execute(text("SELECT count(*) FROM chunks"))).scalar_one()

    table = [
        [r.name, r.kind, r.size, r.idx_scan, r.last_idx_scan.strftime("%F %T") if r.last_idx_scan else "nunca"]
        for r in rows
    ]
    print(f"Tabla chunks: {chunks} filas · {table_size}\n")
    print(format_table(["Índice", "Tipo", "Tamaño", "idx_scan", "last_idx_scan"], table))
    sizes = {r.name: r.bytes for r in rows}
    full, half = sizes.get("chunks_embedding_idx"), sizes.get("chunks_embedding_halfvec_idx")
    if full and half:
        print(f"\nhalfvec / vector = {half / full:.0%} del tamaño")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
