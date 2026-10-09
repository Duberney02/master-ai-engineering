"""Contratos de la estimación revisada (`POST /api/v1/sessions/{id}/estimate-acb`) y su traza de auditoría."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.critic import CriticFeedback, Severity, Verdict
from app.schemas.sessions import SessionEstimationResponse


class BossDecision(str, Enum):
    ACCEPT = "accept"
    REGENERATE = "regenerate"
    RETURN_WITH_RESERVATIONS = "return_with_reservations"


FinalDecision = Literal["accepted", "returned_with_reservations"]


class DefectSummary(BaseModel):
    """Recuento de defectos por severidad y categorías afectadas, sin texto del usuario."""

    critical: int = Field(default=0, ge=0)
    major: int = Field(default=0, ge=0)
    minor: int = Field(default=0, ge=0)
    categories: list[str] = Field(default_factory=list)

    @classmethod
    def of(cls, feedback: CriticFeedback | None) -> "DefectSummary":
        if feedback is None:
            return cls()
        counts = {severity: sum(i.severity is severity for i in feedback.issues) for severity in Severity}
        categories = list(dict.fromkeys(issue.category.value for issue in feedback.issues))
        return cls(
            critical=counts[Severity.CRITICAL],
            major=counts[Severity.MAJOR],
            minor=counts[Severity.MINOR],
            categories=categories,
        )


class AuditIteration(BaseModel):
    iteration: int = Field(ge=1)
    critic_verdict: Verdict | None = Field(default=None, description="`null` si el crítico no pudo revisar.")
    critic_confidence: float | None = Field(default=None, ge=0, le=1)
    defects: DefectSummary = Field(default_factory=DefectSummary)
    boss_decision: BossDecision
    critic_error: bool = False


class AuditTrace(BaseModel):
    iterations: list[AuditIteration]
    total_iterations: int = Field(ge=1)
    final_decision: FinalDecision
    reservations: list[str] = Field(
        default_factory=list, description="Defectos pendientes o motivo del rechazo si se devuelve con reservas."
    )


class AcbEstimationResponse(SessionEstimationResponse):
    """Respuesta de `estimate-acb`: la de la estimación conversacional más la traza de auditoría."""

    audit_trace: AuditTrace
