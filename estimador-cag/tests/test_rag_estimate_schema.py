"""Esquema `Estimate` (módulos/tareas, citas, supuestos, confianza), regla de coherencia y ids inventados."""

import pytest
from pydantic import ValidationError

from app.generation.rag.estimator import insufficient_estimate
from app.generation.rag.schemas import Estimate, EstimateRequest, EstimationQuery
from app.generation.rag.validation import check_coherence, fabricated_source_ids
from tests._grounded import estimate_payload, incoherent_insufficient, line_task


def test_a_full_estimate_validates():
    estimate = Estimate.model_validate(estimate_payload(source_ids=(1, 2)))

    assert estimate.modules[0].tasks[0].engineer_days == 12
    assert [source.source_id for source in estimate.sources] == [1, 2]
    assert estimate.assumptions[0].impact == "medium" and estimate.confidence == "high"


@pytest.mark.parametrize(
    "override",
    [
        {"confidence": "certain"},
        {"total_engineer_days": -1},
        {"modules": [{"name": "X", "tasks": [line_task("t", -2)]}]},
        {"sources": [{"source_id": "abc", "relevance": "primary", "used_for": "x"}]},
        {"sources": [{"source_id": 1, "relevance": "vital", "used_for": "x"}]},
        {"assumptions": [{"description": "x", "impact": "huge", "rationale": "y"}]},
        {"reasoning": None},
    ],
)
def test_invalid_estimates_are_rejected(override):
    with pytest.raises(ValidationError):
        Estimate.model_validate(estimate_payload(**override))


@pytest.mark.parametrize("total", [0, 20, None])
def test_total_must_match_the_sum_of_tasks(total):
    with pytest.raises(ValidationError, match="sum of the task engineer_days"):
        Estimate.model_validate(estimate_payload(total_engineer_days=total))


def test_total_tolerates_rounding_and_ignores_insufficient():
    assert Estimate.model_validate(estimate_payload(total_engineer_days=12.4)).total_engineer_days == 12.4
    assert Estimate.model_validate(estimate_payload(modules=[], total_engineer_days=3)).total_engineer_days == 3
    assert Estimate.model_validate(incoherent_insufficient()).confidence == "insufficient"


async def test_a_wrong_total_triggers_the_correction_turn():
    from tests._grounded import BRIEF, TRANSCRIPT, ScriptedGenerator, build_estimator

    generator = ScriptedGenerator(BRIEF, estimate_payload(total_engineer_days=0), estimate_payload())

    estimate = await build_estimator(generator).estimate_from_transcript(TRANSCRIPT)

    assert estimate.total_engineer_days == 12 and len(generator.calls) == 3
    assert "sum of the task engineer_days" in generator.calls[2]["messages"][-1]["content"]


def test_coherence_rule_for_insufficient():
    assert check_coherence(insufficient_estimate())
    assert check_coherence(Estimate.model_validate(estimate_payload()))
    assert not check_coherence(Estimate.model_validate(incoherent_insufficient()))
    assert not check_coherence(
        Estimate.model_validate(
            estimate_payload(
                confidence="insufficient", total_engineer_days=None, duration_weeks=None, modules=[], sources=[]
            )
        )
    )  # sin explicación


def test_canonical_insufficient_estimate_has_no_numbers():
    estimate = insufficient_estimate()

    assert (estimate.total_engineer_days, estimate.duration_weeks, estimate.modules) == (None, None, [])
    assert estimate.confidence == "insufficient" and estimate.insufficient_context_explanation


def test_fabricated_ids_are_the_cited_ids_outside_the_context():
    estimate = Estimate.model_validate(estimate_payload(source_ids=(1, 999, 7, 999)))

    assert fabricated_source_ids(estimate, {1, 2, 3}) == [7, 999]
    assert fabricated_source_ids(estimate, {1, 7, 999}) == []


@pytest.mark.parametrize(
    "body", [{"transcript": "corta"}, {"transcript": "x" * 50_001}, {"transcript": "x" * 200, "idempotency_key": ""}]
)
def test_estimate_request_bounds(body):
    with pytest.raises(ValidationError):
        EstimateRequest.model_validate(body)


def test_estimation_query_defaults():
    query = EstimationQuery(function="app")

    assert (query.technologies, query.sector, query.scale) == ([], None, "unknown")
