#!/usr/bin/env python3
"""Barrido de `hnsw.ef_search`: latencia frente a recall@5.

La verdad de fondo es el top-10 exacto (`SET LOCAL enable_indexscan = off`: búsqueda secuencial). Para cada valor de
`ef_search` se mide la latencia (1 calentamiento + 2 mediciones por query) y el
recall@5 = |top5 índice ∩ top5 real| / 5.
La medición fuerza el índice (`enable_seqscan = off`); la columna "Plan natural" dice qué plan elegiría el planner solo.
El ★ marca el menor valor cuyo recall esté a ≤ 0.005 del mejor::

    docker compose run --rm estimador-cag python scripts/sweep_ef_search_s08.py

Necesita el índice HNSW halfvec y un corpus lo bastante grande para que el planner lo use
(`insert_synthetic_chunks_s08.py 30000`).
"""

from __future__ import annotations

import asyncio
import statistics
import sys

from s08_common import (
    HALFVEC_INDEX,
    RECALL_TOLERANCE,
    Stopwatch,
    embed_queries,
    explain,
    format_table,
    recall_at_k,
    recommendation_labels,
    require_embedder,
    session_scope,
    uses_index,
)
from sqlalchemy import text

# isort: split
from app.generation.rag.store.documents import search_statement  # noqa: E402

EF_SEARCH_VALUES = [10, 20, 40, 80, 120, 200]
TRUTH_K = 10
RECALL_K = 5
WARMUPS = 1
MEASUREMENTS = 2


async def _ids(session, statement) -> list[int]:
    return [row.id for row in (await session.execute(statement)).all()]


async def main() -> int:
    queries = await embed_queries(require_embedder())
    async with session_scope() as session:
        total = (await session.execute(text("SELECT count(*) FROM chunks"))).scalar_one()
        found = await session.execute(text("SELECT 1 FROM pg_indexes WHERE indexname = :n"), {"n": HALFVEC_INDEX})
        if not found.first():
            sys.exit(f"ERROR: falta el índice {HALFVEC_INDEX}. Ejecuta `alembic upgrade head`.")

        # Verdad de fondo: sin index scan el planner recorre toda la tabla y ordena (resultado exacto).
        await session.execute(text("SET LOCAL enable_indexscan = off"))
        truth = [await _ids(session, search_statement(q.vector, TRUTH_K)) for q in queries]
        await session.rollback()  # descarta el SET LOCAL: a partir de aquí el planner puede usar el índice
        sample = search_statement(queries[0].vector, RECALL_K)

        rows: list[list[object]] = []
        recalls: list[float] = []
        for ef_search in EF_SEARCH_VALUES:
            await session.execute(text(f"SET LOCAL hnsw.ef_search = {ef_search}"))
            # Plan que elegiría el planner por sí solo: el coste del índice depende de ef_search y en tablas medianas
            # puede perder frente al Seq Scan. Se anota, y la medición fuerza el índice para medir HNSW, no el Seq Scan.
            natural = "Index" if uses_index(await explain(session, sample), HALFVEC_INDEX) else "Seq Scan"
            await session.execute(text("SET LOCAL enable_seqscan = off"))
            latencies: list[float] = []
            query_recalls: list[float] = []
            for query, expected in zip(queries, truth, strict=True):
                statement = search_statement(query.vector, RECALL_K)
                for _ in range(WARMUPS):
                    await session.execute(statement)
                samples = []
                for _ in range(MEASUREMENTS):
                    with Stopwatch() as watch:
                        found = await _ids(session, statement)
                    samples.append(watch.ms)
                latencies.append(statistics.fmean(samples))
                query_recalls.append(recall_at_k(found, expected, RECALL_K))
            recalls.append(statistics.fmean(query_recalls))
            rows.append([ef_search, round(statistics.fmean(latencies), 2), round(recalls[-1], 3), natural])
            await session.rollback()

    labels = recommendation_labels(recalls)
    table = [[*row, label] for row, label in zip(rows, labels, strict=True)]
    print(f"Chunks: {total} · {len(queries)} queries · verdad de fondo = top-{TRUTH_K} exacto\n")
    print(format_table(["ef_search", "Latencia media (ms)", f"recall@{RECALL_K}", "Plan natural", "★"], table))
    best = max(recalls)
    chosen = EF_SEARCH_VALUES[labels.index("★")]
    threshold = best - RECALL_TOLERANCE
    print(f"\n★ = menor ef_search con recall ≥ {threshold:.3f} (mejor {best:.3f} − {RECALL_TOLERANCE}) → {chosen}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
