#!/usr/bin/env python3
"""Comprobación previa de la sesión 6.

Detecta los fallos habituales de entorno: dependencias que faltan, modelo spaCy español ausente,
corpus o catálogo inválidos, API caída o migraciones sin aplicar. Imprime ✅ / ❌ por comprobación y
termina con código distinto de 0 si alguna falla.

Uso (siempre dentro de Docker, con el stack levantado)::

    docker compose exec estimador-cag python scripts/preflight_s06.py

La URL de la API se toma de ``ESTIMATOR_API_BASE_URL`` (por defecto ``http://localhost:8000``).
"""
from __future__ import annotations

import asyncio
import importlib.metadata as importlib_metadata
import os
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

OK = "✅"
FAIL = "❌"

ROOT = Path(__file__).resolve().parent.parent
# Hace importable ``app`` cuando el script se ejecuta directamente desde ``scripts/``.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class Check:
    def __init__(self, name: str, fn: Callable[[], str | None]) -> None:
        self.name = name
        self._fn = fn

    def run(self) -> bool:
        try:
            detail = self._fn()
        except Exception as exc:  # noqa: BLE001
            print(f"{FAIL}  {self.name}: {type(exc).__name__}: {exc}")
            return False
        print(f"{OK}  {self.name}: {detail}" if detail else f"{OK}  {self.name}")
        return True


def check_python_version() -> str:
    major, minor, *_ = sys.version_info
    if (major, minor) < (3, 11):
        raise RuntimeError(f"Python 3.11+ required, found {major}.{minor}")
    return f"{major}.{minor}.{sys.version_info.micro}"


_MIN_VERSIONS = {
    "pandas": "2.2.0",
    "pandera": "0.20.0",
    "pyyaml": "6.0",
    "sqlalchemy": "2.0.0",
    "asyncpg": "0.29.0",
    "alembic": "1.13.0",
    "presidio-analyzer": "2.2.0",
    "spacy": "3.8.0",
    "faker": "24.0.0",
}


def _parse_version(s: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in s.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def check_packages() -> str:
    missing: list[str] = []
    too_old: list[str] = []
    for pkg, minimum in _MIN_VERSIONS.items():
        try:
            installed = importlib_metadata.version(pkg)
        except importlib_metadata.PackageNotFoundError:
            missing.append(pkg)
            continue
        if _parse_version(installed) < _parse_version(minimum):
            too_old.append(f"{pkg} {installed} < {minimum}")
    if missing or too_old:
        raise RuntimeError("missing=" + ",".join(missing) + " too_old=" + ",".join(too_old))
    return f"{len(_MIN_VERSIONS)} packages OK"


def check_spacy_model() -> str:
    import spacy

    from app.config import get_settings

    model = get_settings().presidio_spacy_model
    nlp = spacy.load(model)
    doc = nlp("Laura Fernández firmó el contrato.")
    persons = [e.text for e in doc.ents if e.label_ == "PER"]
    if "Laura Fernández" not in " ".join(persons):
        raise RuntimeError(f"{model} loaded but did NOT detect 'Laura Fernández' as PER — model may be corrupted")
    return f"{model} loaded; detected PER entities: {persons}"


def check_corpus_seed() -> str:
    seed = ROOT / "data" / "seed"
    budgets = list((seed / "budgets").glob("*.json"))
    transcripts = list((seed / "transcripts").glob("*.txt"))
    xlsx = list(seed.glob("*.xlsx"))
    if not budgets or not transcripts or not xlsx:
        raise RuntimeError(
            f"corpus incomplete: budgets={len(budgets)}, transcripts={len(transcripts)}, xlsx={len(xlsx)}"
        )
    return f"{len(budgets)} json + {len(transcripts)} txt + {len(xlsx)} xlsx"


def check_catalog() -> str:
    from app.ingestion.catalog import load_catalog

    catalog = load_catalog(ROOT / "data" / "catalog" / "catalog.yaml")
    return f"version {catalog.version}, {len(catalog.included_sources())} included"


def check_health_endpoint() -> str:
    base = os.environ.get("ESTIMATOR_API_BASE_URL", "http://localhost:8000").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=3) as r:
            return f"{base}/health -> {r.status}"
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"GET {base}/health failed — is the stack running? ({exc})") from exc


async def _table_names() -> set[str]:
    from sqlalchemy import inspect

    from app.persistence.database import create_engine_from_settings

    engine = create_engine_from_settings()
    try:
        async with engine.connect() as connection:
            return set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))
    finally:
        await engine.dispose()


def check_postgres() -> str:
    """Conecta a PostgreSQL y confirma que las migraciones de la ingesta están aplicadas."""
    tables = asyncio.run(_table_names())
    expected = {"pseudonym_mappings", "ingestion_jobs", "alembic_version"}
    missing = expected - tables
    if missing:
        raise RuntimeError(f"missing tables: {sorted(missing)}; run `python -m app.persistence.migrate`")
    return f"tables OK: {sorted(expected)}"


CHECKS = [
    Check("Python version", check_python_version),
    Check("Required packages", check_packages),
    Check("spaCy Spanish model", check_spacy_model),
    Check("Corpus seed present", check_corpus_seed),
    Check("Catalog validates", check_catalog),
    Check("Estimator /health", check_health_endpoint),
    Check("Postgres + migration", check_postgres),
]


def main() -> int:
    print("Pre-flight Sesión 06\n")
    failed = sum(1 for check in CHECKS if not check.run())
    print()
    if failed:
        print(f"{FAIL}  {failed} check(s) failed")
        return 1
    print(f"{OK}  All checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
