# ruff: noqa: F811
"""Memoria ampliada de extremo a extremo: resumen acumulativo, anclas y asociación con la conversación."""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from app.main import app
from app.services.history import EstimationHistory, get_history
from app.services.sessions import get_session_store
from tests import test_sessions_api as base
from tests._fakes import openai_settings
from tests.test_sessions_api import TRANSCRIPT, estimate, new_session

# Fixtures de las pruebas de sesión (LLM guionizado, cliente ASGI y almacén limpio).
llm = base.llm
client = base.client
_fresh_session_store = base._fresh_session_store

COMMITMENT = "El presupuesto acordado es de 45.000 euros y la fecha límite es el 15 de marzo."


@pytest.fixture(autouse=True)
def _small_window(monkeypatch):
    monkeypatch.setenv("SESSION_MAX_TURNS", "2")


async def test_turns_leaving_the_window_are_summarized_and_the_summary_reaches_the_next_estimate(client, llm):
    llm.summaries += ["Quieren un portal de pedidos.", "Portal de pedidos con facturas."]
    session_id = await new_session(client)

    for n in range(1, 5):
        assert (await estimate(client, session_id, f"{TRANSCRIPT} MARCA-{n}.")).status_code == 200

    session = get_session_store().get(session_id)
    assert session.history.summary == "Portal de pedidos con facturas."
    assert len(llm.summary_calls) == 2
    # Segunda compresión: recibe el resumen anterior y el turno recién retirado.
    summary_user = llm.summary_calls[1][1]["content"]
    assert "Quieren un portal de pedidos." in summary_user and "MARCA-2." in summary_user
    # La quinta estimación ve el resumen en el mensaje de sistema, sin los turnos retirados.
    await estimate(client, session_id, f"{TRANSCRIPT} MARCA-5.")
    sent = llm.estimation_calls[-1]
    assert "<conversation_summary>\nPortal de pedidos con facturas." in sent[0]["content"]
    users = "\n".join(m["content"] for m in sent if m["role"] == "user")
    assert "MARCA-1." not in users and "MARCA-5." in users


async def test_commitment_turn_is_kept_as_an_anchor_after_leaving_the_window(client, llm):
    session_id = await new_session(client)
    await estimate(client, session_id, f"{TRANSCRIPT} {COMMITMENT}")
    for n in range(2, 6):
        await estimate(client, session_id, f"{TRANSCRIPT} MARCA-{n}.")

    session = get_session_store().get(session_id)
    assert [a.rules for a in session.history.anchors] == [("agreed_budget", "deadline")]
    # El turno ancla no se resume.
    assert all("45.000" not in call[1]["content"] for call in llm.summary_calls)
    # Y sigue en los mensajes del turno siguiente, antes de la ventana reciente.
    await estimate(client, session_id, f"{TRANSCRIPT} MARCA-6.")
    sent = llm.estimation_calls[-1]
    assert "45.000 euros" in sent[1]["content"] and sent[1]["role"] == "user" and sent[2]["role"] == "assistant"
    assert len(session.history) == 2


async def test_summarizer_failure_does_not_fail_the_estimate_and_keeps_the_previous_summary(client, llm):
    llm.summaries += ["Resumen válido."]
    session_id = await new_session(client)
    for n in range(1, 4):
        await estimate(client, session_id, f"{TRANSCRIPT} MARCA-{n}.")
    assert get_session_store().get(session_id).history.summary == "Resumen válido."

    llm.summaries += [""]  # un resumen vacío cuenta como fallo
    response = await estimate(client, session_id, f"{TRANSCRIPT} MARCA-4.")

    assert response.status_code == 200
    assert get_session_store().get(session_id).history.summary == "Resumen válido."


async def test_estimations_are_stored_with_their_conversation_and_metadata_snapshot(client, llm):
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    history = EstimationHistory(openai_settings(), engine=engine)
    app.dependency_overrides[get_history] = lambda: history
    try:
        llm.metadata += [{"project_name": "Orion"}, {"project_name": "Orion", "assumed_team_size": 3}]
        session_id = await new_session(client)
        other_id = await new_session(client)
        await estimate(client, session_id, f"{TRANSCRIPT} uno")
        second = await estimate(client, session_id, f"{TRANSCRIPT} dos")
        await estimate(client, other_id, f"{TRANSCRIPT} tres")

        latest = await history.latest_for_conversation(session_id)
    finally:
        app.dependency_overrides.pop(get_history, None)
        await engine.dispose()

    assert latest.id == second.json()["estimation_id"] and latest.conversation_id == session_id
    assert latest.metadata_snapshot["project_name"] == "Orion" and latest.metadata_snapshot["assumed_team_size"] == 3
