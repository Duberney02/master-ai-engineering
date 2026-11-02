#!/usr/bin/env python3
"""Ingesta el corpus de ejemplo (`data/budgets_sample.json`) con `POST /embeddings/ingest`, un presupuesto cada vez.

Cada presupuesto se guarda con `source_path = "data/budgets_sample.json#<budget_id>"`; los ya ingestados (409) se
omiten, de modo que el script es idempotente. Con el stack levantado (`docker compose up -d`)::

    docker compose exec estimador-cag python scripts/ingest_corpus.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = ROOT / "data" / "budgets_sample.json"
DEFAULT_API = os.getenv("ESTIMATOR_API_BASE_URL", "http://localhost:8000")
# Cada solicitud embebe los chunks de un presupuesto: tarda unos segundos.
TIMEOUT_SECONDS = 120


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingesta los presupuestos de ejemplo en PostgreSQL + pgvector.")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS, help="JSON con una lista de presupuestos.")
    parser.add_argument("--api", default=DEFAULT_API, help="URL base de la API (por defecto ESTIMATOR_API_BASE_URL).")
    args = parser.parse_args(argv)

    budgets = json.loads(args.corpus.read_text(encoding="utf-8"))
    created = skipped = failed = chunks = 0
    with httpx.Client(base_url=args.api, timeout=TIMEOUT_SECONDS) as client:
        for budget in budgets:
            source_path = f"data/{args.corpus.name}#{budget['budget_id']}"
            body = {"source_path": source_path, "document_type": "historical_budget", "content": budget}
            try:
                response = client.post("/embeddings/ingest", json=body)
            except httpx.HTTPError as exc:
                print(f"ERROR {source_path}: {type(exc).__name__}", file=sys.stderr)
                return 1
            if response.status_code == 200:
                created += 1
                chunks += response.json()["chunks_created"]
                print(f"OK    {source_path}: {response.json()['chunks_created']} chunks")
            elif response.status_code == 409:
                skipped += 1
                print(f"SKIP  {source_path}: ya ingestado (document_id={response.json()['document_id']})")
            else:
                failed += 1
                print(f"ERROR {source_path}: HTTP {response.status_code}", file=sys.stderr)

    print(f"Presupuestos creados: {created} ({chunks} chunks) · omitidos: {skipped} · con error: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
