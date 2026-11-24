#!/usr/bin/env python3
"""Demo OFFLINE de las citas por línea y el gate de alucinaciones (Sesión 11).

No llama a ningún proveedor ni necesita base de datos: el LLM y el recuperador son dobles guionizados. Recorre el
escenario de aceptación de la sesión:

1. El modelo devuelve una línea que cita un chunk que NO vio (el 999): el informe la marca `dangling`, el orquestador
   reintenta UNA vez con la corrección y la segunda respuesta queda limpia.
2. Una línea sin respaldo vuelve `grounded=false`, sin fuentes ni horas (`insufficient`).
3. Si la cita colgante persiste tras el reintento, la confianza baja a `low`.
4. El gate de alucinaciones (ancla numérica) marca `degraded` una línea que afirma 20 jornadas con fuentes que respaldan
   5, y deja `grounded` la que es una fracción del componente.

Imprime `ACCEPTANCE: PASS` (código 0) o `ACCEPTANCE: FAIL` (código 1)::

    docker compose -f docker-compose.verify.yml run --rm --entrypoint python api-test \
        scripts/demo_verify_citations_s11.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# `python scripts/x.py` solo pone `scripts/` en sys.path: se añade la raíz del servicio para importar `app`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.foundation.llm.wrapper import Completion  # noqa: E402
from app.generation.rag.estimator import GroundedEstimator  # noqa: E402
from app.generation.rag.idempotency import IdempotencyStore  # noqa: E402
from app.generation.rag.quality.hallucination import run_gate  # noqa: E402
from app.generation.rag.schemas import Estimate, RetrievalResult, RetrievedChunk  # noqa: E402

TRANSCRIPT = (
    "Cliente: queremos una plataforma de pagos B2B para bancos, con onboarding KYC y conciliación. "
    "Hablamos del tiempo y del fútbol, pero lo importante es el marketplace de pagos y su cumplimiento."
)
BRIEF = {
    "function": "B2B payments marketplace with KYC onboarding",
    "technologies": ["stripe"],
    "sector": "finance",
    "scale": "large",
    "country": "ES",
    "regulations": ["PSD2"],
    "constraints": [],
}


def chunk(chunk_id: int, hours: int, topic: str) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        content=f"[Project: payments] Component {topic}. Estimated hours: {hours}",
        sector="finance",
        project_year=2024,
        chunk_type="budget_component",
        distance=0.2,
        budget_id=f"BUD-{chunk_id}",
        document_id=100 + chunk_id,
    )


def line(name: str, days: float | None, *chunk_ids: int) -> dict:
    grounded = bool(chunk_ids)
    return {
        "name": name,
        "description": None,
        "engineer_days": days if grounded else None,
        "grounded": grounded,
        "sources": [
            {"chunk_id": cid, "document_id": 100 + cid, "evidence": f"Estimated hours: {40 * cid}"} for cid in chunk_ids
        ],
    }


def estimate(*tasks: dict) -> dict:
    total = sum(t["engineer_days"] or 0 for t in tasks)
    return {
        "total_engineer_days": total,
        "duration_weeks": 4,
        "modules": [{"name": "Pagos", "description": None, "tasks": list(tasks)}],
        "sources": [{"source_id": 1, "relevance": "primary", "used_for": "horas de KYC"}],
        "assumptions": [],
        "confidence": "high",
        "reasoning": "Derivado de las fuentes recuperadas.",
        "insufficient_context_explanation": None,
    }


class ScriptedGenerator:
    def __init__(self, *outcomes: dict) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    async def __call__(self, messages, accept=None, **options) -> Completion:
        self.calls += 1
        return Completion(text=json.dumps(self._outcomes.pop(0)), model="demo", provider="openai")


class StaticRetriever:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks

    async def search(self, query_text, **kwargs) -> RetrievalResult:
        return RetrievalResult(chunks=self._chunks, low_confidence=False, candidates_evaluated=len(self._chunks))


def build(generator: ScriptedGenerator, chunks: list[RetrievedChunk]) -> GroundedEstimator:
    settings = Settings(llm_provider="openai", openai_api_key="sk-demo", _env_file=None)
    return GroundedEstimator(settings, StaticRetriever(chunks), IdempotencyStore(ttl=60), generate=generator)


def show(title: str, report) -> None:
    print(f"\n{title}")
    for verdict in report.lines:
        extra = f" (colgantes: {verdict.dangling_ids})" if verdict.dangling_ids else ""
        print(f"  - {verdict.task}: {verdict.status}{extra}")
    print(f"  totales: {report.totals.model_dump()} · colgantes globales: {report.dangling_citations}")


async def main() -> int:
    checks: dict[str, bool] = {}
    chunks = [chunk(1, 40, "KYC onboarding"), chunk(2, 80, "Reconciliation")]
    context_ids = {c.id for c in chunks}

    # 1 + 2. Línea con cita colgante → reintento → respuesta limpia, con una línea sin respaldo.
    dangling = estimate(line("Onboarding KYC", 5, 1), line("Conciliación", 6, 999), line("Integración SAP", None))
    repaired = estimate(line("Onboarding KYC", 5, 1), line("Conciliación", 10, 2), line("Integración SAP", None))
    first = Estimate.model_validate(dangling)
    first_report = GroundedEstimator.citation_report(first, chunks)
    show("Primera generación (con una cita a un chunk que el modelo no vio):", first_report)
    checks["la cita al chunk 999 se marca dangling"] = (
        first_report.lines[1].status == "dangling" and first_report.dangling_citations == [999]
    )
    checks["la línea sin datos es insufficient, sin fuentes ni horas"] = (
        first_report.lines[2].status == "insufficient"
        and first.modules[0].tasks[2].sources == []
        and first.modules[0].tasks[2].engineer_days is None
    )

    generator = ScriptedGenerator(BRIEF, dangling, repaired)
    final = await build(generator, chunks).estimate_from_transcript(TRANSCRIPT)
    final_report = GroundedEstimator.citation_report(final, chunks)
    show("Tras el reintento correctivo:", final_report)
    checks["el orquestador reintenta UNA vez y repara la cita"] = (
        generator.calls == 3 and final_report.totals.dangling == 0 and final.confidence == "high"
    )

    # 3. La cita colgante persiste → confianza `low`.
    stubborn = ScriptedGenerator(BRIEF, dangling, dangling)
    downgraded = await build(stubborn, chunks).estimate_from_transcript(TRANSCRIPT)
    print(f"\nCon la cita colgante persistente la confianza es: {downgraded.confidence}")
    checks["una cita colgante persistente rebaja la confianza a low"] = downgraded.confidence == "low"

    # 4. Gate de alucinaciones (solo ancla numérica: sin LLM).
    gated = Estimate.model_validate(
        estimate(line("Sobreestimada", 20, 1), line("Fracción del componente", 3, 2), line("Sin datos", None))
    )
    gate = await run_gate(gated, chunks, generate=None, tolerance=0.5, use_judge=False)
    print("\nGate de alucinaciones (ancla numérica):")
    for verdict in gate.lines:
        print(f"  - {verdict.task}: {verdict.status}" + (f" — {verdict.reason}" if verdict.reason else ""))
    checks["20 jornadas con fuentes que respaldan 5 → degraded"] = gate.lines[0].status == "degraded"
    checks["3 jornadas de un componente de 10 → grounded"] = gate.lines[1].status == "grounded"
    checks["la línea sin datos es insufficient en el gate"] = gate.lines[2].status == "insufficient"
    checks["el contexto del demo contiene los chunks citados"] = context_ids == {1, 2}

    print()
    for name, ok in checks.items():
        print(f"  [{'x' if ok else ' '}] {name}")
    passed = all(checks.values())
    print(f"\nACCEPTANCE: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
