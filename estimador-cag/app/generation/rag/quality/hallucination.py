"""Gate de alucinaciones (Sesión 11): ancla numérica determinista + juez LLM estricto.

Una cita a un chunk real no garantiza que la cifra esté respaldada: una línea puede citar «KYC, 40 h» y afirmar 20 días.
El gate califica cada línea fundamentada:

1. **Ancla numérica** (función pura): las horas históricas de los chunks citados (campo `estimated_hours` o cifra
   «Estimated hours: N» del texto) sumadas y pasadas a jornadas de 8 horas. La regla es ASIMÉTRICA: solo penaliza la
   SOBREestimación (una línea puede ser una fracción del componente histórico). La tolerancia es relativa: con 0,5, una
   línea puede afirmar hasta un 50 % más que el ancla.
2. **Juez LLM**: UNA llamada por estimación (no por línea, para acotar coste y latencia) que dictamina si la evidencia
   literal de cada línea respalda su cifra.

`degraded` = supera el ancla más allá de la tolerancia, o el juez no la respalda. Las líneas `grounded=false` son
`insufficient`. Las funciones puras se prueban sin LLM; el conductor (`run_gate`) solo inyecta el generador.
"""

import re

import structlog
from pydantic import BaseModel, Field

from app.foundation.llm.structured import Generator, generate_structured
from app.foundation.prompts.loader import render_rag_template
from app.generation.rag.schemas import (
    Estimate,
    GateTotals,
    LineGateVerdict,
    RetrievedChunk,
    TaskItem,
    VerifyReport,
)

logger = structlog.get_logger(__name__)

HOURS_PER_DAY = 8.0
_HOURS_IN_TEXT = re.compile(r"estimated\s+hours\D{0,5}(\d+(?:[.,]\d+)?)", re.IGNORECASE)
_JUDGE_MAX_TOKENS = 2000
_EVIDENCE_LIMIT = 600


class JudgeLine(BaseModel):
    index: int
    supported: bool
    reason: str = ""


class JudgeVerdict(BaseModel):
    """Salida estructurada del juez: un dictamen por línea enviada."""

    lines: list[JudgeLine] = Field(default_factory=list)


def chunk_hours(chunk: RetrievedChunk) -> float | None:
    """Horas históricas de un chunk: su metadato `estimated_hours` o, si no, la cifra «Estimated hours: N» del texto."""
    if chunk.estimated_hours is not None:
        return float(chunk.estimated_hours)
    match = _HOURS_IN_TEXT.search(chunk.content)
    return float(match.group(1).replace(",", ".")) if match else None


def numeric_anchor(task: TaskItem, chunks_by_id: dict[int, RetrievedChunk]) -> float | None:
    """Jornadas que respaldan los chunks citados por la línea; `None` si ninguno aporta una cifra de horas."""
    hours = [
        value
        for source in task.sources
        if (chunk := chunks_by_id.get(source.chunk_id)) is not None and (value := chunk_hours(chunk)) is not None
    ]
    return sum(hours) / HOURS_PER_DAY if hours else None


def gate_line(
    module: str,
    task: TaskItem,
    anchor_days: float | None,
    *,
    tolerance: float,
    judge: JudgeLine | None = None,
) -> LineGateVerdict:
    """Calificación de UNA línea (función pura): `insufficient`, `degraded` o `grounded`."""
    base = {"module": module, "task": task.name, "claimed_days": task.engineer_days, "anchor_days": anchor_days}
    if not task.grounded:
        return LineGateVerdict(status="insufficient", **base)

    reasons: list[str] = []
    claimed = task.engineer_days or 0.0
    if anchor_days is not None and claimed > anchor_days * (1 + tolerance):
        if anchor_days > 0:
            deviation = f"+{(claimed / anchor_days - 1) * 100:.0f} %"
        else:
            deviation = "el ancla es 0"
        reasons.append(f"afirma {claimed:g} jornadas y las fuentes respaldan ~{anchor_days:g} (desviación {deviation})")
    if judge is not None and not judge.supported:
        reasons.append(f"el juez no la respalda: {judge.reason}" if judge.reason else "el juez no la respalda")
    return LineGateVerdict(
        status="degraded" if reasons else "grounded",
        reason="; ".join(reasons) or None,
        judge_supported=None if judge is None else judge.supported,
        **base,
    )


def _numbered_lines(estimate: Estimate) -> list[tuple[int, str, TaskItem]]:
    """Todas las líneas en orden, con su índice estable (el que el juez devuelve)."""
    lines: list[tuple[int, str, TaskItem]] = []
    for module in estimate.modules:
        for task in module.tasks:
            lines.append((len(lines), module.name, task))
    return lines


async def judge_lines(estimate: Estimate, *, generate: Generator, model: str | None = None) -> dict[int, JudgeLine]:
    """UNA llamada al juez con todas las líneas fundamentadas; devuelve los dictámenes por índice de línea."""
    payload = [
        {
            "index": index,
            "task": task.name,
            "claimed_days": task.engineer_days,
            "evidence": [source.evidence[:_EVIDENCE_LIMIT] for source in task.sources],
        }
        for index, _module, task in _numbered_lines(estimate)
        if task.grounded
    ]
    if not payload:
        return {}
    messages = [
        {"role": "system", "content": render_rag_template("judge", "system", {})},
        {"role": "user", "content": render_rag_template("judge", "user", {"lines": payload})},
    ]
    options: dict = {"max_tokens": _JUDGE_MAX_TOKENS}
    if model:
        options["model"] = model
    verdict, _ = await generate_structured(generate, messages, JudgeVerdict, **options)
    return {line.index: line for line in verdict.lines}


async def run_gate(
    estimate: Estimate,
    kept_chunks: list[RetrievedChunk],
    *,
    generate: Generator | None,
    tolerance: float,
    use_judge: bool = True,
    judge_model: str | None = None,
) -> VerifyReport:
    """Califica todas las líneas. Con `use_judge=False` (o sin generador) solo aplica el ancla numérica.

    Un fallo del juez se propaga: el llamante decide (el pipeline lo degrada a solo-ancla; la etapa responde 502).
    """
    chunks_by_id = {chunk.id: chunk for chunk in kept_chunks}
    judge_used = bool(use_judge and generate is not None)
    judged: dict[int, JudgeLine] = {}
    if judge_used:
        judged = await judge_lines(estimate, generate=generate, model=judge_model)  # type: ignore[arg-type]

    verdicts = [
        gate_line(module, task, numeric_anchor(task, chunks_by_id), tolerance=tolerance, judge=judged.get(index))
        for index, module, task in _numbered_lines(estimate)
    ]
    totals = GateTotals(
        grounded=sum(1 for v in verdicts if v.status == "grounded"),
        degraded=sum(1 for v in verdicts if v.status == "degraded"),
        insufficient=sum(1 for v in verdicts if v.status == "insufficient"),
    )
    return VerifyReport(lines=verdicts, totals=totals, judge_used=judge_used)
