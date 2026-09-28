"""Cliente HTTP/SSE (`estimator_client`): decodificación SSE y clasificación de resultados."""

import json

import httpx
import pytest

from estimator_client.api import (
    ApiConnectionError,
    ApiServerError,
    ApiValidationError,
    EstimatorApiClient,
)
from estimator_client.config import ClientSettings
from estimator_client.presentation import detail_lines, is_truncated, summary_metrics
from estimator_client.sse import SSEDecoder, iter_sse

# --------------------------------------------------------------------------- decodificador


def test_multiline_data_is_joined_with_newlines_and_one_space_is_stripped():
    raw = "event: delta\ndata:  dos espacios\ndata:\ndata: tercera \n\n"
    [event] = list(iter_sse([raw]))
    assert event.event == "delta"
    assert event.data == " dos espacios\n\ntercera "


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_all_line_terminators(newline):
    raw = f"event: a{newline}data: 1{newline}{newline}event: b{newline}data: 2{newline}{newline}"
    assert [(e.event, e.data) for e in iter_sse([raw])] == [("a", "1"), ("b", "2")]


def test_events_split_across_arbitrary_chunks_including_crlf():
    raw = 'event: delta\r\ndata: {"text": "hola\\nmundo"}\r\n\r\n: keep-alive\r\n\r\n'
    chunks = ["event: delta\r", "\ndata: {\"text\": \"hola\\nmundo\"}\r", "\n\r\n"]
    events = list(iter_sse(chunks))
    assert len(events) == 1 and json.loads(events[0].data) == {"text": "hola\nmundo"}
    events = list(iter_sse([raw[i:i + 3] for i in range(0, len(raw), 3)]))
    assert [e.event for e in events] == ["delta"]


def test_comments_are_ignored_and_default_event_is_message():
    assert [(e.event, e.data) for e in iter_sse([": ping\n\ndata: x\n\n"])] == [("message", "x")]


def test_incomplete_event_at_eof_is_discarded():
    decoder = SSEDecoder()
    assert decoder.feed("event: done\ndata: {}\n") == []  # falta la línea en blanco


def test_unicode_line_separators_are_not_line_breaks():
    [event] = list(iter_sse(["data: a b\u0085c\n\n"]))
    assert event.data == "a b\u0085c"


# --------------------------------------------------------------------------- cliente HTTP


def _client(handler) -> EstimatorApiClient:
    return EstimatorApiClient(httpx.Client(base_url="http://api:8000", transport=httpx.MockTransport(handler)))


def _sse(*events: tuple[str, dict]) -> str:
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events)


def _stream_response(body: str, status=200):
    return httpx.Response(status, headers={"content-type": "text/event-stream"}, text=body)


def test_completed_stream():
    body = _sse(("start", {"request_id": "r1"}), ("delta", {"text": "## A\n"}),
                ("delta", {"text": "  b"}), ("metadata", {"model": "m"}), ("done", {"status": "completed"}))
    stream = _client(lambda req: _stream_response(body)).open_stream({"transcription": "x"})
    assert "".join(stream.text_chunks()) == "## A\n  b"
    assert stream.outcome.completed and stream.outcome.metadata == {"model": "m"}
    assert stream.outcome.request_id == "r1"


def test_error_event_is_not_a_completed_generation():
    body = _sse(("start", {}), ("delta", {"text": "parcial"}),
                ("error", {"code": "stream_interrupted", "message": "m", "partial": True}))
    stream = _client(lambda req: _stream_response(body)).open_stream({})
    assert list(stream.text_chunks()) == ["parcial"]
    assert stream.outcome.status == "error" and not stream.outcome.completed
    assert stream.outcome.error["partial"] is True


def test_stream_closed_without_done_is_interrupted():
    body = _sse(("start", {}), ("delta", {"text": "parcial"})) + "event: metadata\ndata: {"
    stream = _client(lambda req: _stream_response(body)).open_stream({})
    list(stream.text_chunks())
    assert stream.outcome.status == "interrupted" and stream.outcome.metadata is None


def test_network_failure_mid_stream_is_interrupted():
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield b'event: delta\ndata: {"text": "a"}\n\n'
            raise httpx.ReadError("reset")

    handler = lambda req: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Broken())  # noqa: E731
    stream = _client(handler).open_stream({})
    assert list(stream.text_chunks()) == ["a"]
    assert stream.outcome.status == "interrupted"


def test_user_cancellation_is_interrupted():
    body = _sse(("delta", {"text": "a"}), ("delta", {"text": "b"}), ("done", {}))
    stream = _client(lambda req: _stream_response(body)).open_stream({})
    chunks = stream.text_chunks()
    next(chunks)
    chunks.close()  # p. ej. Streamlit detiene el script
    assert stream.outcome.status == "interrupted"


def test_validation_error_before_stream():
    detail = [{"loc": ["body", "transcription"], "msg": "String should have at least 20 characters"}]
    client = _client(lambda req: httpx.Response(422, json={"detail": detail}))
    with pytest.raises(ApiValidationError) as exc:
        client.open_stream({"transcription": "x"})
    assert exc.value.details == ["transcription: String should have at least 20 characters"]


def test_server_error_before_stream():
    client = _client(lambda req: httpx.Response(503, json={"detail": "LLM provider error"}))
    with pytest.raises(ApiServerError) as exc:
        client.open_stream({})
    assert exc.value.status == 503 and exc.value.message == "LLM provider error"


def test_connection_error():
    def refuse(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(ApiConnectionError):
        _client(refuse).open_stream({})
    with pytest.raises(ApiConnectionError):
        _client(refuse).context()


def test_context_query_params_are_serialised():
    seen = {}

    def handler(req):
        seen.update(dict(req.url.params))
        return httpx.Response(200, json={"system_prompt": "p"})

    _client(handler).context({"use_examples": False, "num_examples": 3})
    assert seen == {"use_examples": "false", "num_examples": "3"}


def test_settings_from_env():
    s = ClientSettings.from_env({"ESTIMATOR_API_BASE_URL": "http://api:8000/"})
    assert s.base_url == "http://api:8000"
    assert ClientSettings.from_env({}).base_url == "http://localhost:8000"
    with pytest.raises(ValueError):
        ClientSettings.from_env({"ESTIMATOR_API_BASE_URL": "api:8000"})


def test_presentation_shows_unknown_instead_of_zero():
    meta = {"model": None, "provider": "openai", "latency_ms": 10, "finish_reason": "length",
            "usage": {"input_tokens": None, "output_tokens": 5, "phases": []},
            "cost": {"incurred_usd": None, "original_generation_usd": None, "saved_usd": 0.0},
            "cache": {"status": "hit"}}
    metrics = dict(summary_metrics(meta))
    assert metrics["Tokens de entrada"] == "desconocido"
    assert metrics["Coste de esta solicitud"] == "desconocido"
    assert metrics["Caché"] == "acierto"
    assert any("desconocido" in line for line in detail_lines(meta))
    assert is_truncated(meta)
