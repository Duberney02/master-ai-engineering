"""Comprobaciones posteriores a la generación de una estimación fundamentada (Sesiones 9 y 11).

* `fabricated_source_ids`: ids citados (globales o por línea) que no estaban en el contexto (una alucinación disfrazada
  de rigor).
* `check_coherence`: el nivel `insufficient` tiene una forma estricta (sin cifras, sin módulos, con explicación).
* `build_citation_report` (Sesión 11): estado de cada línea (`grounded`, `dangling`, `insufficient`) y las citas
  verificadas y colgantes.
"""

from app.generation.rag.schemas import (
    CitationReport,
    CitationTotals,
    Estimate,
    LineCitationVerdict,
    LineStatus,
)


def cited_ids(estimate: Estimate) -> set[int]:
    """Todos los ids de chunk que cita la estimación: la lista global y las fuentes de cada línea."""
    ids = {citation.source_id for citation in estimate.sources}
    ids.update(
        source.chunk_id for module in estimate.modules for task in module.tasks for source in task.sources
    )
    return ids


def fabricated_source_ids(estimate: Estimate, context_ids: set[int]) -> list[int]:
    """Ids citados (globales o por línea) ausentes de `context_ids`, ordenados y sin duplicados."""
    return sorted(cited_ids(estimate) - context_ids)


def check_coherence(estimate: Estimate) -> bool:
    """Con `confidence="insufficient"`: totales nulos, `modules` vacío y explicación rellena; el resto, coherente."""
    if estimate.confidence != "insufficient":
        return True
    return (
        estimate.total_engineer_days is None
        and estimate.duration_weeks is None
        and not estimate.modules
        and bool((estimate.insufficient_context_explanation or "").strip())
    )


def build_citation_report(estimate: Estimate, context_ids: set[int]) -> CitationReport:
    """Informe de citas por línea contra los ids del contexto.

    * `insufficient`: la línea declara `grounded=false` (el contexto no la respalda).
    * `dangling`: la línea cita al menos un chunk que el modelo no vio.
    * `grounded`: todas sus citas existen en el contexto.
    """
    lines: list[LineCitationVerdict] = []
    totals = CitationTotals()
    for module in estimate.modules:
        for task in module.tasks:
            dangling = sorted({source.chunk_id for source in task.sources} - context_ids)
            status: LineStatus
            if not task.grounded:
                status = "insufficient"
                totals.insufficient += 1
            elif dangling:
                status = "dangling"
                totals.dangling += 1
            else:
                status = "grounded"
                totals.grounded += 1
            lines.append(LineCitationVerdict(module=module.name, task=task.name, status=status, dangling_ids=dangling))
    cited = cited_ids(estimate)
    return CitationReport(
        lines=lines,
        totals=totals,
        verified_citations=sorted(cited & context_ids),
        dangling_citations=sorted(cited - context_ids),
    )
