"""Métricas deterministas: schema_adherence, cost_bounds y content_recall."""

import pytest

from app.schemas import EstimationResult
from evals.dataset import EvalCase
from evals.metrics import content_recall, cost_bounds, evaluate_case, schema_adherence


def case(**expectations) -> EvalCase:
    return EvalCase.model_validate(
        {
            "id": "caso",
            "category": "saas",
            "title": "Caso",
            "project_type": "web_saas",
            "transcript": "Transcripción suficientemente larga para el caso de prueba.",
            "expectations": expectations or {"requirements": ["algo"]},
        }
    )


def result(**overrides) -> EstimationResult:
    base = {
        "summary": "Plataforma de facturación con Stripe, React y PostgreSQL. Cumple el RGPD.",
        "confidence_pct": 70,
        "phases": [
            {"name": "Diseño", "description": "UX y prototipos", "duration_weeks": 3, "cost_eur": 10000},
            {
                "name": "Desarrollo",
                "description": "Backend en PostgreSQL y frontend React",
                "duration_weeks": 10,
                "cost_eur": 50000,
            },
            {"name": "QA y despliegue", "description": "Pruebas y salida", "duration_weeks": 3, "cost_eur": 10000},
        ],
        "total_duration_weeks": 14,
        "total_cost_eur": 70000,
    }
    return EstimationResult.model_validate({**base, **overrides})


OUT_OF_SCOPE = {
    "summary": "Out of scope: faltan objetivos.",
    "confidence_pct": 10,
    "total_duration_weeks": 1,
    "total_cost_eur": 0,
    "phases": [
        {"name": "No estimable", "description": "Out of scope: faltan objetivos.", "duration_weeks": 1, "cost_eur": 0}
    ],
}


# --- schema_adherence ---


def test_coherent_estimation_scores_one():
    metric = schema_adherence(result(), case(phases=[3, 6]))

    assert metric.passed and metric.score == 1 and metric.name == "schema_adherence"
    assert metric.details["checks"] == {
        "business_rules": True,
        "durations_coherent": True,
        "unique_phase_names": True,
        "phase_count_in_range": True,
    }


def test_cost_sum_mismatch_fails_business_rules():
    metric = schema_adherence(result(total_cost_eur=99999), case())

    assert not metric.passed and metric.details["checks"]["business_rules"] is False and 0 < metric.score < 1


def test_total_duration_shorter_than_the_longest_phase_is_incoherent():
    metric = schema_adherence(result(total_duration_weeks=5), case())

    assert not metric.passed and metric.details["checks"]["durations_coherent"] is False


def test_total_duration_longer_than_the_sum_of_phases_is_incoherent():
    metric = schema_adherence(result(total_duration_weeks=40), case())

    assert metric.details["checks"]["durations_coherent"] is False


def test_overlapping_phases_are_allowed():
    metric = schema_adherence(result(total_duration_weeks=10), case())

    assert metric.details["checks"]["durations_coherent"] is True


def test_duplicate_phase_names_fail():
    phases = [
        {"name": "Fase", "description": "", "duration_weeks": 2, "cost_eur": 100},
        {"name": " fase ", "description": "", "duration_weeks": 2, "cost_eur": 100},
    ]

    metric = schema_adherence(result(phases=phases, total_cost_eur=200, total_duration_weeks=4), case())

    assert metric.details["checks"]["unique_phase_names"] is False


@pytest.mark.parametrize(("bounds", "ok"), [([4, 8], False), ([1, 2], False), ([3, 3], True), ([1, 10], True)])
def test_phase_count_must_be_inside_the_case_range(bounds, ok):
    metric = schema_adherence(result(), case(phases=bounds))

    assert metric.details["checks"]["phase_count_in_range"] is ok


def test_out_of_scope_result_must_have_the_placeholder_shape():
    metric = schema_adherence(EstimationResult.model_validate(OUT_OF_SCOPE), case(expect_out_of_scope=True))

    assert metric.passed and metric.details["checks"]["out_of_scope_shape"] is True
    assert "phase_count_in_range" not in metric.details["checks"]


# --- cost_bounds ---


def test_cost_and_duration_inside_ranges_pass():
    metric = cost_bounds(result(), case(cost_eur=[50000, 100000], duration_weeks=[10, 20]))

    assert metric.passed and metric.score == 1


@pytest.mark.parametrize(
    ("cost", "duration", "failing"),
    [
        ([80000, 100000], [10, 20], "cost_eur_in_range"),
        ([1000, 60000], [10, 20], "cost_eur_in_range"),
        ([50000, 100000], [20, 30], "duration_weeks_in_range"),
    ],
)
def test_values_outside_ranges_fail_and_report_value_and_range(cost, duration, failing):
    metric = cost_bounds(result(), case(cost_eur=cost, duration_weeks=duration))

    assert not metric.passed and metric.details["checks"][failing] is False
    key = failing.removesuffix("_in_range")
    assert metric.details[key]["value"] and metric.details[key]["range"]


def test_range_edges_are_inclusive():
    assert cost_bounds(result(), case(cost_eur=[70000, 70000], duration_weeks=[14, 14])).passed


def test_case_without_ranges_only_checks_the_scope():
    metric = cost_bounds(result(), case(requirements=["xx"]))

    assert metric.passed and list(metric.details["checks"]) == ["out_of_scope_matches"]


def test_expected_out_of_scope_with_zero_cost_passes():
    assert cost_bounds(EstimationResult.model_validate(OUT_OF_SCOPE), case(expect_out_of_scope=True)).passed


def test_expected_out_of_scope_with_figures_fails():
    metric = cost_bounds(result(), case(expect_out_of_scope=True))

    assert not metric.passed and metric.details["checks"]["out_of_scope_matches"] is False


def test_unexpected_out_of_scope_fails_and_ranges_are_still_reported():
    metric = cost_bounds(EstimationResult.model_validate(OUT_OF_SCOPE), case(cost_eur=[1000, 5000]))

    assert not metric.passed and metric.details["checks"]["out_of_scope_matches"] is False


# --- content_recall ---


def test_full_recall_scores_one():
    metric = content_recall(result(), case(requirements=["facturación"], technologies=["stripe", "react"]))

    assert metric.passed and metric.score == 1 and metric.details["missing"] == []


def test_partial_recall_reports_the_missing_items_and_applies_the_threshold():
    metric = content_recall(
        result(), case(requirements=["facturación", "inventario"], technologies=["stripe", "kafka"])
    )

    assert metric.score == 0.5 and not metric.passed
    assert metric.details["missing"] == ["inventario", "kafka"] and metric.details["threshold"] == 0.6


def test_a_lower_case_threshold_can_make_partial_recall_pass():
    metric = content_recall(result(), case(requirements=["facturación", "inventario"], min_recall=0.5))

    assert metric.passed and metric.score == 0.5


def test_alternatives_accents_and_case_are_ignored():
    metric = content_recall(result(), case(requirements=["proteccion de datos|rgpd"], technologies=["POSTGRESQL"]))

    assert metric.passed and metric.score == 1


def test_phase_names_and_descriptions_count_as_content():
    assert content_recall(result(), case(requirements=["prototipos"])).passed


def test_no_expectations_passes_with_full_score():
    metric = content_recall(result(), case(cost_eur=[1, 10]))

    assert metric.passed and metric.score == 1 and metric.details["expected"] == 0


def test_out_of_scope_cases_have_no_content_expectations():
    assert content_recall(EstimationResult.model_validate(OUT_OF_SCOPE), case(expect_out_of_scope=True)).passed


# --- conjunto ---


def test_evaluate_case_returns_the_three_metrics():
    metrics = evaluate_case(result(), case(requirements=["facturación"], cost_eur=[50000, 90000]))

    assert list(metrics) == ["schema_adherence", "cost_bounds", "content_recall"]
    assert all(m.passed for m in metrics.values())
    assert metrics["cost_bounds"].as_dict()["score"] == 1


def test_existing_structural_evaluation_is_unchanged():
    from app.services.evaluation import evaluate_estimation

    assert evaluate_estimation("sin formato", "stop").score < 1
