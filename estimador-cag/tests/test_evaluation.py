import pytest

from app.context.examples import ESTIMATION_EXAMPLES, ESTIMATION_EXAMPLES_CATALOG
from app.services.evaluation import evaluate_estimation

WELL_FORMED = ESTIMATION_EXAMPLES[0]["estimation"]  # total 292, rango 280–340


def _replace(text: str, old: str, new: str) -> str:
    assert old in text
    return text.replace(old, new)


@pytest.mark.parametrize("example", ESTIMATION_EXAMPLES_CATALOG, ids=lambda e: e.title[:25])
def test_every_catalog_example_passes_its_own_evaluation(example):
    ev = evaluate_estimation(example.estimation_markdown, "stop")
    assert ev.score == 1.0, ev.issues
    assert ev.issues == []
    assert ev.table_rows == len(example.tareas)
    assert ev.declared_total_hours == example.total_hours
    assert ev.sum_row_hours_min == ev.sum_row_hours_max == example.total_hours
    assert (ev.range_min, ev.range_max) == example.rango


def test_well_formed_response_has_all_sections_in_order():
    ev = evaluate_estimation(WELL_FORMED, "stop")
    assert all(ev.sections.values()) and len(ev.sections) == 7
    assert ev.sections_in_order
    assert ev.has_breakdown_table and ev.has_team and ev.has_duration
    assert ev.hours_match is True and ev.range_consistent is True
    assert not ev.truncated and ev.finish_reason_ok


def test_missing_sections_are_reported_and_lower_the_score():
    text = WELL_FORMED.split("### Riesgos e incertidumbres")[0]
    ev = evaluate_estimation(text, "stop")
    assert ev.sections["riesgos_e_incertidumbres"] is False
    assert ev.sections["preguntas_abiertas"] is False
    assert any("riesgos_e_incertidumbres" in i for i in ev.issues)
    assert ev.score < 1.0


def test_sections_out_of_order_are_flagged():
    text = _replace(WELL_FORMED, "### Supuestos", "### TEMP")
    text = _replace(text, "### Requisitos identificados", "### Supuestos")
    text = _replace(text, "### TEMP", "### Requisitos identificados")
    ev = evaluate_estimation(text, "stop")
    assert all(ev.sections.values())
    assert ev.sections_in_order is False
    assert any("orden" in i for i in ev.issues)


def test_missing_table_is_reported():
    text = _replace(WELL_FORMED, "| # | Área | Tarea | Horas |", "| Tarea | Horas |")
    ev = evaluate_estimation(text, "stop")
    assert ev.has_breakdown_table is False
    assert ev.table_rows == 0
    assert ev.hours_match is None
    assert any("tabla" in i.lower() for i in ev.issues)


def test_total_mismatch_is_detected():
    text = _replace(WELL_FORMED, "**Total estimado:** 292 horas", "**Total estimado:** 310 horas")
    ev = evaluate_estimation(text, "stop")
    assert ev.hours_match is False
    assert ev.declared_total_hours == 310
    assert ev.sum_row_hours_min == 292
    assert any("310" in i and "292" in i for i in ev.issues)


def test_total_within_one_hour_tolerance_is_accepted():
    text = _replace(WELL_FORMED, "**Total estimado:** 292 horas", "**Total estimado:** 293 horas")
    assert evaluate_estimation(text, "stop").hours_match is True


def test_total_outside_recommended_range_is_detected():
    text = _replace(WELL_FORMED, "280–340 horas", "300–340 horas")
    ev = evaluate_estimation(text, "stop")
    assert ev.range_consistent is False
    assert any("rango" in i.lower() for i in ev.issues)


def test_hour_ranges_in_rows_are_summed_as_min_and_max():
    text = (
        "## Estimación: X\n### Desglose de tareas\n\n"
        "| # | Área | Tarea | Horas |\n|---|------|-------|------:|\n"
        "| 1 | A | t1 | 8–12 |\n| 2 | B | t2 | 10 |\n| 3 | C | t3 | 5-7 h |\n\n"
        "### Resumen\n- Total estimado: 27 horas\n- Rango recomendado: 23–29 horas\n"
    )
    ev = evaluate_estimation(text, "stop")
    assert (ev.sum_row_hours_min, ev.sum_row_hours_max) == (23, 29)
    assert ev.table_rows == 3
    assert ev.hours_match is True  # 27 cae dentro de 23–29


def test_total_row_inside_table_is_not_counted_as_a_task():
    text = _replace(
        WELL_FORMED,
        "\n### Resumen",
        "\n| | **Total** | | 292 |\n\n### Resumen",
    )
    ev = evaluate_estimation(text, "stop")
    assert ev.table_rows == 19
    assert ev.hours_match is True


def test_unparseable_hours_cells_are_reported():
    text = _replace(
        WELL_FORMED,
        "| 1 | Diseño | Wireframes y flujos UX (5 pantallas principales) | 24 |",
        "| 1 | Diseño | Wireframes y flujos UX (5 pantallas principales) | varias |",
    )
    ev = evaluate_estimation(text, "stop")
    assert ev.table_rows == 18
    assert any("no interpretable" in i for i in ev.issues)
    assert ev.hours_match is False  # faltan 24 h en la suma


def test_number_formats_thousands_and_decimals():
    text = (
        "## Estimación: X\n### Desglose de tareas\n\n"
        "| # | Área | Tarea | Horas |\n|---|---|---|---|\n"
        "| 1 | A | t | 1.000 |\n| 2 | B | t | 12,5 |\n\n"
        "### Resumen\n- **Total estimado**: 1.012 horas\n"
    )
    ev = evaluate_estimation(text, "stop")
    assert ev.sum_row_hours_min == 1012.5  # 1.000 (miles) + 12,5 (decimal)
    assert ev.declared_total_hours == 1012
    assert ev.hours_match is True


def test_truncated_response_is_flagged_for_both_providers():
    for reason in ("length", "max_tokens"):
        ev = evaluate_estimation(WELL_FORMED[:800], reason)
        assert ev.truncated is True
        assert ev.finish_reason_ok is False
        assert any("truncada" in i for i in ev.issues)


def test_unexpected_finish_reason_is_not_truncation():
    ev = evaluate_estimation(WELL_FORMED, "content_filter")
    assert ev.truncated is False and ev.finish_reason_ok is False
    assert any("content_filter" in i for i in ev.issues)


def test_truncated_preprocessing_phase_is_reported():
    ev = evaluate_estimation(WELL_FORMED, "stop", preprocessing_finish_reason="length")
    assert any("fase 1" in i for i in ev.issues)
    assert ev.truncated is False


def test_empty_text_scores_low_without_crashing():
    ev = evaluate_estimation("", "stop")
    assert not any(ev.sections.values())
    assert ev.sections_in_order is False
    assert ev.score < 0.2
    assert ev.issues
