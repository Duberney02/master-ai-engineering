"""Utilidades compartidas por los scripts `*_s08.py` de la Sesión 08 (indexación vectorial).

Hablan con PostgreSQL por la sesión async del proyecto (`app.foundation.persistence.database`) y con el embedder
existente: no crean motores ni clientes paralelos. Sin dependencias nuevas (ni `rich` ni `tabulate`).

Se ejecutan dentro de Docker, desde la raíz del repo::

    docker compose run --rm estimador-cag python scripts/<script>.py
"""

from __future__ import annotations

import statistics
import sys
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ClauseElement

# `python scripts/x.py` solo pone `scripts/` en sys.path: se añade la raíz del servicio para importar `app`, y los
# scripts importan este módulo ANTES que `app`. `query_examples` vive junto a este módulo.
SCRIPTS_DIR = Path(__file__).resolve().parent
for path in (str(SCRIPTS_DIR), str(SCRIPTS_DIR.parent)):
    if path not in sys.path:
        sys.path.insert(0, path)

from query_examples import QUERIES  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.foundation.persistence.database import SessionLocal  # noqa: E402
from app.generation.rag.embedding.embedder import OpenAIEmbedder  # noqa: E402

HALFVEC_INDEX = "chunks_embedding_halfvec_idx"
VECTOR_INDEX = "chunks_embedding_idx"
RECALL_TOLERANCE = 0.005
STAR = "★"


@dataclass(frozen=True)
class EmbeddedQuery:
    label: str
    text: str
    vector: list[float]


def require_embedder() -> OpenAIEmbedder:
    """El embedder del proyecto, o salida con un mensaje claro si falta la configuración (sin trazas)."""
    settings = get_settings()
    if not settings.database_url:
        sys.exit("ERROR: DATABASE_URL no está configurada (usa `docker compose run --rm estimador-cag`).")
    if not settings.openai_api_key:
        sys.exit("ERROR: OPENAI_API_KEY no está configurada: hace falta para embeber las consultas.")
    return OpenAIEmbedder()


async def embed_queries(embedder: OpenAIEmbedder | None = None) -> list[EmbeddedQuery]:
    """Embebe una sola vez las `QUERIES` de `query_examples.py`, fuera de cualquier tiempo medido."""
    embedder = embedder or require_embedder()
    vectors = await embedder.embed_texts([query for _, query in QUERIES])
    return [EmbeddedQuery(label, query, vector) for (label, query), vector in zip(QUERIES, vectors, strict=True)]


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Sesión async del proyecto; hace rollback al salir, así que cualquier `SET LOCAL` queda acotado."""
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()


def vector_literal(vector: Sequence[float]) -> str:
    """`[0.1,0.2,…]`, el literal de pgvector para pegarlo en `psql` (`'…'::vector`)."""
    return "[" + ",".join(f"{value:.8g}" for value in vector) + "]"


def truncate(value: str, width: int = 60) -> str:
    """Texto en una sola línea, recortado a `width` caracteres (con `…` si se recorta)."""
    flat = " ".join(value.split())
    return flat if len(flat) <= width else flat[: max(width - 1, 0)] + "…"


def format_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """Tabla de texto alineada (números a la derecha), sin dependencias."""
    cells = [[str(cell) for cell in row] for row in rows]
    widths = [max([len(str(header)), *(len(row[i]) for row in cells)]) for i, header in enumerate(headers)]
    numeric = [
        bool(rows) and all(isinstance(row[i], int | float) and not isinstance(row[i], bool) for row in rows)
        for i in range(len(headers))
    ]

    def line(values: Sequence[str]) -> str:
        return "  ".join(v.rjust(w) if num else v.ljust(w) for v, w, num in zip(values, widths, numeric, strict=True))

    rule = "  ".join("-" * w for w in widths)
    return "\n".join([line([str(h) for h in headers]), rule, *(line(row) for row in cells)])


class Stopwatch:
    """Cronómetro de contexto: `with Stopwatch() as watch: …; watch.ms`."""

    def __enter__(self) -> Stopwatch:
        self._start = time.perf_counter()
        self.ms = 0.0
        return self

    def __exit__(self, *exc: object) -> None:
        self.ms = (time.perf_counter() - self._start) * 1000


def latency_summary(samples_ms: Sequence[float]) -> str:
    """`media ± desviación` en ms (la desviación es 0 con una sola muestra)."""
    if not samples_ms:
        return "n/d"
    deviation = statistics.stdev(samples_ms) if len(samples_ms) > 1 else 0.0
    return f"{statistics.fmean(samples_ms):.2f} ± {deviation:.2f} ms"


def recall_at_k(found: Sequence[int], truth: Sequence[int], k: int = 5) -> float:
    """recall@k = |top-k del índice ∩ top-k real| / k."""
    return len(set(found[:k]) & set(truth[:k])) / k


def recommendation_labels(recalls: Sequence[float], tolerance: float = RECALL_TOLERANCE) -> list[str]:
    """`★` en el primer valor (el menor `ef_search`, si van en orden) cuyo recall está a ≤ `tolerance` del mejor."""
    if not recalls:
        return []
    threshold = max(recalls) - tolerance
    labels = [""] * len(recalls)
    labels[next(i for i, recall in enumerate(recalls) if recall >= threshold - 1e-12)] = STAR
    return labels


def render(statement: ClauseElement) -> str:
    """SQL con los parámetros incrustados (para `EXPLAIN`)."""
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


async def explain(session: AsyncSession, statement: ClauseElement) -> str:
    """Plan de ejecución (`EXPLAIN`, sin ejecutar) de un statement de SQLAlchemy."""
    rows = await session.execute(text(f"EXPLAIN {render(statement)}"))
    return "\n".join(rows.scalars())


def uses_index(plan: str, index: str) -> bool:
    return f"Index Scan using {index}" in plan
