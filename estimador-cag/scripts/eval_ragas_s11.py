#!/usr/bin/env python3
"""Recolecta muestras de generación y fija la línea base RAGAS (Sesión 11).

Corre el golden set (`evals/golden_generation_s11.json`) por el pipeline RAG REAL, etapa a etapa (reformulación →
recuperación → ensamblado → generación → informe de citas → gate de alucinaciones), y guarda por consulta lo que RAGAS
necesita: la petición (`user_input`), la estimación renderizada como texto (`response`), los chunks que vio el modelo
(`retrieved_contexts`) y la respuesta de referencia experta (`reference`). Además de las muestras guarda las
comprobaciones propias del servicio: citas colgantes y líneas `degraded`.

* `--collect-only`: escribe las muestras (`evals/ragas_samples_s11.json`) y termina; no llama al juez de RAGAS. Es la
  fase que necesita el stack; la puntuación (`score_ragas_s11.py`) solo necesita `ragas` y una clave de LLM.
* Sin flags: recolecta y puntúa con las cuatro métricas e imprime la tabla.
* `--write-baseline`: además versiona la línea base (`evals/ragas_baseline_s11.json` y su informe `.md`), la referencia
  contra la que `eval_generation_s11.py --gate` detecta regresiones.

Se ejecuta con el stack levantado, los corpus ingestados y claves REALES (nunca desde `pytest`)::

    docker compose exec estimador-cag python scripts/ingest_corpus.py
    docker compose exec estimador-cag python scripts/build_task_corpus.py --ingest
    docker compose -f docker-compose.verify.yml run --rm --entrypoint python api-test \
        scripts/eval_ragas_s11.py --collect-only
    docker compose -f docker-compose.verify.yml run --rm --entrypoint python api-test \
        scripts/eval_ragas_s11.py --write-baseline

(`api-test` necesita `DATABASE_URL` y `OPENAI_API_KEY` reales apuntando al stack.)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# `python scripts/x.py` solo pone `scripts/` en sys.path: se añade la raíz del servicio para importar `app`.
for path in (str(ROOT / "scripts"), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

GOLDEN_PATH = ROOT / "evals" / "golden_generation_s11.json"
SAMPLES_PATH = ROOT / "evals" / "ragas_samples_s11.json"
BASELINE_PATH = ROOT / "evals" / "ragas_baseline_s11.json"
REPORT_PATH = ROOT / "evals" / "ragas_baseline_s11.md"
METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")


@dataclass
class Collected:
    """Muestras RAGAS y las comprobaciones propias por consulta."""

    samples: list[dict] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)

    @property
    def dangling_citations(self) -> int:
        return sum(len(check["dangling_citations"]) for check in self.checks)

    @property
    def degraded_lines(self) -> int:
        return sum(check["degraded_lines"] for check in self.checks)


def load_golden(path: Path = GOLDEN_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["queries"]


def render_answer(estimate) -> str:
    """La estimación como texto plano: lo que RAGAS evalúa como `response`."""
    if estimate.confidence == "insufficient":
        return f"Contexto insuficiente: {estimate.insufficient_context_explanation or estimate.reasoning}"
    lines = [f"Confianza: {estimate.confidence}. {estimate.reasoning}"]
    if estimate.total_engineer_days is not None:
        lines.append(f"Total: {estimate.total_engineer_days:g} jornadas ({estimate.total_engineer_days * 8:g} horas).")
    for module in estimate.modules:
        lines.append(f"Módulo {module.name}:")
        for task in module.tasks:
            if task.grounded:
                days = f"{task.engineer_days:g} jornadas ({(task.engineer_days or 0) * 8:g} h)"
                evidence = "; ".join(source.evidence for source in task.sources)
                lines.append(f"- {task.name}: {days}. Evidencia: {evidence}")
            else:
                lines.append(f"- {task.name}: sin datos históricos que lo respalden.")
    return "\n".join(lines)


async def collect_one(estimator, entry: dict, *, use_judge: bool, with_reference: bool) -> tuple[dict, dict]:
    """Una consulta por el pipeline por etapas; devuelve `(muestra RAGAS, comprobaciones)`."""
    from app.generation.rag.estimator import insufficient_estimate, sector_filter
    from app.generation.rag.retriever import RetrievalFilters

    transcript = entry["transcript"]
    reformulation = await estimator.reformulate(transcript)
    toggles = await estimator.retrieval_toggles()
    retrieval = await estimator.retrieve(
        reformulation.search_text, filters=RetrievalFilters(sectors=sector_filter(reformulation.query))
    )
    if retrieval.low_confidence:
        estimate, kept = insufficient_estimate(), []
    else:
        assembled = estimator.assemble(retrieval.chunks, toggles=toggles)
        kept = assembled.kept_chunks
        estimate = await estimator.generate(assembled.context_block, reformulation.query)

    citations = estimator.citation_report(estimate, kept)
    gate = await estimator.verify(estimate, kept, use_judge=use_judge)
    sample = {
        "id": entry["id"],
        "user_input": transcript,
        "response": render_answer(estimate),
        "retrieved_contexts": [chunk.content for chunk in kept],
        "reference": entry["ground_truth"] if with_reference else None,
    }
    checks = {
        "id": entry["id"],
        "confidence": estimate.confidence,
        "dangling_citations": citations.dangling_citations,
        "citation_totals": citations.totals.model_dump(),
        "degraded_lines": gate.totals.degraded,
        "gate_totals": gate.totals.model_dump(),
        "judge_used": gate.judge_used,
    }
    return sample, checks


async def collect_samples(
    estimator, entries: Sequence[dict], *, use_judge: bool = True, with_reference: bool = True
) -> Collected:
    """Recolecta las muestras de `entries` en orden (secuencial: cada consulta son varias llamadas al LLM)."""
    collected = Collected()
    for entry in entries:
        sample, checks = await collect_one(estimator, entry, use_judge=use_judge, with_reference=with_reference)
        collected.samples.append(sample)
        collected.checks.append(checks)
        print(f"  {entry['id']}: {len(sample['retrieved_contexts'])} chunks, confianza {checks['confidence']}")
    return collected


def build_estimator():
    """El orquestador real (recuperador con reranker, caché de idempotencia en memoria) para la recolección."""
    from s08_common import require_embedder

    from app.config import get_settings
    from app.dependencies import get_chunk_retriever, get_reranker
    from app.foundation.persistence.database import SessionLocal
    from app.generation.rag.estimator import GroundedEstimator
    from app.generation.rag.idempotency import IdempotencyStore

    settings = get_settings()
    retriever = get_chunk_retriever(SessionLocal, require_embedder(), get_reranker())
    return GroundedEstimator(settings, retriever, IdempotencyStore(ttl=settings.idempotency_ttl))


def mean_scores(rows: Sequence[dict[str, float | None]], metrics: Sequence[str] = METRICS) -> dict[str, float | None]:
    """Media por métrica ignorando las muestras sin valor; `None` si ninguna lo tiene."""
    means: dict[str, float | None] = {}
    for metric in metrics:
        values = [row[metric] for row in rows if row.get(metric) is not None]
        means[metric] = round(statistics.fmean(values), 4) if values else None
    return means


def baseline_payload(samples: Sequence[dict], rows: Sequence[dict], collected: Collected, *, judge_model: str) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "judge_model": judge_model,
        "queries": len(samples),
        "metrics": mean_scores(rows),
        "per_query": [{"id": s["id"], "scores": row} for s, row in zip(samples, rows, strict=True)],
        "checks": {
            "dangling_citations": collected.dangling_citations,
            "degraded_lines": collected.degraded_lines,
        },
    }


def format_table(payload: dict) -> str:
    """Tabla Markdown (una fila por consulta y la media); sirve de informe versionado."""
    header = "| consulta | " + " | ".join(METRICS) + " |"
    divider = "|---|" + "---|" * len(METRICS)

    def cell(value: float | None) -> str:
        return "n/d" if value is None else f"{value:.3f}"

    rows = [
        f"| {item['id']} | " + " | ".join(cell(item["scores"].get(m)) for m in METRICS) + " |"
        for item in payload["per_query"]
    ]
    mean = "| **media** | " + " | ".join(f"**{cell(payload['metrics'].get(m))}**" for m in METRICS) + " |"
    return "\n".join([header, divider, *rows, mean])


def write_baseline(payload: dict, baseline_path: Path | None = None, report_path: Path | None = None) -> None:
    baseline_path, report_path = baseline_path or BASELINE_PATH, report_path or REPORT_PATH
    baseline_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report_path.write_text(
        "# Línea base RAGAS de la generación (Sesión 11)\n\n"
        f"Generada el {payload['generated_at']} con el juez `{payload['judge_model']}` sobre "
        f"{payload['queries']} consultas del golden set.\n\n"
        f"{format_table(payload)}\n\n"
        f"Citas colgantes: {payload['checks']['dangling_citations']} · "
        f"líneas `degraded`: {payload['checks']['degraded_lines']}.\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None, *, estimator=None, scorer=None) -> int:
    parser = argparse.ArgumentParser(description="Recolecta muestras de generación y puntúa con RAGAS.")
    parser.add_argument("--collect-only", action="store_true", help="Solo recolectar (sin juez de RAGAS).")
    parser.add_argument("--write-baseline", action="store_true", help="Versionar la línea base y su informe.")
    parser.add_argument("--no-judge", action="store_true", help="El gate de alucinaciones sin juez (solo ancla).")
    parser.add_argument("--samples-out", type=Path, default=SAMPLES_PATH)
    parser.add_argument("--limit", type=int, default=None, help="Solo las N primeras consultas.")
    args = parser.parse_args(argv)

    entries = load_golden()[: args.limit]
    print(f"Golden set de generación: {len(entries)} consultas.")
    collected = asyncio.run(collect_samples(estimator or build_estimator(), entries, use_judge=not args.no_judge))
    args.samples_out.write_text(
        json.dumps({"samples": collected.samples, "checks": collected.checks}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Muestras escritas en {args.samples_out}.")
    print(f"Citas colgantes: {collected.dangling_citations} · líneas degraded: {collected.degraded_lines}.")
    if args.collect_only:
        return 0

    if scorer is None:
        from score_ragas_s11 import JUDGE_MODEL, score_samples

        scorer = score_samples
        judge_model = JUDGE_MODEL
    else:
        judge_model = "fake"
    rows = scorer(collected.samples, METRICS)
    payload = baseline_payload(collected.samples, rows, collected, judge_model=judge_model)
    print(format_table(payload))
    if args.write_baseline:
        write_baseline(payload)
        print(f"Línea base escrita en {BASELINE_PATH.name} y {REPORT_PATH.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
