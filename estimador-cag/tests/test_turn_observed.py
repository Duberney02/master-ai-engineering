# ruff: noqa: F811
"""Evento `turn_observed` y `last_turn` en `GET /sessions/{id}`: una observación por turno confirmado."""

import pytest
from structlog.testing import capture_logs

from tests import test_sessions_api as base
from tests._documents import make_pdf
from tests.test_sessions_api import TRANSCRIPT, estimate, new_session

llm = base.llm
client = base.client
_fresh_session_store = base._fresh_session_store

OBSERVED_FIELDS = {
    "turn_index",
    "session_id",
    "enriched_transcript_chars",
    "attachments_total_chars",
    "messages_in_window",
    "anchors_count",
    "summary_chars",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "latency_ms",
    "cache_hit_kind",
    "last_resolved_tier",
}


def observed(logs: list[dict]) -> list[dict]:
    return [entry for entry in logs if entry["event"] == "turn_observed"]


async def test_first_turn_emits_turn_observed_with_every_field(client, llm):
    session_id = await new_session(client)

    with capture_logs() as logs:
        response = await estimate(client, session_id)

    assert response.status_code == 200
    (event,) = observed(logs)
    assert OBSERVED_FIELDS <= event.keys()
    assert event["turn_index"] == 1 and event["session_id"] == session_id
    assert event["enriched_transcript_chars"] == len(TRANSCRIPT) and event["attachments_total_chars"] == 0
    assert event["messages_in_window"] == 2 and event["anchors_count"] == 0 and event["summary_chars"] == 0
    # Estimación + extracción de metadatos: 2 llamadas de 100 tokens de entrada y 50 de salida.
    assert event["tokens_in"] == 200 and event["tokens_out"] == 100
    assert event["cache_hit_kind"] == "none" and event["last_resolved_tier"] == "default"
    assert event["latency_ms"] >= 0


async def test_event_never_contains_conversation_text(client, llm):
    session_id = await new_session(client)

    with capture_logs() as logs:
        await estimate(client, session_id)

    (event,) = observed(logs)
    assert TRANSCRIPT not in " ".join(str(value) for value in event.values())


async def test_attachment_characters_are_counted_separately(client, llm):
    session_id = await new_session(client)
    pdf = ("informe.pdf", make_pdf("Alcance cerrado con integracion SAP"), "application/pdf")

    with capture_logs() as logs:
        await estimate(client, session_id, files=[pdf])

    (event,) = observed(logs)
    assert event["attachments_total_chars"] > 0
    assert event["enriched_transcript_chars"] > event["attachments_total_chars"] + len(TRANSCRIPT)


async def test_turn_index_keeps_counting_beyond_the_window(client, llm):
    session_id = await new_session(client)

    with capture_logs() as logs:
        for _ in range(9):
            assert (await estimate(client, session_id)).status_code == 200

    events = observed(logs)
    assert [e["turn_index"] for e in events] == list(range(1, 10))
    assert events[-1]["messages_in_window"] == 12  # 6 turnos de ventana, medido tras la compresión


async def test_failed_turn_emits_nothing_and_does_not_consume_an_index(client, llm):
    llm.estimations += ["no es json"] * 3
    session_id = await new_session(client)

    with capture_logs() as logs:
        failed = await estimate(client, session_id)
        retried = await estimate(client, session_id)

    assert failed.status_code == 502 and retried.status_code == 200
    assert [e["turn_index"] for e in observed(logs)] == [1]


async def test_state_embeds_the_same_observation_as_last_turn(client, llm):
    session_id = await new_session(client)
    assert (await client.get(f"/api/v1/sessions/{session_id}")).json()["last_turn"] is None

    with capture_logs() as logs:
        await estimate(client, session_id)
        await estimate(client, session_id)

    state = (await client.get(f"/api/v1/sessions/{session_id}")).json()
    assert state["last_turn"] == {key: observed(logs)[-1][key] for key in OBSERVED_FIELDS}
    assert state["last_turn"]["turn_index"] == 2


async def test_memory_text_is_only_returned_on_request(client, llm):
    llm.summaries += ["Resumen del cliente Zafiro."] * 5
    session_id = await new_session(client)
    for _ in range(8):  # 8 turnos con ventana de 6: dos salen de la ventana y se resumen
        await estimate(client, session_id)

    default = (await client.get(f"/api/v1/sessions/{session_id}")).json()
    with_memory = (await client.get(f"/api/v1/sessions/{session_id}", params={"include_memory": "true"})).json()

    assert default["summary"] is None and default["anchors"] is None
    assert default["summary_length"] > 0
    assert "Zafiro" in with_memory["summary"] and with_memory["anchors"] == []
    assert with_memory["last_turn"]["summary_chars"] == default["summary_length"]


@pytest.mark.parametrize("turns", [1, 3])
async def test_every_confirmed_turn_has_one_event(client, llm, turns):
    session_id = await new_session(client)

    with capture_logs() as logs:
        for _ in range(turns):
            await estimate(client, session_id)

    assert len(observed(logs)) == turns
