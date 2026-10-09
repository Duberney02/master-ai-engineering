"""Pruebas del template v2: variación deliberada de tono y ejemplos respecto a v1."""

import re

from app.prompts.loader import render_estimation_prompt
from tests.prompts.test_estimation_v1 import PER_PHASE_ASSUMPTIONS, make_request


def test_v2_differs_from_v1_in_tone_and_examples():
    request = make_request()
    v1_system, _ = render_estimation_prompt(request, version="v1")
    v2_system, _ = render_estimation_prompt(request, version="v2")

    assert v1_system != v2_system
    assert "consultor de preventa" in v2_system
    assert "**En una frase:**" in v2_system
    assert "Plataforma de citas para clínicas veterinarias" in v2_system
    assert "App de reservas para una cadena de gimnasios" not in v2_system
    assert len(re.findall(r"^### Ejemplo \d+:", v2_system, re.M)) == 2


def test_v2_respects_format_and_detail():
    table, _ = render_estimation_prompt(make_request(output_format="phases_table"), version="v2")
    narrative, _ = render_estimation_prompt(make_request(output_format="narrative"), version="v2")
    detailed, _ = render_estimation_prompt(make_request(detail_level="detailed"), version="v2")
    summary, _ = render_estimation_prompt(make_request(detail_level="summary"), version="v2")

    assert "| confidence_pct |" in table and "| confidence_pct |" not in narrative
    assert PER_PHASE_ASSUMPTIONS in detailed and PER_PHASE_ASSUMPTIONS not in summary


def test_v2_user_prompt_keeps_description_block_and_references():
    request = make_request(
        reference_projects=[
            {"name": "Intranet", "description": "Portal de empleados", "actual_hours": 300},
        ]
    )
    _, user = render_estimation_prompt(request, version="v2")

    assert f"<project_description>\n{request.description}\n</project_description>" in user
    assert "- Intranet: Portal de empleados — 300 h reales" in user
