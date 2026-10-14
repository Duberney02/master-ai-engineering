"""El Boss: decide en código qué hacer con la revisión del crítico (sin llamadas al LLM)."""

from app.schemas.acb import BossDecision
from app.schemas.critic import CriticFeedback, Verdict


def decide(feedback: CriticFeedback, iteration: int, max_iterations: int) -> BossDecision:
    """Aceptar, regenerar o devolver el borrador con reservas.

    - `accept` → aceptar.
    - `reject` → devolver con reservas, aunque queden iteraciones: regenerar no arreglará una
      estimación que el crítico considera no salvable.
    - `needs_iteration` → regenerar mientras queden iteraciones (`iteration` cuenta desde 1 y
      `max_iterations` es el máximo de generaciones); con la última agotada, devolver con reservas.

    La confianza de la revisión es informativa (queda en la traza) y no altera la decisión.
    """
    if feedback.verdict is Verdict.ACCEPT:
        return BossDecision.ACCEPT
    if feedback.verdict is Verdict.NEEDS_ITERATION and iteration < max_iterations:
        return BossDecision.REGENERATE
    return BossDecision.RETURN_WITH_RESERVATIONS
