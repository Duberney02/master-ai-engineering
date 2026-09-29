"""Pruebas del template v1: renderizan en milisegundos y nunca llaman al modelo."""

import re

import pytest

from app.prompts.loader import render_estimation_prompt
from app.schemas import EstimationRequest

DESCRIPTION = (
    "Aplicación web para que una red de bibliotecas gestione préstamos, "
    "reservas y avisos de devolución por correo."
)
PER_PHASE_ASSUMPTIONS = "Para cada fase, lista explícitamente las asunciones"


def make_request(**overrides) -> EstimationRequest:
    fields = {
        "description": DESCRIPTION,
        "project_type": "web_saas",
        "detail_level": "medium",
        "output_format": "phases_table",
    }
    return EstimationRequest(**(fields | overrides))


def test_user_prompt_wraps_description_literally():
    description = "Portal <interno> con \"comillas\", {llaves} y\nun salto de línea para RRHH."
    _, user = render_estimation_prompt(make_request(description=description))

    block = re.search(r"<project_description>\n(.*)\n</project_description>", user, re.S)
    assert block is not None
    assert block.group(1) == description


def test_phases_table_mentions_confidence_pct_and_narrative_does_not():
    table_system, _ = render_estimation_prompt(make_request(output_format="phases_table"))
    narrative_system, _ = render_estimation_prompt(make_request(output_format="narrative"))

    assert "confidence_pct" in table_system
    assert "confidence_pct" not in narrative_system


def test_line_items_format_instruction_only_for_line_items():
    items_system, _ = render_estimation_prompt(make_request(output_format="line_items"))
    table_system, _ = render_estimation_prompt(make_request(output_format="phases_table"))

    assert "- [Fase] Tarea — N h" in items_system
    assert "- [Fase] Tarea — N h" not in table_system


def test_detailed_asks_for_assumptions_per_phase_and_summary_does_not():
    detailed_system, _ = render_estimation_prompt(make_request(detail_level="detailed"))
    summary_system, _ = render_estimation_prompt(make_request(detail_level="summary"))

    assert PER_PHASE_ASSUMPTIONS in detailed_system
    assert "Asunciones por fase:" in detailed_system  # los ejemplos lo muestran
    assert PER_PHASE_ASSUMPTIONS not in summary_system
    assert "Asunciones por fase:" not in summary_system


def test_system_includes_three_examples():
    system, _ = render_estimation_prompt(make_request())

    assert len(re.findall(r"^### Ejemplo \d+:", system, re.M)) == 3


def test_reference_projects_are_listed_when_present():
    request = make_request(reference_projects=[
        {"name": "Portal de socios", "description": "Altas y cuotas", "actual_hours": 640},
        {"name": "Agenda de salas", "description": "Reservas internas", "actual_hours": 212.5},
    ])
    _, user = render_estimation_prompt(request)

    block = user[user.index("<reference_projects>"):user.index("</reference_projects>")]
    assert "Portal de socios (640 h reales): Altas y cuotas" in block
    assert "Agenda de salas (212.5 h reales): Reservas internas" in block


@pytest.mark.parametrize("references", [None, []])
def test_reference_block_absent_without_projects(references):
    _, user = render_estimation_prompt(make_request(reference_projects=references))

    assert "<reference_projects>" not in user


@pytest.mark.parametrize("project_type", ["mobile_app", "web_saas", "internal_tool", "data_pipeline"])
@pytest.mark.parametrize("detail_level", ["summary", "medium", "detailed"])
@pytest.mark.parametrize("output_format", ["phases_table", "line_items", "narrative"])
def test_every_combination_renders_without_leftover_markup(project_type, detail_level, output_format):
    system, user = render_estimation_prompt(make_request(
        project_type=project_type, detail_level=detail_level, output_format=output_format,
    ))

    for text in (system, user):
        assert "{{" not in text and "{%" not in text
        assert "\n\n\n" not in text
    assert f"Tipo de proyecto: {project_type}" in user
