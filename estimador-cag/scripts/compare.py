#!/usr/bin/env python3
"""Compara dos textos por similitud coseno entre sus embeddings (text-embedding-3-small).

Dentro del contenedor::

    docker compose exec estimador-cag python scripts/compare.py --text-a "..." --text-b "..."

Fuera del contenedor (Python 3.11+, dependencias instaladas y OPENAI_API_KEY en .env)::

    uv run python scripts/compare.py --text-a "..." --text-b "..."
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Hace importable ``app`` cuando el script se ejecuta directamente desde ``scripts/``.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.generation.rag.analysis.similarity import cosine_similarity  # noqa: E402
from app.generation.rag.embedding.embedder import OpenAIEmbedder  # noqa: E402


async def _embed_pair(text_a: str, text_b: str) -> float:
    vector_a, vector_b = await OpenAIEmbedder().embed_texts([text_a, text_b])
    return cosine_similarity(vector_a, vector_b)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Similitud coseno entre los embeddings de dos textos.")
    parser.add_argument("--text-a", required=True, help="Primer texto.")
    parser.add_argument("--text-b", required=True, help="Segundo texto.")
    args = parser.parse_args(argv)

    try:
        similarity = asyncio.run(_embed_pair(args.text_a, args.text_b))
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Text A: {args.text_a}")
    print(f"Text B: {args.text_b}")
    print(f"Cosine similarity: {similarity:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
