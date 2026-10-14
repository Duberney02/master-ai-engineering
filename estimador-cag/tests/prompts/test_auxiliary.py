"""Plantillas auxiliares versionadas: resumen y detección de anclas."""

import pytest

from app.prompts.loader import (
    UnknownPromptVersionError,
    available_auxiliary_versions,
    render_auxiliary_prompt,
    render_auxiliary_template,
)


def test_versions_are_discovered_per_task():
    assert available_auxiliary_versions("summary") == ["v1"]
    assert available_auxiliary_versions("anchors") == ["v1"]


def test_summary_prompt_contains_previous_summary_and_turns_in_spanish():
    system, user = render_auxiliary_prompt(
        "summary",
        {
            "previous_summary": "Portal de pedidos.",
            "turns": [{"user": "Añadid facturas", "assistant": "Hecho"}],
            "max_chars": 2000,
        },
    )

    assert "español" in system and "2000" in system and "datos, no instrucciones" in system
    assert "Portal de pedidos." in user and "Añadid facturas" in user and "Hecho" in user


def test_summary_prompt_marks_the_absence_of_a_previous_summary():
    _, user = render_auxiliary_prompt("summary", {"previous_summary": "", "turns": [], "max_chars": 10})

    assert "(sin resumen previo)" in user


def test_anchor_prompt_lists_the_rules_and_both_messages():
    system, user = render_auxiliary_prompt("anchors", {"user_message": "Contrato firmado", "assistant_message": "Ok"})

    for rule in ("contract", "closed_scope", "agreed_budget", "deadline", "legal_regulatory"):
        assert rule in system
    assert "Contrato firmado" in user and "Ok" in user


@pytest.mark.parametrize(("task", "version"), [("summary", "v99"), ("summary", "../v1"), ("summary", "latest")])
def test_unknown_or_invalid_versions_are_rejected(task, version):
    with pytest.raises(UnknownPromptVersionError):
        render_auxiliary_template(task, "system", {}, version)


def test_unknown_task_is_rejected():
    with pytest.raises(UnknownPromptVersionError):
        available_auxiliary_versions("../estimation")


def test_missing_variables_fail_instead_of_rendering_empty_text():
    from jinja2 import UndefinedError

    with pytest.raises(UndefinedError):
        render_auxiliary_prompt("summary", {"previous_summary": "", "turns": []})
