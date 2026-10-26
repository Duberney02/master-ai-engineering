#!/usr/bin/env python3
"""Compara estrategias de chunking sobre el corpus de presupuestos: estadísticas, top-k por consulta y coste.

Dentro del contenedor (monta ``scripts/`` y ``data/``)::

    docker compose exec estimador-cag python scripts/compare_chunkers.py --show-stats
    docker compose exec estimador-cag python scripts/compare_chunkers.py --strategies all --queries all \\
        --show-stats --show-top-k 3 --show-cost --output /tmp/informe.md

Sin ``--strategies`` solo se ejecutan las estrategias gratuitas (``free``). Las de pago (semantic, propositional,
contextual_retrieval) llaman a un LLM o a embeddings durante el chunking: pídelas por nombre o con ``all``.
Las estadísticas de las gratuitas no necesitan ninguna clave; las consultas sí (OPENAI_API_KEY).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Hace importable ``app`` cuando el script se ejecuta directamente desde ``scripts/``.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.generation.rag.analysis.comparison import ChunkingComparator, ChunkingStats, QueryResult  # noqa: E402
from app.generation.rag.chunking.registry import (  # noqa: E402
    ALL_STRATEGIES,
    FREE_STRATEGIES,
    StrategyUnavailableError,
    UnknownStrategyError,
    build_chunkers,
)
from app.generation.rag.embedding.embedder import OpenAIEmbedder  # noqa: E402
from app.generation.rag.schemas import Budget  # noqa: E402

DATA = ROOT / "data"
DEFAULT_CORPUS = (DATA / "budgets_sample.json", DATA / "budgets_stress_cases.json")
QUERIES_FILE = DATA / "test_queries.json"


def load_budgets(paths: Sequence[Path], limit: int | None = None) -> list[Budget]:
    budgets = [Budget.model_validate(item) for path in paths for item in json.loads(path.read_text(encoding="utf-8"))]
    return budgets[:limit] if limit else budgets


def select_strategies(value: str) -> list[str]:
    if value == "free":
        return list(FREE_STRATEGIES)
    if value == "all":
        return list(ALL_STRATEGIES)
    return [name.strip() for name in value.split(",") if name.strip()]


def select_queries(value: str, extra: Sequence[str]) -> list[str]:
    """`all`, índices (base 1) separados por comas sobre test_queries.json, o vacío; más las de --query."""
    available = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))
    if value == "all":
        chosen = list(available)
    elif value:
        chosen = [available[int(i) - 1] for i in value.split(",")]
    else:
        chosen = []
    return [*chosen, *extra]


def stats_table(stats: dict[str, ChunkingStats], show_cost: bool) -> str:
    head = "| strategy | chunks | min | p50 | p95 | max | huérfanos (<20) | obesos (>800) | segundos |"
    sep = "|---|---:|---:|---:|---:|---:|---:|---:|---:|"
    if show_cost:
        head += " llamadas extra | coste USD |"
        sep += "---:|---:|"
    rows = []
    for name, s in stats.items():
        d = s.token_distribution
        row = (
            f"| {name} | {s.n_chunks} | {d.min} | {d.p50} | {d.p95} | {d.max} | {s.n_orphan_chunks} "
            f"| {s.n_obese_chunks} | {s.ingestion_seconds:.2f} |"
        )
        if show_cost:
            row += f" {s.extra_api_calls} | {s.ingestion_cost_usd:.6f} |"
        rows.append(row)
    return "\n".join([head, sep, *rows])


async def run(args: argparse.Namespace) -> str:
    settings = get_settings()
    budgets = load_budgets(args.corpus, args.limit_budgets)
    queries = select_queries(args.queries, args.query)
    dimensions = [int(d) for d in args.dimensions.split(",")] if args.dimensions else [settings.embedding_dimensions]
    names = select_strategies(args.strategies)

    embedder = OpenAIEmbedder(dimensions=dimensions[0])
    chunkers = build_chunkers(names, settings, embedder)
    comparator = ChunkingComparator(chunkers, embedder)

    title = "# Comparación de estrategias de chunking"
    out = [f"{title}\n\nCorpus: {len(budgets)} presupuestos · estrategias: {', '.join(names)}\n"]
    if args.show_stats or args.show_cost:
        out.append(
            "## Estadísticos por estrategia\n\n" + stats_table(await comparator.compute_stats(budgets), args.show_cost)
        )

    if queries and args.show_top_k:
        for dim in dimensions:
            comparator.use_embedder(OpenAIEmbedder(dimensions=dim))
            results = await comparator.run_queries(budgets, queries, args.show_top_k)
            out.append(f"## Top-{args.show_top_k} por consulta (dimensión {dim})")
            for query in queries:
                out.append(f"### {query}")
                for name, per_query in results.items():
                    out.append(
                        await _describe(comparator, budgets, name, next(r for r in per_query if r.query == query), args)
                    )
    return "\n\n".join(out) + "\n"


async def _describe(
    comparator: ChunkingComparator, budgets: list[Budget], name: str, result: QueryResult, args: argparse.Namespace
) -> str:
    hits = " · ".join(f"{hit.chunk_id} ({hit.cosine:.3f})" for hit in result.top_k)
    line = f"- **{name}**: {hits}"
    if args.resolve_parents:
        chunks = {chunk.chunk_id: chunk for chunk in await comparator.chunks_of(budgets, name)}
        for hit in result.top_k:
            if hit.parent_chunk_id and hit.parent_chunk_id in chunks:
                parent = chunks[hit.parent_chunk_id]
                line += f"\n  - padre de {hit.chunk_id}: {parent.chunk_id} ({len(parent.text)} caracteres)"
    return line


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compara estrategias de chunking.")
    parser.add_argument("--strategies", default="free", help="'free' (por defecto), 'all' o lista separada por comas.")
    parser.add_argument("--queries", default="", help="'all', índices (base 1) separados por comas, o vacío.")
    parser.add_argument("--query", action="append", default=[], help="Consulta adicional (repetible).")
    parser.add_argument("--show-stats", action="store_true", help="Muestra los estadísticos por estrategia.")
    parser.add_argument(
        "--show-top-k", type=int, default=0, metavar="N", help="Muestra los N mejores chunks por consulta."
    )
    parser.add_argument(
        "--show-cost", action="store_true", help="Añade llamadas extra y coste a la tabla de estadísticos."
    )
    parser.add_argument("--output", type=Path, default=None, help="Escribe además el informe en este archivo Markdown.")
    parser.add_argument("--limit-budgets", type=int, default=None, help="Usa solo los N primeros presupuestos.")
    parser.add_argument(
        "--resolve-parents", action="store_true", help="En la jerárquica, indica el padre de cada hijo."
    )
    parser.add_argument("--dimensions", default="", help="Dimensiones de embedding a comparar, p. ej. 1536,768.")
    parser.add_argument(
        "--corpus", type=Path, nargs="+", default=list(DEFAULT_CORPUS), help="Archivos JSON de presupuestos."
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = asyncio.run(run(args))
    except UnknownStrategyError as exc:
        print(
            f"ERROR: estrategia desconocida: {exc.args[0]}. Disponibles: {', '.join(ALL_STRATEGIES)}", file=sys.stderr
        )
        return 2
    except StrategyUnavailableError as exc:
        print(f"ERROR: {exc.reason}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(report)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"Informe escrito en {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
