#!/usr/bin/env python3
"""Mide la calidad de recuperación por CONFIGURACIÓN NOMBRADA (Sesión 10).

Ejecuta el golden set (`evals/golden_retrieval.json`) por el pipeline avanzado con cada configuración nombrada e imprime
la precision@k media (sobre las consultas), la latencia extremo a extremo media (sobre las ejecuciones medidas) y el
desglose de precision por consulta.

Las configuraciones son DATOS, no ramas de código: cada una es un `StageConfig` que activa o desactiva etapas concretas
(las líneas base A–D, y luego *decay* temporal, *routing*, transformación de consulta y el pipeline completo). Para
añadir una fila basta añadir un `NamedConfig`.

Notas de método:

* Se usa un umbral de distancia permisivo para que el top-k nunca lo recorte el suelo de relevancia: se compara la
  calidad del RANKING, no el *soft-fail*.
* Un chunk es relevante si su `source_id` (budget_id / transcript_id / doc_id) está en `relevant_source_ids` de la
  consulta (`relevant_budget_ids` se respeta en los golden sets antiguos). precision@k = aciertos / k.
* La latencia incluye el embedding de cada subconsulta y, en las filas con *routing* o transformación, las llamadas al
  LLM que esas técnicas añaden: ese sobrecoste ES el coste que pondera el compromiso.

Se ejecuta con el stack levantado, los TRES corpus ingestados y claves reales (`OPENAI_API_KEY`); el primer *rerank*
descarga los pesos del cross-encoder::

    docker compose exec estimador-cag python scripts/ingest_corpus.py
    docker compose exec estimador-cag python scripts/build_multi_index_corpus.py
    docker compose -f docker-compose.verify.yml run --rm --entrypoint python api-test scripts/eval_retrieval_s10.py

(en el segundo caso `api-test` necesita `DATABASE_URL` y `OPENAI_API_KEY` reales apuntando al stack).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from s08_common import Stopwatch, format_table, require_embedder  # importa antes que `app`

from app.config import get_settings
from app.foundation.llm.service import generate_from_messages
from app.foundation.persistence.database import SessionLocal
from app.generation.rag.retrieval.advanced_pipeline import AdvancedRetriever, StageConfig
from app.generation.rag.retrieval.collections import Collection
from app.generation.rag.retrieval.reranker import CrossEncoderReranker
from app.generation.rag.schemas import RetrievedChunk

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = ROOT / "evals" / "golden_retrieval.json"

# Sin suelo de relevancia efectivo: queremos un top-k completo para calificar el ranking.
NO_FLOOR_THRESHOLD = 2.0
# Muestras de latencia por (consulta, configuración): una de calentamiento descartada y N medidas.
MEASURED_RUNS = 3
# Solo presupuestos, para las líneas base A–D (comparables con la tabla del trabajo previo).
BUDGET_ONLY = [Collection.BUDGET]


@dataclass(frozen=True)
class NamedConfig:
    """Una configuración medida: etiqueta, interruptores de etapas y alcance del *routing*."""

    id: str
    label: str
    stages: StageConfig
    explicit: list[Collection] | None  # None = decide el router (multi-índice)


def stages(**overrides) -> StageConfig:
    """`StageConfig` con los valores por defecto del arnés (umbral permisivo, k=5)."""
    base = {
        "routing_enabled": False,
        "query_transform_enabled": False,
        "search_mode": "vector",
        "rerank": False,
        "temporal_decay_enabled": False,
        "top_k": 5,
        "distance_threshold": NO_FLOOR_THRESHOLD,
    }
    return StageConfig(**{**base, **overrides})


# Las configuraciones nombradas (DATOS). A–D reproducen las líneas base sobre presupuestos; E–H añaden las técnicas.
CONFIGS: tuple[NamedConfig, ...] = (
    NamedConfig("A", "Vector", stages(search_mode="vector"), BUDGET_ONLY),
    NamedConfig("B", "Hybrid", stages(search_mode="hybrid"), BUDGET_ONLY),
    NamedConfig("C", "Vector+Rerank", stages(search_mode="vector", rerank=True), BUDGET_ONLY),
    NamedConfig("D", "Hybrid+Rerank", stages(search_mode="hybrid", rerank=True), BUDGET_ONLY),
    NamedConfig(
        "E",
        "Hybrid+Rerank+Temporal",
        stages(search_mode="hybrid", rerank=True, temporal_decay_enabled=True),
        BUDGET_ONLY,
    ),
    NamedConfig("F", "Multi-index routing", stages(search_mode="hybrid", rerank=True, routing_enabled=True), None),
    NamedConfig(
        "G",
        "Query transform",
        stages(search_mode="hybrid", rerank=True, query_transform_enabled=True),
        BUDGET_ONLY,
    ),
    NamedConfig(
        "H",
        "Full pipeline",
        stages(
            search_mode="hybrid",
            rerank=True,
            routing_enabled=True,
            query_transform_enabled=True,
            temporal_decay_enabled=True,
        ),
        None,
    ),
)


def relevant_ids(query: dict) -> set[str]:
    """Ids de documento relevantes anotados (genéricos; `relevant_budget_ids` como respaldo)."""
    return set(query.get("relevant_source_ids") or query.get("relevant_budget_ids") or [])


def precision_at_k(chunks: Sequence[RetrievedChunk], relevant: set[str], k: int) -> float:
    """Fracción de los `k` primeros resultados cuyo documento de origen es realmente relevante."""
    hits = sum(1 for chunk in chunks[:k] if (chunk.source_id or chunk.budget_id) in relevant)
    return hits / k


@dataclass
class ConfigResult:
    precisions: list[float]
    latencies_ms: list[float]
    per_query: dict[str, float]
    empty: bool = False


async def evaluate(
    retriever: AdvancedRetriever,
    queries: list[dict],
    configs: Sequence[NamedConfig],
    *,
    k: int,
    reference_date: date,
    measured_runs: int = MEASURED_RUNS,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, ConfigResult]:
    """Ejecuta cada consulta por cada configuración: una pasada de calentamiento y `measured_runs` medidas."""
    results = {config.id: ConfigResult([], [], {}) for config in configs}
    for config in configs:
        if on_progress:
            on_progress(f"{config.id} {config.label}")
        bucket = results[config.id]
        for query in queries:

            async def run_once(query_text: str = query["query"], config: NamedConfig = config):
                outcome = await retriever.search(
                    query_text,
                    stages=config.stages,
                    reference_date=reference_date,
                    explicit_collections=config.explicit,
                )
                return outcome.chunks

            await run_once()  # calentamiento (descartado)
            last: list[RetrievedChunk] = []
            for _ in range(measured_runs):
                with Stopwatch() as watch:
                    last = await run_once()
                bucket.latencies_ms.append(watch.ms)
            bucket.empty = bucket.empty or not last
            precision = precision_at_k(last, relevant_ids(query), k)
            bucket.precisions.append(precision)
            bucket.per_query[query["id"]] = precision
    return results


def format_report(results: dict[str, ConfigResult], configs: Sequence[NamedConfig], queries: list[dict], k: int) -> str:
    """Tabla comparativa (una fila por configuración) y desglose de precision@k por consulta."""
    summary = format_table(
        ["Config", "Etapas", f"Precision@{k}", "Latencia (ms)"],
        [
            [
                config.id,
                config.label,
                f"{statistics.fmean(results[config.id].precisions):.2f}",
                f"{statistics.fmean(results[config.id].latencies_ms):.1f}",
            ]
            for config in configs
        ],
    )
    breakdown = format_table(
        ["Consulta", *(config.id for config in configs)],
        [
            [query["id"], *(f"{results[config.id].per_query[query['id']]:.2f}" for config in configs)]
            for query in queries
        ],
    )
    title = f"## Evaluación de recuperación — precision@{k} y latencia"
    return f"{title}\n\n{summary}\n\n### precision@{k} por consulta\n\n{breakdown}"


def select_configs(ids: Sequence[str] | None) -> tuple[NamedConfig, ...]:
    """Las configuraciones pedidas por id (todas si `ids` está vacío); un id desconocido es un error de uso."""
    if not ids:
        return CONFIGS
    by_id = {config.id: config for config in CONFIGS}
    unknown = [config_id for config_id in ids if config_id not in by_id]
    if unknown:
        raise SystemExit(f"ERROR: configuraciones desconocidas: {', '.join(unknown)} (disponibles: {', '.join(by_id)})")
    return tuple(by_id[config_id] for config_id in ids)


async def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="precision@k y latencia por configuración de recuperación.")
    parser.add_argument("--configs", nargs="*", help="Ids a medir (por defecto todos): A B C D E F G H.")
    parser.add_argument("--runs", type=int, default=MEASURED_RUNS, help="Ejecuciones medidas por consulta y config.")
    args = parser.parse_args(argv)
    configs = select_configs(args.configs)

    settings = get_settings()
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    queries, k = golden["queries"], int(golden.get("k", 5))

    reranker = CrossEncoderReranker(settings.reranker_model)
    retriever = AdvancedRetriever(
        SessionLocal,
        require_embedder(),
        generate=generate_from_messages,
        reranker=reranker,
        ef_search=settings.hnsw_ef_search,
    )
    if any(config.stages.rerank for config in configs):
        print("Calentando el cross-encoder (la primera carga descarga los pesos)...")
        await reranker.load()

    results = await evaluate(
        retriever,
        queries,
        configs,
        k=k,
        reference_date=date.today(),
        measured_runs=args.runs,
        on_progress=lambda label: print(f"Midiendo {label}...", file=sys.stderr),
    )
    print(format_report(results, configs, queries, k))
    if any(result.empty for result in results.values()):
        print(
            "\nAVISO: alguna configuración devolvió 0 chunks. ¿Están ingestadas las tres colecciones? Ejecuta "
            "scripts/ingest_corpus.py y scripts/build_multi_index_corpus.py.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
