"""Comprobaciones posteriores a la generación de una estimación fundamentada (Sesión 9).

* `fabricated_source_ids`: ids citados que no estaban en el contexto (una alucinación disfrazada de rigor).
* `check_coherence`: el nivel `insufficient` tiene una forma estricta (sin cifras, sin módulos, con explicación).
"""

from app.generation.rag.schemas import Estimate


def fabricated_source_ids(estimate: Estimate, context_ids: set[int]) -> list[int]:
    """Ids citados en `estimate.sources` ausentes de `context_ids`, ordenados y sin duplicados."""
    return sorted({citation.source_id for citation in estimate.sources} - context_ids)


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
