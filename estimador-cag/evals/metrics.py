"""Métricas deterministas de una estimación estructurada frente a las expectativas de un caso.

Son funciones puras (sin LLM ni E/S). Cada una devuelve un `MetricResult` con una puntuación entre 0 y 1,
si aprueba y el detalle de lo comprobado. Las evaluaciones del flujo de transcripción
(`app/services/evaluation.py`) siguen siendo independientes.
"""

from dataclasses import dataclass, field

from app.schemas import EstimationResult
from app.schemas.project_estimation import OUT_OF_SCOPE_PREFIX
from app.services.anchors import fold
from app.services.validation import PLACEHOLDER_PHASE_NAME, business_rule_errors
from evals.dataset import EvalCase

# Las fases pueden solaparse, así que la duración total no es la suma: debe quedar entre la fase más
# larga y la suma, con esta holgura (semanas) por redondeos.
DURATION_TOLERANCE_WEEKS = 0.5
METRIC_NAMES = ("schema_adherence", "cost_bounds", "content_recall")


@dataclass
class MetricResult:
    name: str
    score: float
    passed: bool
    details: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"score": round(self.score, 3), "passed": self.passed, "details": self.details}


def _fraction(checks: dict[str, bool]) -> float:
    return sum(checks.values()) / len(checks) if checks else 1.0


def _in_range(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


def schema_adherence(result: EstimationResult, case: EvalCase) -> MetricResult:
    """Coherencia estructural de la estimación y número de fases dentro del rango del caso."""
    expectations = case.expectations
    phases = result.phases
    durations = [p.duration_weeks for p in phases]
    names = [p.name.strip().casefold() for p in phases]
    checks: dict[str, bool] = {
        "business_rules": not business_rule_errors(result),
        "durations_coherent": (
            max(durations) - DURATION_TOLERANCE_WEEKS
            <= result.total_duration_weeks
            <= sum(durations) + DURATION_TOLERANCE_WEEKS
        ),
        "unique_phase_names": len(set(names)) == len(names),
    }
    if result.out_of_scope:
        checks["out_of_scope_shape"] = (
            len(phases) == 1
            and phases[0].name == PLACEHOLDER_PHASE_NAME
            and result.total_cost_eur == 0
            and result.summary.lstrip().startswith(OUT_OF_SCOPE_PREFIX)
        )
    elif expectations.phases:
        checks["phase_count_in_range"] = _in_range(len(phases), expectations.phases)
    return MetricResult(
        "schema_adherence",
        _fraction(checks),
        all(checks.values()),
        {"checks": checks, "phase_count": len(phases)},
    )


def cost_bounds(result: EstimationResult, case: EvalCase) -> MetricResult:
    """Coste y duración dentro de los rangos del caso y carácter fuera de alcance coincidente."""
    expectations = case.expectations
    checks: dict[str, bool] = {"out_of_scope_matches": result.out_of_scope == expectations.expect_out_of_scope}
    details: dict[str, object] = {"out_of_scope": result.out_of_scope}
    if expectations.expect_out_of_scope:
        checks["no_figures"] = result.total_cost_eur == 0
    else:
        for name, value, bounds in (
            ("cost_eur", result.total_cost_eur, expectations.cost_eur),
            ("duration_weeks", result.total_duration_weeks, expectations.duration_weeks),
        ):
            if bounds is None:
                continue
            checks[f"{name}_in_range"] = _in_range(value, bounds)
            details[name] = {"value": value, "range": list(bounds)}
    details["checks"] = checks
    return MetricResult("cost_bounds", _fraction(checks), all(checks.values()), details)


def _alternatives(keyword: str) -> list[str]:
    return [alt for alt in (fold(part).strip() for part in keyword.split("|")) if alt]


def content_recall(result: EstimationResult, case: EvalCase) -> MetricResult:
    """Fracción de requisitos y tecnologías esperados presentes en el resumen y las fases."""
    expected = [*case.expectations.requirements, *case.expectations.technologies]
    if not expected or case.expectations.expect_out_of_scope:
        return MetricResult("content_recall", 1.0, True, {"expected": 0, "note": "sin expectativas de contenido"})
    text = fold(" ".join([result.summary, *(f"{p.name} {p.description}" for p in result.phases)]))
    found = [keyword for keyword in expected if any(alt in text for alt in _alternatives(keyword))]
    missing = [keyword for keyword in expected if keyword not in found]
    recall = len(found) / len(expected)
    return MetricResult(
        "content_recall",
        recall,
        recall >= case.expectations.min_recall,
        {"expected": len(expected), "found": len(found), "missing": missing, "threshold": case.expectations.min_recall},
    )


def evaluate_case(result: EstimationResult, case: EvalCase) -> dict[str, MetricResult]:
    """Las tres métricas de un caso; el caso aprueba si aprueban todas."""
    return {
        "schema_adherence": schema_adherence(result, case),
        "cost_bounds": cost_bounds(result, case),
        "content_recall": content_recall(result, case),
    }
