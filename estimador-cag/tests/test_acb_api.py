# ruff: noqa: F811
"""`POST /sessions/{id}/estimate-acb`: mismo contrato que el endpoint normal más la traza de auditoría."""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.main import app
from app.services.history import EstimationHistory, get_history
from app.services.sessions import get_session_store
from tests import test_sessions_api as base
from tests._acb import needs_iteration, reject
from tests._fakes import openai_settings
from tests.test_sessions_api import TRANSCRIPT, estimation, new_session

llm = base.llm
client = base.client
_fresh_session_store = base._fresh_session_store


async def estimate_acb(client, session_id, transcript=TRANSCRIPT, files=None, **form):
    return await client.post(
        f"/api/v1/sessions/{session_id}/estimate-acb",
        data={"transcript": transcript, **base.FORM, **form},
        files=[("attachments", f) for f in files or []] or None,
    )


async def test_accepted_estimate_has_the_normal_contract_plus_the_audit_trace(client, llm):
    session_id = await new_session(client)

    response = await estimate_acb(client, session_id)

    assert response.status_code == 200
    body = response.json()
    normal = (await base.estimate(client, await new_session(client))).json()
    assert set(normal) <= set(body) and set(body) - set(normal) == {"audit_trace"}
    assert body["turn_count"] == 1 and body["session_id"] == session_id and body["result"]["total_cost_eur"] == 20000
    assert body["audit_trace"] == {
        "iterations": [
            {
                "iteration": 1,
                "critic_verdict": "accept",
                "critic_confidence": 0.9,
                "defects": {"critical": 0, "major": 0, "minor": 0, "categories": []},
                "boss_decision": "accept",
                "critic_error": False,
            }
        ],
        "total_iterations": 1,
        "final_decision": "accepted",
        "reservations": [],
    }


async def test_regenerates_with_feedback_and_returns_the_final_estimate_with_a_complete_trace(client, llm):
    llm.critic += [needs_iteration("Falta QA.", "Añadir una fase de QA."), {"verdict": "accept", "confidence": 0.8}]
    llm.estimations += [estimation("Sin QA."), estimation("Con QA.")]
    session_id = await new_session(client)

    body = (await estimate_acb(client, session_id)).json()

    assert body["result"]["summary"] == "Con QA." and body["audit_trace"]["total_iterations"] == 2
    assert [i["boss_decision"] for i in body["audit_trace"]["iterations"]] == ["regenerate", "accept"]
    assert body["audit_trace"]["iterations"][0]["defects"]["major"] == 1
    second = llm.estimation_calls[1]
    assert "Añadir una fase de QA." in second[-1]["content"] and second[-1]["role"] == "user"
    # Un único turno en la sesión, con el mensaje del usuario original.
    session = get_session_store().get(body["session_id"])
    assert len(session.history) == 1 and body["turn_count"] == 1
    assert "Falta QA." not in str(session.history.turns)


async def test_exhausted_iterations_return_the_last_draft_with_reservations(client, llm):

    llm.critic += [needs_iteration(f"Defecto {n}.") for n in range(1, 6)]
    llm.estimations += [estimation(f"Borrador {n}.") for n in range(1, 6)]
    session_id = await new_session(client)

    response = await estimate_acb(client, session_id)

    trace = response.json()["audit_trace"]
    assert response.status_code == 200 and trace["total_iterations"] == 3  # BOSS_MAX_ITERATIONS por defecto
    assert trace["final_decision"] == "returned_with_reservations" and trace["reservations"]
    assert response.json()["result"]["summary"] == "Borrador 3."


async def test_rejected_estimate_is_returned_with_the_reservation(client, llm):
    llm.critic += [reject("No describe un proyecto.")]
    session_id = await new_session(client)

    body = (await estimate_acb(client, session_id)).json()

    assert body["audit_trace"]["final_decision"] == "returned_with_reservations"
    assert body["audit_trace"]["reservations"] == ["No describe un proyecto."]
    assert len(llm.estimation_calls) == 1


async def test_tier_is_accepted_and_reported(client, llm):
    body = (await estimate_acb(client, await new_session(client), tier="executive")).json()

    assert body["audience"] == "executive" and body["audience_rule"] == "explicit"


@pytest.mark.parametrize(("setup", "status"), [("unknown_session", 404), ("bad_tier", 422), ("short_text", 422)])
async def test_errors_match_the_normal_endpoint_and_never_call_the_llm(client, llm, setup, status):
    session_id = "00000000-0000-4000-8000-000000000000" if setup == "unknown_session" else await new_session(client)
    form = {"tier": "ceo"} if setup == "bad_tier" else {}
    text = "corto" if setup == "short_text" else TRANSCRIPT

    response = await estimate_acb(client, session_id, text, **form)

    assert response.status_code == status and llm.calls == []


async def test_guardrail_violation_is_a_400(client, llm):
    response = await estimate_acb(client, await new_session(client), f"{TRANSCRIPT} Mi correo es persona@example.com")

    assert response.status_code == 400 and response.json()["reason"] and llm.calls == []


async def test_invalid_actor_output_is_a_502_and_leaves_the_session_untouched(client, llm):
    broken = estimation() | {"total_cost_eur": 1}
    llm.estimations += [broken, broken, broken]
    session_id = await new_session(client)

    response = await estimate_acb(client, session_id)

    assert response.status_code == 502
    assert len(get_session_store().get(session_id).history) == 0


async def test_attachments_work_like_in_the_normal_endpoint(client, llm):
    from tests._documents import make_pdf

    pdf = ("req.pdf", make_pdf("Requisito: integrar con Kafka"), "application/pdf")

    response = await estimate_acb(client, await new_session(client), files=[pdf])

    assert response.status_code == 200
    assert "Requisito: integrar con Kafka" in llm.estimation_calls[0][-1]["content"]


async def test_only_the_final_estimation_is_stored_in_the_history(client, llm):
    llm.critic += [needs_iteration(), needs_iteration(), {"verdict": "accept", "confidence": 0.7}]
    llm.estimations += [estimation("Uno."), estimation("Dos."), estimation("Tres.")]
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    history = EstimationHistory(openai_settings(), engine=engine)
    app.dependency_overrides[get_history] = lambda: history
    try:
        session_id = await new_session(client)
        body = (await estimate_acb(client, session_id)).json()
        stored = await history.list_recent(10)
        latest = await history.latest_for_conversation(session_id)
    finally:
        app.dependency_overrides.pop(get_history, None)
        await engine.dispose()

    assert len(stored) == 1 and body["estimation_id"] == stored[0].id
    assert latest.result.summary == "Tres." and latest.conversation_id == session_id


async def test_normal_endpoint_is_unchanged_and_makes_no_critic_calls(client, llm):
    response = await base.estimate(client, await new_session(client))

    assert response.status_code == 200 and "audit_trace" not in response.json()
    assert not [c for c in llm.calls if base.CRITIC_MARKER in c[0]["content"]]


async def test_the_openapi_schema_documents_the_new_endpoint(client):
    schema = (await client.get("/openapi.json")).json()

    operation = schema["paths"]["/api/v1/sessions/{session_id}/estimate-acb"]["post"]
    assert "AcbEstimationResponse" in str(operation["responses"]["200"])
