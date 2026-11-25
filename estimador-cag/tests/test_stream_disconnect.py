"""Caracterización de la desconexión ASGI durante las dos rutas SSE públicas."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from app.dependencies import get_history, get_pipeline
from app.main import app


@pytest.mark.parametrize("structured", [True, False], ids=["estructurada", "transcripcion"])
async def test_disconnect_closes_inflight_work(mocker, structured):
    started = asyncio.Event()
    closed = asyncio.Event()
    token_sent = asyncio.Event()

    async def wait_for_disconnect():
        started.set()
        try:
            await asyncio.Future()
        finally:
            closed.set()

    async def transcription_stream(*_args):
        yield "Primer fragmento"
        await wait_for_disconnect()

    async def structured_run(_request, _version, *, input_checked):
        assert input_checked is True
        await wait_for_disconnect()

    save = AsyncMock()
    pipeline = mocker.Mock(check_input=AsyncMock(), run=AsyncMock(side_effect=structured_run))
    history = mocker.Mock(save=save)
    mocker.patch.dict(app.dependency_overrides, {get_pipeline: lambda: pipeline, get_history: lambda: history})
    mocker.patch("app.api.estimations.generate_estimation_stream", transcription_stream)

    description = "El cliente solicita un portal para gestionar pedidos y facturas."
    if structured:
        path = "/api/v1/estimate/stream"
        payload = {
            "description": description,
            "project_type": "web_saas",
            "detail_level": "medium",
            "output_format": "phases_table",
        }
    else:
        path = "/api/v1/transcription/estimate/stream"
        payload = {"transcription": description}

    messages = []

    async def send(message):
        messages.append(message)
        if b"event: token" in message.get("body", b""):
            token_sent.set()

    request_received = False

    async def receive():
        nonlocal request_received
        if not request_received:
            request_received = True
            return {"type": "http.request", "body": json.dumps(payload).encode(), "more_body": False}
        await started.wait()
        if not structured:
            await token_sent.wait()
        return {"type": "http.disconnect"}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
    }
    await asyncio.wait_for(app(scope, receive, send), timeout=5)

    assert messages[0]["type"] == "http.response.start"
    assert messages[0]["status"] == 200
    # Un cierre del transporte puede añadir un cuerpo vacío sin emitir ningún evento SSE.
    body = b"".join(message["body"] for message in messages if message["type"] == "http.response.body")
    expected = b"" if structured else b'event: token\ndata: {"text": "Primer fragmento"}\n\n'
    assert body == expected
    assert closed.is_set()
    save.assert_not_awaited()
