#!/usr/bin/env python3
"""Compara dos textos por similitud coseno entre sus embeddings (text-embedding-3-small).

Dentro del contenedor::

    docker compose exec estimador-cag python scripts/compare.py --text-a "..." --text-b "..."

Fuera del contenedor (Python 3.11+, dependencias instaladas y OPENAI_API_KEY en .env)::

    uv run python scripts/compare.py --text-a "..." --text-b "..."
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Hace importable ``app`` cuando el script se ejecuta directamente desde ``scripts/``.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.embedding_pipeline.embedder import OpenAIEmbedder  # noqa: E402


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """dot(a, b) / (norm(a) * norm(b)), solo con la biblioteca estándar."""
    if len(a) != len(b):
        raise ValueError(f"vectors must have the same dimension ({len(a)} != {len(b)})")
    dot = math.fsum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(math.fsum(x * x for x in a))
    norm_b = math.sqrt(math.fsum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        raise ValueError("cosine similarity is undefined for a zero-norm vector")
    return dot / (norm_a * norm_b)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Similitud coseno entre los embeddings de dos textos.")
    parser.add_argument("--text-a", required=True, help="Primer texto.")
    parser.add_argument("--text-b", required=True, help="Segundo texto.")
    args = parser.parse_args(argv)

    embedder = OpenAIEmbedder()
    try:
        vector_a = embedder.embed_one(args.text_a)
        vector_b = embedder.embed_one(args.text_b)
        similarity = cosine_similarity(vector_a, vector_b)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Text A: {args.text_a}")
    print(f"Text B: {args.text_b}")
    print(f"Cosine similarity: {similarity:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
