"""Plantilla v4: enfoque por audiencia manteniendo el español y el contrato estructurado."""

import pytest

from app.prompts.loader import OUTPUT_CONTRACT_MARKER, available_versions, render_system_prompt
from tests.prompts.test_estimation_v1 import make_request

FOCUS = {
    "executive": "la leerá la dirección",
    "pm": "la leerá la gestión del proyecto",
    "developer": "la leerá el equipo de ingeniería",
    "default": "audiencia general",
}


def system(audience: str, version: str = "v4") -> str:
    return render_system_prompt(make_request(), version, None, audience)


def test_v4_is_available_and_v3_stays_the_default_of_the_stateless_endpoint():
    from app.prompts.loader import DEFAULT_PROMPT_VERSION

    assert "v4" in available_versions() and DEFAULT_PROMPT_VERSION == "v3"


@pytest.mark.parametrize("audience", FOCUS)
def test_each_audience_gets_only_its_own_focus(audience):
    text = system(audience)

    assert FOCUS[audience] in text
    assert all(marker not in text for other, marker in FOCUS.items() if other != audience)


def test_executive_focus_is_risks_synthesis_and_accessible_language():
    text = system("executive")

    assert "riesgos" in text and "síntesis" in text and "accesible" in text


def test_pm_focus_is_milestones_deliverables_and_dependencies():
    text = system("pm")

    assert "hitos" in text and "entregables" in text and "dependencias" in text


def test_developer_focus_is_technologies_integrations_and_technical_assumptions():
    text = system("developer")

    assert "tecnologías" in text and "integraciones" in text and "supuestos técnicos" in text


@pytest.mark.parametrize("audience", FOCUS)
def test_v4_keeps_spanish_and_the_structured_contract_exactly_once(audience):
    text = system(audience)

    assert text.count(OUTPUT_CONTRACT_MARKER) == 1
    assert "respondes siempre en español" in text and "Out of scope:" in text


def test_v4_without_a_given_audience_uses_the_general_focus():
    assert FOCUS["default"] in render_system_prompt(make_request(), "v4")


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
def test_previous_versions_ignore_the_audience(version):
    base = render_system_prompt(make_request(), version)

    assert "## Audiencia" not in base
    assert render_system_prompt(make_request(), version, None, "executive") == base


def test_v4_includes_the_session_metadata_block_like_the_other_versions():
    from app.services.sessions import ProjectMetadata

    text = render_system_prompt(make_request(), "v4", ProjectMetadata(project_name="Orion"), "pm")

    assert "- Nombre del proyecto: Orion" in text
