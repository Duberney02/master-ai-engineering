"""Plantillas v3 (salida estructurada) y contrato JSON compartido con v1/v2."""

import json
import re

import pytest

from app.prompts.loader import DEFAULT_PROMPT_VERSION, OUTPUT_CONTRACT_MARKER, render_estimation_prompt
from app.services.validation import validate_text
from tests.prompts.test_estimation_v1 import make_request


def test_v3_is_the_default_version():
    assert DEFAULT_PROMPT_VERSION == "v3"
    assert render_estimation_prompt(make_request()) == render_estimation_prompt(make_request(), "v3")


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
def test_every_version_carries_the_json_contract_exactly_once(version):
    system, _ = render_estimation_prompt(make_request(), version)

    assert system.count(OUTPUT_CONTRACT_MARKER) == 1
    assert "Out of scope:" in system and "suma de `cost_eur`" in system


def test_v3_adapts_instructions_to_format_and_detail():
    table, _ = render_estimation_prompt(make_request(output_format="phases_table"), "v3")
    items, _ = render_estimation_prompt(make_request(output_format="line_items"), "v3")
    narrative, _ = render_estimation_prompt(make_request(output_format="narrative"), "v3")
    detailed, _ = render_estimation_prompt(make_request(detail_level="detailed"), "v3")
    summary, _ = render_estimation_prompt(make_request(detail_level="summary"), "v3")

    assert "tabla de fases" in table and "tabla de fases" not in narrative
    assert "`Tarea (N h)`" in items and "`Tarea (N h)`" not in table
    assert "como una narración" in narrative
    assert "preguntas abiertas" in detailed and "preguntas abiertas" not in summary
    assert "máximo 150 palabras" in summary and "máximo 150 palabras" not in detailed


def test_v3_examples_are_valid_results_and_include_an_out_of_scope_one():
    system, _ = render_estimation_prompt(make_request(), "v3")
    examples = [json.loads(line) for line in system.splitlines() if line.startswith('{"summary"')]

    assert len(examples) == 2
    results = [validate_text(json.dumps(example)) for example in examples]
    assert [r.out_of_scope for r in results] == [False, True]
    assert len(re.findall(r"^### Ejemplo \d+:", system, re.M)) == 2


def test_v3_user_prompt_wraps_description_and_references():
    request = make_request(
        reference_projects=[{"name": "Portal de socios", "description": "Altas", "actual_hours": 640}]
    )
    _, user = render_estimation_prompt(request, "v3")

    assert f"<project_description>\n{request.description}\n</project_description>" in user
    assert "Portal de socios (640 h reales): Altas" in user
