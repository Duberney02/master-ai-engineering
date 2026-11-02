#!/usr/bin/env python3
"""Latencia SQL de las 5 queries de `query_examples.py` (1 calentamiento + 2 mediciones por query).

Se ejecuta antes y después de crear el índice HNSW (`alembic upgrade head`) para ver la diferencia. Mide solo la
consulta SQL (los embeddings se calculan una vez, fuera de los tiempos) con la misma sentencia que usa `/search`::

    docker compose run --rm estimador-cag python scripts/measure_baseline_s08.py

Al final imprime el literal vector de la primera query, para pegarlo en `psql` (`'…'::vector`).
"""

from __future__ import annotations

import asyncio
import statistics
import sys

from s08_common import (
    HALFVEC_INDEX,
    Stopwatch,
    embed_queries,
    explain,
    format_table,
    latency_summary,
    require_embedder,
    session_scope,
    truncate,
    uses_index,
    vector_literal,
)
from sqlalchemy import text

# isort: split
from app.generation.rag.store.documents import search_statement  # noqa: E402

TOP_K = 5
WARMUPS = 1
MEASUREMENTS = 2


async def main() -> int:
    queries = await embed_queries(require_embedder())
    rows: list[list[object]] = []
    means: list[float] = []
    async with session_scope() as session:
        total = (await session.execute(text("SELECT count(*) FROM chunks"))).scalar_one()
        for number, query in enumerate(queries, start=1):
            statement = search_statement(query.vector, TOP_K)
            for _ in range(WARMUPS):
                await session.execute(statement)
            samples: list[float] = []
            for _ in range(MEASUREMENTS):
                with Stopwatch() as watch:
                    result = (await session.execute(statement)).all()
                samples.append(watch.ms)
            means.append(statistics.fmean(samples))
            rows.append([number, truncate(query.label, 24), len(result), latency_summary(samples)])
        plan = await explain(session, search_statement(queries[0].vector, TOP_K))

    print(f"Chunks en la tabla: {total} · {WARMUPS} calentamiento + {MEASUREMENTS} mediciones por query\n")
    print(format_table(["#", "Query", "Filas", "Latencia SQL"], rows))
    print(f"\nMedia de las {len(queries)} queries: {statistics.fmean(means):.2f} ms")
    kind = "Index Scan (HNSW halfvec)" if uses_index(plan, HALFVEC_INDEX) else "sin índice (Seq Scan)"
    print(f"Plan de la query 1: {kind}")
    print("\nLiteral vector de la query 1 (para psql, `'…'::vector`):")
    print(vector_literal(queries[0].vector))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
