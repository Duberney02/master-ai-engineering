"""Orquestación Actor–Critic–Boss de una estimación de sesión.

El actor (`SessionEstimationService.draft`) genera una estimación, el crítico (`CriticService`) la revisa de
forma independiente y el Boss (`app.services.boss.decide`, en código) decide: aceptar, regenerar
incorporando el feedback o devolver el último borrador con reservas. Los borradores intermedios y los
mensajes de feedback nunca llegan al historial: solo se confirma, una vez, el resultado final.

Todo el bucle ocurre bajo el cerrojo de la sesión. Un fallo del actor (p. ej. 502 por respuesta
inválida) se propaga antes de `commit`, así que la sesión queda intacta; un fallo del crítico no
impide devolver el borrador (con reservas).
"""

import time
from dataclasses import dataclass

import structlog
from fastapi import Depends

from app.schemas import EstimationRequest
from app.schemas.acb import AuditIteration, AuditTrace, BossDecision, DefectSummary
from app.schemas.critic import CriticFeedback, Verdict
from app.services.audience import Audience
from app.services.boss import decide
from app.services.critic import CriticService, render_feedback_message
from app.services.llm_wrapper import Completion
from app.services.session_estimation import (
    Draft,
    Feedback,
    SessionEstimationService,
    SessionOutcome,
    get_session_estimation_service,
)
from app.services.sessions import Session

logger = structlog.get_logger(__name__)

_CRITIC_UNAVAILABLE = "No se pudo completar la revisión independiente de la estimación."
_MAX_RESERVATIONS = 10


@dataclass
class AcbOutcome:
    session_outcome: SessionOutcome
    trace: AuditTrace


class ActorCriticBoss:
    def __init__(self, service: SessionEstimationService, critic: CriticService, max_iterations: int | None = None):
        self.service = service
        self.critic = critic
        self.max_iterations = max_iterations or service.settings.boss_max_iterations

    async def run(
        self, session: Session, request: EstimationRequest, prompt_version: str, tier: Audience | None = None
    ) -> AcbOutcome:
        await self.service.check_input(request, prompt_version)
        async with session.lock:
            started = time.monotonic()
            resolution = self.service.resolve_audience(session, request, tier)
            transcript = self.service.audience_transcript(session, request)
            iterations: list[AuditIteration] = []
            reservations: list[str] = []
            review_completions: list[Completion] = []
            earlier_drafts: list[Completion] = []
            feedback: Feedback | None = None
            draft: Draft | None = None
            final_decision = BossDecision.RETURN_WITH_RESERVATIONS

            for iteration in range(1, self.max_iterations + 1):
                if draft is not None:  # el borrador anterior ya no es el final: sus tokens cuentan igualmente
                    earlier_drafts.extend(draft.completions)
                draft = await self.service.draft(session, request, prompt_version, resolution, feedback)
                try:
                    review = await self.critic.review(
                        transcript, session.metadata, resolution.audience.value, draft.result
                    )
                except Exception as exc:
                    logger.warning("critic_failed", iteration=iteration, error_type=type(exc).__name__)
                    iterations.append(
                        AuditIteration(
                            iteration=iteration,
                            boss_decision=BossDecision.RETURN_WITH_RESERVATIONS,
                            critic_error=True,
                        )
                    )
                    reservations = [_CRITIC_UNAVAILABLE]
                    break
                review_completions.extend(review.completions)
                decision = decide(review.feedback, iteration, self.max_iterations)
                iterations.append(
                    AuditIteration(
                        iteration=iteration,
                        critic_verdict=review.feedback.verdict,
                        critic_confidence=review.feedback.confidence,
                        defects=DefectSummary.of(review.feedback),
                        boss_decision=decision,
                    )
                )
                logger.info(
                    "boss_decision", iteration=iteration, verdict=review.feedback.verdict.value, decision=decision.value
                )
                if decision is BossDecision.REGENERATE:
                    feedback = Feedback(previous_text=draft.text, message=render_feedback_message(review.feedback))
                    continue
                final_decision = decision
                if decision is BossDecision.RETURN_WITH_RESERVATIONS:
                    reservations = _reservations(review.feedback)
                break

            assert draft is not None  # el máximo de iteraciones es al menos 1
            outcome = await self.service.commit(
                session,
                request,
                prompt_version,
                draft,
                resolution,
                started,
                extra_completions=[*earlier_drafts, *review_completions],
            )
            trace = AuditTrace(
                iterations=iterations,
                total_iterations=len(iterations),
                final_decision="accepted" if final_decision is BossDecision.ACCEPT else "returned_with_reservations",
                reservations=reservations,
            )
            return AcbOutcome(session_outcome=outcome, trace=trace)


def _reservations(feedback: CriticFeedback) -> list[str]:
    """Motivos por los que el borrador se devuelve con reservas: el rechazo y los defectos pendientes."""
    notes = [feedback.explanation] if feedback.verdict is Verdict.REJECT and feedback.explanation else []
    notes += [f"[{issue.severity.value}] {issue.affected_field}: {issue.description}" for issue in feedback.issues]
    return notes[:_MAX_RESERVATIONS]


def get_actor_critic_boss(
    service: SessionEstimationService = Depends(get_session_estimation_service),
) -> ActorCriticBoss:
    """Dependencia de FastAPI; las pruebas la sustituyen con `app.dependency_overrides`."""
    return ActorCriticBoss(service, CriticService(service.settings), service.settings.boss_max_iterations)
