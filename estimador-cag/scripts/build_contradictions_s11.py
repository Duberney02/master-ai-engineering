#!/usr/bin/env python3
"""Siembra precedentes HISTÓRICOS CONTRADICTORIOS para demostrar la síntesis de rangos (Sesión 11).

Un promedio de vecinos que se contradicen oculta la incertidumbre: «40 h» y «90 h» para la misma tarea dan «65 h», una
cifra que parece precisa y no lo es. Este script añade al corpus de tareas (`chunk_type="historical_task"`) pares de
proyectos que registran la MISMA tarea con esfuerzos muy distintos (alcance mínimo frente a alcance completo), de modo
que `POST /v1/estimate/tasks/hours` con la síntesis activa devuelva un `hours_range` además de la cifra puntual.

Es DETERMINISTA e IDEMPOTENTE: cada proyecto se ingesta con un `source_path` estable
(`data/contradictions_s11.json#<id>`) y `POST /embeddings/ingest` responde 409 a los ya ingestados, así que
ejecutarlo dos veces no duplica nada. Para retirarlo::

    DELETE FROM documents WHERE document_type = 'historical_task_contradiction';

Con el stack raíz levantado (`docker compose up -d --build`) y `OPENAI_API_KEY` real (embeddings)::

    docker compose exec estimador-cag python scripts/build_contradictions_s11.py --ingest
    docker compose exec estimador-cag python scripts/build_contradictions_s11.py --ingest   # 0 nuevos: idempotente

Solo generar el JSON, sin red::

    docker compose -f docker-compose.verify.yml run --rm --entrypoint python api-test \
        scripts/build_contradictions_s11.py --generate-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

DOCUMENT_TYPE = "historical_task_contradiction"
CHUNK_TYPE = "historical_task"
SOURCE_PREFIX = "data/contradictions_s11.json#"
DEFAULT_API = os.getenv("ESTIMATOR_API_BASE_URL", "http://localhost:8000")
TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class Contradiction:
    """Una tarea con dos precedentes: el de alcance mínimo y el de alcance completo."""

    key: str
    module: str
    name: str
    description: str
    low_hours: int
    high_hours: int
    sector: str
    low_scope: str
    high_scope: str


# Los nombres y descripciones coinciden con plantillas reales del corpus de tareas, para que la consulta de horas de
# esas tareas (`compose_task_search_text`) alcance a ambos precedentes. Los textos, en inglés como el resto del corpus.
CONTRADICTIONS: tuple[Contradiction, ...] = (
    Contradiction(
        key="OAUTH",
        module="Authentication & Access",
        name="OAuth2 / OIDC login",
        description="Authorization-code flow with refresh tokens and session handling.",
        low_hours=40,
        high_hours=90,
        sector="finance",
        low_scope="Single identity provider, no refresh-token rotation, no session revocation.",
        high_scope="Multiple identity providers, refresh-token rotation, device sessions and global revocation.",
    ),
    Contradiction(
        key="RBAC",
        module="Authentication & Access",
        name="Role-based access control",
        description="Roles, permissions and policy checks across the API.",
        low_hours=24,
        high_hours=72,
        sector="healthcare",
        low_scope="Three fixed roles checked in a decorator.",
        high_scope="Tenant-scoped custom roles, policy engine and a full audit trail.",
    ),
    Contradiction(
        key="KYC",
        module="Regulatory Reporting",
        name="KYC / AML onboarding",
        description="Identity verification and sanction-list screening.",
        low_hours=32,
        high_hours=96,
        sector="finance",
        low_scope="Manual review queue over uploaded documents.",
        high_scope="Automated document verification, sanctions screening and re-verification workflows.",
    ),
)


def _project(case: Contradiction, variant: str, hours: int, scope: str, year: int) -> dict:
    """Un `Budget` de una sola tarea (un chunk `historical_task`) con el esfuerzo del precedente."""
    return {
        "budget_id": f"CONTRA-{case.key}-{variant}",
        "client_metadata": {"name": f"Contradiction Demo {variant.title()}", "sector": case.sector, "country": "ES"},
        "project_summary": f"{case.name}: {scope}",
        "main_technology": "python_fastapi",
        "year": year,
        "total_estimated_hours": hours,
        "components": [
            {
                "component_id": f"{case.key}-001",
                "name": case.name,
                "description": case.description,
                "module": case.module,
                "tech_stack": ["python", "postgresql"],
                "estimated_hours": hours,
                "complexity": "high" if variant == "HIGH" else "low",
                "dependencies": [],
            }
        ],
    }


def generate_corpus() -> list[dict]:
    """Dos proyectos por contradicción (bajo y alto); sin aleatoriedad: la salida es siempre la misma."""
    corpus: list[dict] = []
    for case in CONTRADICTIONS:
        corpus.append(_project(case, "LOW", case.low_hours, case.low_scope, 2023))
        corpus.append(_project(case, "HIGH", case.high_hours, case.high_scope, 2024))
    return corpus


def ingest_body(project: dict) -> dict:
    return {
        "source_path": f"{SOURCE_PREFIX}{project['budget_id']}",
        "document_type": DOCUMENT_TYPE,
        "chunk_type": CHUNK_TYPE,
        "content": project,
    }


def ingest_corpus(corpus: list[dict], client: httpx.Client) -> tuple[int, int]:
    """Un documento por proyecto; 409 = ya ingestado (se omite). Devuelve `(creados, omitidos)`."""
    created = skipped = 0
    for project in corpus:
        response = client.post("/embeddings/ingest", json=ingest_body(project))
        if response.status_code == 200:
            created += 1
        elif response.status_code == 409:
            skipped += 1
        else:
            raise RuntimeError(f"{project['budget_id']}: HTTP {response.status_code}")
    return created, skipped


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Siembra precedentes contradictorios para la síntesis de rangos.")
    parser.add_argument("--api", default=DEFAULT_API, help="URL base de la API (por defecto ESTIMATOR_API_BASE_URL).")
    parser.add_argument("--out", type=Path, default=None, help="Ruta donde escribir el JSON generado.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--generate-only", action="store_true", help="Generar (y escribir con --out), sin ingestar.")
    mode.add_argument("--ingest", action="store_true", help="Generar e ingestar.")
    args = parser.parse_args(argv)

    corpus = generate_corpus()
    print(f"Precedentes contradictorios: {len(corpus)} proyectos ({len(CONTRADICTIONS)} tareas × 2 alcances).")
    for case in CONTRADICTIONS:
        print(f"  - {case.name}: {case.low_hours} h frente a {case.high_hours} h")
    if args.out:
        args.out.write_text(json.dumps(corpus, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Escrito en {args.out}.")
    if not args.ingest:
        print("(solo generación; usa --ingest para cargarlo en pgvector)")
        return 0

    try:
        with httpx.Client(base_url=args.api, timeout=TIMEOUT_SECONDS) as client:
            created, skipped = ingest_corpus(corpus, client)
    except (httpx.HTTPError, RuntimeError) as exc:
        print(f"ERROR al ingestar: {exc}", file=sys.stderr)
        return 1
    print(f"{created} ingestados, {skipped} ya presentes (chunk_type={CHUNK_TYPE}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
