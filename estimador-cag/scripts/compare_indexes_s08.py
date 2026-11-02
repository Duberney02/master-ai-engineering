#!/usr/bin/env python3
"""Compara el índice HNSW `vector` con el `halfvec` sobre las 5 queries (sin borrar ninguno).

Cada índice se fuerza por la *expresión* del `ORDER BY` (`embedding <=> q` usa `chunks_embedding_idx`;
`CAST(embedding AS HALFVEC(1536)) <=> q` usa `chunks_embedding_halfvec_idx`) y se comprueba con `EXPLAIN`. Con
`enable_seqscan = off` el planner usa el índice aunque la tabla sea pequeña. Muestra top-5, overlap y latencias::

    docker compose run --rm estimador-cag python scripts/compare_indexes_s08.py
"""

from __future__ import annotations

import asyncio
import statistics
import sys

from s08_common import (
    HALFVEC_INDEX,
    VECTOR_INDEX,
    Stopwatch,
    embed_queries,
    explain,
    format_table,
    latency_summary,
    recall_at_k,
    require_embedder,
    session_scope,
    truncate,
    uses_index,
)
from sqlalchemy import select, text

# isort: split
from app.foundation.persistence.models import Chunk  # noqa: E402
from app.generation.rag.store.documents import search_statement  # noqa: E402

TOP_K = 5
WARMUPS = 1
MEASUREMENTS = 2


def vector_statement(vector: list[float], k: int):
    """Misma consulta pero sobre la columna `vector` sin castear: la usa solo `chunks_embedding_idx`."""
    distance = Chunk.embedding.cosine_distance(vector).label("distance")
    return select(Chunk.id, distance).where(Chunk.embedding.is_not(None)).order_by(distance).limit(k)


async def _run(session, statement) -> tuple[list[int], list[float]]:
    for _ in range(WARMUPS):
        await session.execute(statement)
    samples, ids = [], []
    for _ in range(MEASUREMENTS):
        with Stopwatch() as watch:
            ids = [row.id for row in (await session.execute(statement)).all()]
        samples.append(watch.ms)
    return ids, samples


async def main() -> int:
    queries = await embed_queries(require_embedder())
    async with session_scope() as session:
        names = await session.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'chunks'"))
        present = set(names.scalars())
        missing = [name for name in (VECTOR_INDEX, HALFVEC_INDEX) if name not in present]
        if missing:
            sys.exit(f"ERROR: falta(n) el/los índice(s) {', '.join(missing)}. Ejecuta `alembic upgrade head`.")
        await session.execute(text("SET LOCAL enable_seqscan = off"))

        rows, overlaps, vector_ms, halfvec_ms = [], [], [], []
        for number, query in enumerate(queries, start=1):
            full, half = vector_statement(query.vector, TOP_K), search_statement(query.vector, TOP_K)
            for statement, index in ((full, VECTOR_INDEX), (half, HALFVEC_INDEX)):
                if not uses_index(await explain(session, statement), index):
                    sys.exit(f"ERROR: el plan de la query {number} no usa {index} (expresión desalineada).")
            full_ids, full_samples = await _run(session, full)
            half_ids, half_samples = await _run(session, half)
            overlaps.append(recall_at_k(half_ids, full_ids, TOP_K))
            vector_ms.append(statistics.fmean(full_samples))
            halfvec_ms.append(statistics.fmean(half_samples))
            rows.append(
                [number, truncate(query.label, 22), str(full_ids), str(half_ids), f"{overlaps[-1]:.2f}",
                 latency_summary(full_samples), latency_summary(half_samples)]
            )

    print(format_table(["#", "Query", "Top-5 vector", "Top-5 halfvec", "Overlap", "Lat. vector", "Lat. halfvec"], rows))
    print(
        f"\nOverlap medio: {statistics.fmean(overlaps):.3f} · latencia media "
        f"vector {statistics.fmean(vector_ms):.2f} ms · halfvec {statistics.fmean(halfvec_ms):.2f} ms"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
