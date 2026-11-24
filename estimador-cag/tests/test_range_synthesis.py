"""Síntesis de rangos (Sesión 11): `hours_range` cuando los vecinos se contradicen, sin tocar la cifra puntual."""

import pytest

from app.generation.rag.quality.synthesis import deterministic_bounds, is_contradictory, synthesize_range
from app.generation.rag.schemas import TaskHoursEstimate, TaskHoursModuleInput, TaskHoursTaskInput
from app.generation.rag.task_hours import TaskHoursEstimator, estimate_from_chunks
from tests._fakes import openai_settings
from tests._grounded import ScriptedGenerator
from tests.test_task_hours_api import HoursRetriever, hist, hours_body


def estimator(retriever, generate=None, **settings) -> TaskHoursEstimator:
    return TaskHoursEstimator(openai_settings(**settings), retriever, generate=generate)


def modules(*tasks: str) -> list[TaskHoursModuleInput]:
    return [TaskHoursModuleInput(name="Compliance", tasks=[TaskHoursTaskInput(name=t) for t in tasks])]


def contradictory_retriever() -> HoursRetriever:
    return HoursRetriever({"KYC onboarding": [hist(1, 40, 0.1), hist(2, 90, 0.1)]})


def coherent_retriever() -> HoursRetriever:
    return HoursRetriever({"KYC onboarding": [hist(1, 40, 0.1), hist(2, 44, 0.1)]})


# --- Funciones puras -------------------------------------------------------------------------------------------


def test_bounds_and_the_contradiction_test_use_the_neighbours():
    estimate = estimate_from_chunks("M", "t", [hist(1, 40, 0.1), hist(2, 90, 0.2)])

    assert deterministic_bounds(estimate) == (40, 90)
    assert is_contradictory(estimate, 0.35) and not is_contradictory(estimate, 0.9)


def test_a_task_without_match_or_with_one_neighbour_is_never_contradictory():
    assert not is_contradictory(TaskHoursEstimate(module="M", task="t", has_match=False), 0.0)
    assert not is_contradictory(estimate_from_chunks("M", "t", [hist(1, 40, 0.1)]), 0.0)


async def test_a_coherent_task_is_returned_untouched():
    estimate = estimate_from_chunks("M", "t", [hist(1, 40, 0.1), hist(2, 44, 0.1)])
    generator = ScriptedGenerator()

    result = await synthesize_range(estimate, threshold=0.35, generate=generator)

    assert result is estimate and result.hours_range is None and generator.calls == []


async def test_the_llm_writes_the_reason_and_the_range_comes_from_the_neighbours():
    estimate = estimate_from_chunks("Compliance", "KYC onboarding", [hist(1, 40, 0.1), hist(2, 90, 0.1)])
    generator = ScriptedGenerator({"reason": "Un precedente incluye verificación biométrica (90 h) y otro no (40 h)."})

    result = await synthesize_range(estimate, threshold=0.35, generate=generator, model="gpt-4o")

    assert (result.hours_range.low, result.hours_range.high) == (40, 90)
    assert result.hours_range.reason.startswith("Un precedente incluye verificación biométrica")
    assert result.estimated_hours == estimate.estimated_hours  # la cifra puntual no cambia
    assert generator.calls[0]["model"] == "gpt-4o" and "40, 90" in generator.user_messages()[0]


@pytest.mark.parametrize("failure", [RuntimeError("llm down"), "no es JSON", {"reason": ""}])
async def test_without_a_working_llm_the_range_is_deterministic_with_a_template_reason(failure):
    estimate = estimate_from_chunks("Compliance", "KYC onboarding", [hist(1, 40, 0.1), hist(2, 90, 0.1)])

    result = await synthesize_range(estimate, threshold=0.35, generate=ScriptedGenerator(failure, failure))

    assert (result.hours_range.low, result.hours_range.high) == (40, 90)
    assert "KYC onboarding" in result.hours_range.reason and "40 h" in result.hours_range.reason and "90 h" in result.hours_range.reason


async def test_with_no_generator_at_all_the_template_reason_is_used():
    estimate = estimate_from_chunks("M", "t", [hist(1, 40, 0.1), hist(2, 90, 0.1)])

    result = await synthesize_range(estimate, threshold=0.35, generate=None)

    assert result.hours_range is not None and "se contradicen" in result.hours_range.reason


# --- Estimador de horas ----------------------------------------------------------------------------------------


async def test_precedents_of_40_and_90_hours_yield_a_range_and_keep_the_point_estimate():
    generator = ScriptedGenerator({"reason": "Alcance distinto entre precedentes."})
    result = await estimator(contradictory_retriever(), generator, synthesis_enabled=True).estimate_all(modules("KYC onboarding"))

    task = result.tasks[0]
    assert (task.hours_range.low, task.hours_range.high) == (40, 90)
    assert task.hours_range.reason == "Alcance distinto entre precedentes."
    assert task.estimated_hours == 65.0 and task.dispersion > 0.35


async def test_coherent_neighbours_have_no_range_and_no_llm_call():
    generator = ScriptedGenerator()
    result = await estimator(coherent_retriever(), generator, synthesis_enabled=True).estimate_all(modules("KYC onboarding"))

    assert result.tasks[0].hours_range is None and generator.calls == []


async def test_the_llm_failure_still_produces_the_range():
    result = await estimator(
        contradictory_retriever(), ScriptedGenerator(RuntimeError("down"), RuntimeError("down")), synthesis_enabled=True
    ).estimate_all(modules("KYC onboarding"))

    assert (result.tasks[0].hours_range.low, result.tasks[0].hours_range.high) == (40, 90)


async def test_with_the_synthesis_disabled_there_is_no_range():
    generator = ScriptedGenerator()
    result = await estimator(contradictory_retriever(), generator).estimate_all(modules("KYC onboarding"))

    assert result.tasks[0].hours_range is None and generator.calls == []


async def test_the_contradiction_threshold_is_configurable():
    strict = await estimator(
        contradictory_retriever(), None, synthesis_enabled=True, synthesis_contradiction_threshold=0.2
    ).estimate_all(modules("KYC onboarding"))
    lax = await estimator(
        contradictory_retriever(), None, synthesis_enabled=True, synthesis_contradiction_threshold=0.5
    ).estimate_all(modules("KYC onboarding"))

    assert strict.tasks[0].hours_range is not None and lax.tasks[0].hours_range is None


async def test_unmatched_tasks_in_the_same_request_get_no_range():
    result = await estimator(contradictory_retriever(), None, synthesis_enabled=True).estimate_all(
        modules("KYC onboarding", "Quantum gardening")
    )

    assert result.tasks[0].hours_range is not None
    assert result.tasks[1].has_match is False and result.tasks[1].hours_range is None


def test_the_endpoint_exposes_the_range(monkeypatch):
    from app.dependencies import get_task_hours_estimator
    from app.main import app
    from tests._grounded import ESTIMATE_KEY, api_client

    client = api_client(monkeypatch)
    generator = ScriptedGenerator({"reason": "Precedentes contradictorios."})
    app.dependency_overrides[get_task_hours_estimator] = lambda: estimator(
        contradictory_retriever(), generator, synthesis_enabled=True
    )

    response = client.post(
        "/v1/estimate/tasks/hours", json=hours_body("KYC onboarding"), headers={"X-API-Key": ESTIMATE_KEY}
    )

    task = response.json()["tasks"][0]
    assert response.status_code == 200
    assert task["hours_range"] == {"low": 40.0, "high": 90.0, "reason": "Precedentes contradictorios."}
    assert task["estimated_hours"] == 65.0
