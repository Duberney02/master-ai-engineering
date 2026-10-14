# ruff: noqa: F811
"""`tier`, audiencia en la respuesta y `GET /sessions/{id}`."""

import pytest

from app.services.sessions import get_session_store
from tests import test_sessions_api as base
from tests._fakes import openai_settings, patch_settings
from tests.test_sessions_api import TRANSCRIPT, estimate, new_session

llm = base.llm
client = base.client
_fresh_session_store = base._fresh_session_store

REGULATORY = f"{TRANSCRIPT} Los datos son personales y debemos cumplir el RGPD."
TECHNICAL = f"{TRANSCRIPT} Usaremos una API REST con PostgreSQL, Docker y React."


async def test_new_session_state_is_empty(client):
    session_id = await new_session(client)

    response = await client.get(f"/api/v1/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json() == {
        "session_id": session_id,
        "recent_message_count": 0,
        "max_turns": 6,
        "project_metadata": {
            "project_name": None,
            "assumed_team_size": None,
            "mentioned_technologies": [],
            "agreed_scope": None,
        },
        "anchored_message_count": 0,
        "summary_length": 0,
        "last_audience": None,
        "last_audience_rule": None,
    }


async def test_state_reflects_turns_metadata_and_last_audience(client, llm):
    llm.metadata += [{"project_name": "Orion"}, {"project_name": "Orion", "assumed_team_size": 4}]
    session_id = await new_session(client)
    await estimate(client, session_id, REGULATORY)
    await estimate(client, session_id, TRANSCRIPT)

    state = (await client.get(f"/api/v1/sessions/{session_id}")).json()

    assert state["recent_message_count"] == 4 and state["max_turns"] == 6
    assert state["project_metadata"]["project_name"] == "Orion" and state["project_metadata"]["assumed_team_size"] == 4
    # El contexto regulatorio sigue en la memoria de la sesión aunque el segundo turno no lo repita.
    assert state["last_audience"] == "executive" and state["last_audience_rule"] == "confidentiality_or_regulatory"
    assert len(llm.calls) == 4  # consultar el estado no llama al LLM


async def test_state_counts_anchors_and_summary(client, llm, monkeypatch):
    monkeypatch.setenv("SESSION_MAX_TURNS", "1")
    llm.summaries += ["Resumen de ocho caracteres."]
    session_id = await new_session(client)
    await estimate(client, session_id, f"{TRANSCRIPT} El contrato está firmado.")
    await estimate(client, session_id, f"{TRANSCRIPT} uno")
    await estimate(client, session_id, f"{TRANSCRIPT} dos")

    state = (await client.get(f"/api/v1/sessions/{session_id}")).json()

    assert state["recent_message_count"] == 2
    assert state["anchored_message_count"] == 2
    assert state["summary_length"] == len("Resumen de ocho caracteres.")


async def test_unknown_session_state_is_404(client):
    assert (await client.get("/api/v1/sessions/00000000-0000-4000-8000-000000000000")).status_code == 404
    assert (await client.get("/api/v1/sessions/no-es-un-uuid")).status_code == 404


async def test_response_reports_the_audience_and_the_rule(client, llm):
    session_id = await new_session(client)

    body = (await estimate(client, session_id, TECHNICAL)).json()

    assert body["audience"] == "developer" and body["audience_rule"] == "technical_terms"
    assert "La estimación la leerá el equipo de ingeniería" in llm.estimation_calls[0][0]["content"]


async def test_default_audience_when_no_rule_matches(client, llm):
    body = (await estimate(client, await new_session(client))).json()

    assert body["audience"] == "default" and body["audience_rule"] == "no_match"


async def test_explicit_tier_prevails_and_is_kept_as_the_last_audience(client, llm):
    session_id = await new_session(client)

    body = (await estimate(client, session_id, REGULATORY, tier="pm")).json()

    assert body["audience"] == "pm" and body["audience_rule"] == "explicit"
    assert "la leerá la gestión del proyecto".lower() in llm.estimation_calls[0][0]["content"].lower()
    session = get_session_store().get(session_id)
    assert (session.audience, session.audience_rule) == ("pm", "explicit")


@pytest.mark.parametrize("tier", ["ceo", "EXECUTIVE-ish"])
async def test_invalid_tier_is_a_422_and_does_not_touch_the_session(client, llm, tier):
    session_id = await new_session(client)

    response = await estimate(client, session_id, TRANSCRIPT, tier=tier)

    assert response.status_code == 422 and llm.calls == []
    assert get_session_store().get(session_id).audience is None


async def test_blank_tier_is_ignored(client, llm):
    response = await estimate(client, await new_session(client), TRANSCRIPT, tier="")

    assert response.status_code == 200 and response.json()["audience_rule"] == "no_match"


async def test_failed_turn_keeps_the_previous_audience(client, llm):
    session_id = await new_session(client)
    await estimate(client, session_id, REGULATORY)
    broken = base.estimation() | {"total_cost_eur": 1}
    llm.estimations += [broken, broken, broken]

    failed = await estimate(client, session_id, TECHNICAL)

    assert failed.status_code == 502
    session = get_session_store().get(session_id)
    assert (session.audience, session.audience_rule) == ("executive", "confidentiality_or_regulatory")


async def test_prompt_version_defaults_to_the_configured_one_and_can_be_overridden(client, llm, mocker):
    default = await estimate(client, await new_session(client))
    assert default.json()["prompt_version"] == "v4"

    patch_settings(mocker, openai_settings(moderation_enabled=False, conversation_prompt_version="v3"))
    configured = await estimate(client, await new_session(client))
    explicit = await estimate(client, await new_session(client), prompt_version="v2")

    assert configured.json()["prompt_version"] == "v3"
    assert explicit.json()["prompt_version"] == "v2"
