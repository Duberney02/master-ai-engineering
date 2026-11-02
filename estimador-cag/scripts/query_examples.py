#!/usr/bin/env python3
"""Cinco consultas de ejemplo contra `POST /search` (sustituye a `scripts/compare.py` de la Sesión 7).

Con el stack levantado y el corpus ingestado (`scripts/ingest_corpus.py`)::

    docker compose exec estimador-cag python scripts/query_examples.py
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

import httpx

DEFAULT_API = os.getenv("ESTIMATOR_API_BASE_URL", "http://localhost:8000")
TOP_K = 5
PREVIEW_CHARS = 120

# (tipo de consulta, texto): cubren acierto directo, paráfrasis, otro dominio, ambigüedad y especificidad.
QUERIES: list[tuple[str, str]] = [
    ("Componente conocido", "REST API development with JWT authentication for financial sector"),
    (
        "Reformulación semántica",
        "secure backend service with token-based access control for banking applications",
    ),
    ("Dominio distinto", "mobile application for restaurant reservations"),
    ("Ambigua", "integration with external system"),
    ("Muy específica", "migration from monolith to microservices architecture using Kubernetes"),
]


def _preview(content: str) -> str:
    """Primeros ~120 caracteres del contenido en una sola línea."""
    return " ".join(content.split())[:PREVIEW_CHARS]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consultas de ejemplo de búsqueda semántica.")
    parser.add_argument("--api", default=DEFAULT_API, help="URL base de la API (por defecto ESTIMATOR_API_BASE_URL).")
    args = parser.parse_args(argv)

    with httpx.Client(base_url=args.api, timeout=60) as client:
        for number, (label, query) in enumerate(QUERIES, start=1):
            try:
                response = client.post("/search", json={"query": query, "k": TOP_K})
                response.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"ERROR en la consulta {number}: {type(exc).__name__}", file=sys.stderr)
                return 1
            body = response.json()
            print(f"\n[{number}] {label}: {query}")
            print(f"    k={body['k']} · search_time_ms={body['search_time_ms']}")
            for rank, hit in enumerate(body["results"], start=1):
                print(
                    f"    {rank}. chunk_id={hit['chunk_id']:<4} distance={hit['distance']:.4f} "
                    f"{hit['chunk_type']:<16} {_preview(hit['content'])}"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main())
