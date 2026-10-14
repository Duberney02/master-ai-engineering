"""Decisiones del Boss: puras, deterministas y sin llamadas al LLM."""

import pytest

from app.schemas.acb import BossDecision
from app.schemas.critic import CriticFeedback
from app.services.boss import decide
from tests._acb import accept, needs_iteration, reject


def feedback(payload: dict) -> CriticFeedback:
    return CriticFeedback.model_validate(payload)


@pytest.mark.parametrize(("iteration", "maximum"), [(1, 1), (1, 3), (3, 3)])
def test_accept_is_always_accepted(iteration, maximum):
    assert decide(feedback(accept()), iteration, maximum) is BossDecision.ACCEPT


@pytest.mark.parametrize(("iteration", "maximum"), [(1, 1), (1, 3), (3, 3)])
def test_reject_returns_the_draft_with_reservations_even_if_iterations_remain(iteration, maximum):
    assert decide(feedback(reject()), iteration, maximum) is BossDecision.RETURN_WITH_RESERVATIONS


@pytest.mark.parametrize(("iteration", "maximum"), [(1, 2), (1, 3), (2, 3), (4, 5)])
def test_needs_iteration_regenerates_while_iterations_remain(iteration, maximum):
    assert decide(feedback(needs_iteration()), iteration, maximum) is BossDecision.REGENERATE


@pytest.mark.parametrize(("iteration", "maximum"), [(1, 1), (2, 2), (3, 3), (5, 5)])
def test_needs_iteration_on_the_last_iteration_returns_with_reservations(iteration, maximum):
    assert decide(feedback(needs_iteration()), iteration, maximum) is BossDecision.RETURN_WITH_RESERVATIONS


def test_the_review_confidence_does_not_change_the_decision():
    low, high = accept(0.0), accept(1.0)

    assert decide(feedback(low), 1, 3) is decide(feedback(high), 1, 3) is BossDecision.ACCEPT


def test_the_boss_makes_no_llm_calls(mocker):
    sdk = mocker.patch("app.services.llm_service.AsyncOpenAI")

    decide(feedback(needs_iteration()), 1, 3)

    sdk.assert_not_called()
