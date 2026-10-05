"""Validación de negocio del resultado estructurado y filtro de estimaciones fuera de alcance.

Todo son funciones puras: el pipeline las usa para decidir si pide una corrección
al modelo y para revalidar resultados leídos de caché.
"""

import json
import re

from pydantic import ValidationError

from app.schemas.project_estimation import (
    OUT_OF_SCOPE_CONFIDENCE,
    OUT_OF_SCOPE_PREFIX,
    EstimationResult,
    Phase,
)

COST_TOLERANCE_EUR = 0.01
PLACEHOLDER_PHASE_NAME = "No estimable"
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class ResultValidationError(ValueError):
    """La respuesta del modelo no es un resultado válido; `str(exc)` explica por qué."""


def extract_json(text: str) -> dict:
    """Obtiene el objeto JSON de una respuesta, tolerando vallas de código y texto alrededor."""
    candidate = _FENCE.sub("", text.strip())
    start, end = candidate.find("{"), candidate.rfind("}")
    if start == -1 or end <= start:
        raise ResultValidationError("La respuesta no contiene un objeto JSON.")
    try:
        value = json.loads(candidate[start : end + 1])
    except ValueError:
        raise ResultValidationError("La respuesta no es JSON válido.") from None
    if not isinstance(value, dict):
        raise ResultValidationError("La respuesta debe ser un objeto JSON.")
    return value


def parse_result(value: dict) -> EstimationResult:
    try:
        return EstimationResult.model_validate(value)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
        )
        raise ResultValidationError(f"El JSON no cumple el esquema ({details}).") from None


def business_rule_errors(result: EstimationResult) -> list[str]:
    errors = []
    phases_total = round(sum(p.cost_eur for p in result.phases), 2)
    if abs(phases_total - result.total_cost_eur) > COST_TOLERANCE_EUR:
        errors.append(
            f"La suma de cost_eur de las fases ({phases_total:g}) no coincide con "
            f"total_cost_eur ({result.total_cost_eur:g})."
        )
    if result.out_of_scope and not result.summary.lstrip().startswith(OUT_OF_SCOPE_PREFIX):
        errors.append(
            f"Con confidence_pct inferior a {OUT_OF_SCOPE_CONFIDENCE}, summary debe empezar "
            f"por '{OUT_OF_SCOPE_PREFIX}'."
        )
    return errors


def validate_result(result: EstimationResult) -> EstimationResult:
    errors = business_rule_errors(result)
    if errors:
        raise ResultValidationError(" ".join(errors))
    return result


def validate_text(text: str) -> EstimationResult:
    """Parsea y valida la respuesta del modelo; lanza `ResultValidationError` si falla."""
    return validate_result(parse_result(extract_json(text)))


def apply_out_of_scope_filter(result: EstimationResult) -> EstimationResult:
    """Un resultado fuera de alcance se presenta con una única fase placeholder de coste 0."""
    if not result.out_of_scope:
        return result
    return result.model_copy(
        update={
            "phases": [
                Phase(
                    name=PLACEHOLDER_PHASE_NAME,
                    description=result.summary,
                    duration_weeks=1,
                    cost_eur=0,
                )
            ],
            "total_duration_weeks": 1,
            "total_cost_eur": 0,
        }
    )


def correction_message(error: str) -> str:
    return (
        "Tu respuesta anterior no es válida: "
        f"{error}\nCorrígela y devuelve únicamente el objeto JSON completo."
    )
