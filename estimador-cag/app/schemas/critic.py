"""Contrato del crítico: defectos detectados en una estimación y veredicto de la revisión.

Lo produce el LLM (`app.services.critic`) y lo consume el Boss (`app.services.boss`). Los textos libres
se reinyectan en el prompt de la siguiente generación, de ahí la normalización (sin marcado).
"""

import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_MARKUP_CHARS = re.compile(r"[<>`]")
_SPACES = re.compile(r"\s+")


class IssueCategory(str, Enum):
    MATH_ERROR = "math_error"
    HALLUCINATION = "hallucination"
    SCOPE_MISMATCH = "scope_mismatch"
    PHASE_IMBALANCE = "phase_imbalance"
    MISSING_ASSUMPTION = "missing_assumption"
    UNREALISTIC_ESTIMATE = "unrealistic_estimate"
    TIER_MISMATCH = "tier_mismatch"


class Severity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class Verdict(str, Enum):
    ACCEPT = "accept"
    NEEDS_ITERATION = "needs_iteration"
    REJECT = "reject"


# Severidades que justifican regenerar la estimación.
BLOCKING_SEVERITIES = frozenset({Severity.CRITICAL, Severity.MAJOR})


def _clean(value: object) -> object:
    if not isinstance(value, str):
        return value
    return _SPACES.sub(" ", _MARKUP_CHARS.sub(" ", _CONTROL_CHARS.sub(" ", value))).strip()


class CriticIssue(BaseModel):
    category: IssueCategory
    severity: Severity
    affected_field: str = Field(min_length=1, max_length=120, description="Campo de la estimación afectado.")
    description: str = Field(min_length=1, max_length=600)
    suggested_fix: str = Field(min_length=1, max_length=600)

    @field_validator("affected_field", "description", "suggested_fix", mode="before")
    @classmethod
    def _clean_text(cls, value: object) -> object:
        return _clean(value)


class CriticFeedback(BaseModel):
    verdict: Verdict
    issues: list[CriticIssue] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False, description="Confianza de la revisión (0 a 1).")
    explanation: str | None = Field(default=None, max_length=1000)

    @field_validator("explanation", mode="before")
    @classmethod
    def _clean_explanation(cls, value: object) -> object:
        cleaned = _clean(value)
        return cleaned or None

    @model_validator(mode="after")
    def _verdict_is_consistent(self) -> "CriticFeedback":
        if self.verdict is Verdict.NEEDS_ITERATION and not any(
            issue.severity in BLOCKING_SEVERITIES for issue in self.issues
        ):
            raise ValueError("needs_iteration requiere al menos un defecto critical o major")
        if self.verdict is Verdict.REJECT and not self.explanation:
            raise ValueError("reject requiere una explicación")
        return self
