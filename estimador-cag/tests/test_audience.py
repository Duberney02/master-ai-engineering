"""Resolución de la audiencia: reglas ordenadas, precedencia de la selección explícita y estado de la sesión."""

import pytest

from app.services.audience import (
    AUDIENCE_RULES,
    SMALL_TEAM_MAX,
    TECH_TERMS_THRESHOLD,
    Audience,
    resolve_audience,
)
from app.services.sessions import ProjectMetadata

PLAIN = "Queremos una aplicación sencilla para que los vecinos reporten incidencias del barrio."
REGULATORY = "Los datos son personales y debemos cumplir el RGPD."
CONFIDENTIAL = "El proyecto es confidencial: hay un NDA firmado con el cliente."
TECHNICAL = "Necesitamos una API REST con PostgreSQL, Docker y un frontend en React."
EMPTY = ProjectMetadata()


def test_the_profiles_are_exactly_executive_pm_developer_and_default():
    assert {a.value for a in Audience} == {"executive", "pm", "developer", "default"}


def test_rules_are_ordered_by_priority():
    assert [r.name for r in AUDIENCE_RULES] == ["confidentiality_or_regulatory", "technical_terms", "small_team"]


@pytest.mark.parametrize("text", [REGULATORY, CONFIDENTIAL, "Debe cumplir la normativa del sector financiero."])
def test_confidentiality_or_regulatory_context_resolves_executive(text):
    resolution = resolve_audience(text, EMPTY)

    assert (resolution.audience, resolution.rule) == (Audience.EXECUTIVE, "confidentiality_or_regulatory")


def test_several_technical_terms_resolve_developer():
    resolution = resolve_audience(TECHNICAL, EMPTY)

    assert (resolution.audience, resolution.rule) == (Audience.DEVELOPER, "technical_terms")


def test_technologies_in_the_metadata_count_as_technical_terms():
    metadata = ProjectMetadata(mentioned_technologies=["Kafka", "Terraform"])

    assert resolve_audience("Necesitamos una API para integrar pedidos.", metadata).audience == Audience.DEVELOPER


def test_fewer_terms_than_the_threshold_are_not_enough():
    assert TECH_TERMS_THRESHOLD == 3
    assert resolve_audience("Una API con PostgreSQL para los pedidos.", EMPTY).audience == Audience.DEFAULT


def test_repeating_the_same_term_does_not_add_up():
    assert resolve_audience("API API API API API REST REST", EMPTY).audience == Audience.DEFAULT


@pytest.mark.parametrize("size", [1, 3, SMALL_TEAM_MAX])
def test_small_team_in_the_metadata_resolves_pm(size):
    resolution = resolve_audience(PLAIN, ProjectMetadata(assumed_team_size=size))

    assert (resolution.audience, resolution.rule) == (Audience.PM, "small_team")


def test_a_large_team_does_not_resolve_pm():
    assert resolve_audience(PLAIN, ProjectMetadata(assumed_team_size=SMALL_TEAM_MAX + 1)).audience == Audience.DEFAULT


def test_no_match_resolves_default():
    resolution = resolve_audience(PLAIN, EMPTY)

    assert (resolution.audience, resolution.rule) == (Audience.DEFAULT, "no_match")


def test_regulatory_beats_technical_and_small_team():
    metadata = ProjectMetadata(assumed_team_size=2)

    assert resolve_audience(f"{TECHNICAL} {REGULATORY}", metadata).rule == "confidentiality_or_regulatory"


def test_technical_beats_small_team():
    assert resolve_audience(TECHNICAL, ProjectMetadata(assumed_team_size=2)).rule == "technical_terms"


@pytest.mark.parametrize("tier", list(Audience) + ["executive", "pm", "developer", "default"])
def test_explicit_tier_prevails_over_every_rule(tier):
    resolution = resolve_audience(f"{TECHNICAL} {REGULATORY}", ProjectMetadata(assumed_team_size=2), explicit=tier)

    assert resolution.audience == Audience(tier) and resolution.rule == "explicit"


def test_unknown_explicit_tier_is_rejected():
    with pytest.raises(ValueError):
        resolve_audience(PLAIN, EMPTY, explicit="ceo")


def test_accents_and_case_do_not_matter():
    assert resolve_audience("Debemos cumplir la PROTECCIÓN DE DATOS.", EMPTY).audience == Audience.EXECUTIVE
