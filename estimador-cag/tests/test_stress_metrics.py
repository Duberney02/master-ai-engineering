"""Métricas del stress test: presupuestos de latencia y coste y deriva de memoria (éxito, fallo y límites)."""

import math

import pytest

from evals.metrics import MetricResult
from evals.stress import (
    DEFAULT_COST_BUDGET_USD,
    DEFAULT_LATENCY_BUDGET_MS,
    CostBudgetMetric,
    LatencyBudgetMetric,
    MemoryDriftMetric,
    Snapshot,
)


def test_default_budgets_are_the_documented_ones():
    assert DEFAULT_LATENCY_BUDGET_MS == 30_000 and DEFAULT_COST_BUDGET_USD == 0.01
    assert LatencyBudgetMetric().budget_ms == 30_000 and CostBudgetMetric().budget_usd == 0.01


# --- LatencyBudgetMetric ---


def test_latency_within_budget_scores_one():
    result = LatencyBudgetMetric(1000).evaluate(999)

    assert isinstance(result, MetricResult)
    assert (result.name, result.score, result.passed) == ("latency_budget", 1.0, True)
    assert result.details == {"latency_ms": 999, "budget_ms": 1000.0}


def test_latency_over_budget_scores_zero():
    result = LatencyBudgetMetric(1000).evaluate(1500)

    assert (result.score, result.passed) == (0.0, False)


@pytest.mark.parametrize(("latency", "score"), [(1000, 1.0), (1001, 0.0), (0, 1.0)])
def test_latency_limit_is_inclusive(latency, score):
    assert LatencyBudgetMetric(1000).evaluate(latency).score == score


# --- CostBudgetMetric ---


def test_cost_within_budget_scores_one():
    result = CostBudgetMetric(0.01).evaluate(0.0042)

    assert (result.name, result.score, result.passed) == ("cost_budget", 1.0, True)


def test_cost_over_budget_scores_zero():
    result = CostBudgetMetric(0.01).evaluate(0.0101)

    assert (result.score, result.passed) == (0.0, False)
    assert result.details == {"cost_usd": 0.0101, "budget_usd": 0.01}


@pytest.mark.parametrize(("cost", "score"), [(0.01, 1.0), (0.0, 1.0), (0.010000001, 0.0)])
def test_cost_limit_is_inclusive(cost, score):
    assert CostBudgetMetric(0.01).evaluate(cost).score == score


def test_unknown_cost_fails_and_says_so():
    result = CostBudgetMetric().evaluate(None)

    assert (result.score, result.passed) == (0.0, False)
    assert result.details["unknown"] is True and result.details["cost_usd"] is None


@pytest.mark.parametrize("metric", [LatencyBudgetMetric, CostBudgetMetric])
@pytest.mark.parametrize("budget", [-1, math.nan, "10", True])
def test_invalid_budgets_are_rejected(metric, budget):
    with pytest.raises(ValueError):
        metric(budget)


# --- MemoryDriftMetric ---

METADATA = {
    "project_name": "Proyecto Atlas",
    "assumed_team_size": 4,
    "mentioned_technologies": ["Stripe", "Keycloak"],
    "agreed_scope": "Portal de pedidos con facturación",
}


def snapshot(turn=8, **parts) -> Snapshot:
    return Snapshot(turn_index=turn, **parts)


def test_fact_in_metadata_is_retained():
    result = MemoryDriftMetric().evaluate("Atlas", 1, snapshot(metadata=METADATA))

    assert (result.name, result.score, result.passed) == ("memory_drift", 1.0, True)
    assert result.details["found_in"] == ["metadata"]


def test_fact_in_summary_or_anchors_is_retained_and_reports_where():
    summary = MemoryDriftMetric().evaluate("Stripe", 2, snapshot(summary="Se acordó cobrar con Stripe."))
    anchors = MemoryDriftMetric().evaluate("30.000", 3, snapshot(anchors=("El presupuesto es de 30.000 EUR",)))
    everywhere = MemoryDriftMetric().evaluate(
        "Atlas", 1, snapshot(summary="Atlas", anchors=("Atlas",), metadata=METADATA)
    )

    assert summary.details["found_in"] == ["summary"]
    assert anchors.details["found_in"] == ["anchors"]
    assert everywhere.details["found_in"] == ["summary", "anchors", "metadata"]


def test_forgotten_fact_scores_zero():
    result = MemoryDriftMetric().evaluate("Zafiro", 7, snapshot(summary="Otro resumen.", metadata=METADATA))

    assert (result.score, result.passed) == (0.0, False)
    assert result.details["found_in"] == []


def test_match_is_case_insensitive_but_exact():
    metric = MemoryDriftMetric()

    assert metric.evaluate("keycloak", 1, snapshot(metadata=METADATA)).passed
    assert metric.evaluate("STRIPE", 1, snapshot(summary="stripe")).passed
    # Exacto: ni acentos plegados ni sinónimos.
    assert not metric.evaluate("facturacion", 1, snapshot(metadata=METADATA)).passed
    assert not metric.evaluate("Atlas Pro", 1, snapshot(metadata=METADATA)).passed


def test_alternatives_separated_by_pipe_match_any_of_them():
    metric = MemoryDriftMetric()

    assert metric.evaluate("30.000|30000", 3, snapshot(summary="presupuesto de 30000 EUR")).passed
    assert not metric.evaluate("30.000|30000", 3, snapshot(summary="presupuesto de 80.000 EUR")).passed


def test_recent_window_is_not_memory():
    # Solo cuentan resumen, anclas y metadatos: nada más viaja en el snapshot.
    assert set(snapshot(summary="a", anchors=("b",), metadata=METADATA).sources()) == {"summary", "anchors", "metadata"}


def test_snapshot_must_be_later_than_the_turn_that_introduced_the_fact():
    metric = MemoryDriftMetric()

    assert metric.evaluate("Atlas", 7, snapshot(turn=8, metadata=METADATA)).passed  # límite: justo después
    with pytest.raises(ValueError):
        metric.evaluate("Atlas", 8, snapshot(turn=8, metadata=METADATA))
    with pytest.raises(ValueError):
        metric.evaluate("Atlas", 9, snapshot(turn=8, metadata=METADATA))


@pytest.mark.parametrize("fact", ["", "  ", "|"])
def test_empty_fact_is_rejected(fact):
    with pytest.raises(ValueError):
        MemoryDriftMetric().evaluate(fact, 1, snapshot())


def test_empty_snapshot_forgets_everything():
    assert not MemoryDriftMetric().evaluate("Atlas", 1, snapshot()).passed
