from pathlib import Path
from contextlib import contextmanager
import json
import httpx

from streamlit.testing.v1 import AppTest

from tests._fakes import openai_stream_chunks

APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


def _fresh_app(mocker):
    # Windows/CI can exceed Streamlit's 3 s default while loading the UI.
    return AppTest.from_file(APP_PATH, default_timeout=10)


def patch_openai_stream(mocker, chunks):
    """Adapt existing UI fixtures to the HTTP boundary, never call provider SDKs."""
    @contextmanager
    def stream(method, url, **kwargs):
        assert method == "POST"
        assert url.endswith("/api/v1/estimate/stream")
        events = []
        for chunk in chunks:
            if chunk.choices and chunk.choices[0].delta.content:
                events.append(("token", {"text": chunk.choices[0].delta.content}))
            if chunk.usage:
                events.append(("metadata", {"model": chunk.model, "latency_ms": 10, "usage": {
                    "input_tokens": chunk.usage.prompt_tokens,
                    "output_tokens": chunk.usage.completion_tokens,
                }}))
        events.append(("done", {}))
        body = "".join(f"event: {name}\ndata: {json.dumps(value)}\n\n" for name, value in events)
        yield httpx.Response(200, text=body, request=httpx.Request(method, url))
    mocker.patch("app.streamlit_client.httpx.stream", stream)


def test_clear_history_and_metrics(mocker):
    patch_openai_stream(mocker, openai_stream_chunks(["Hola"]))
    at = _fresh_app(mocker).run()
    at.chat_input[0].set_value("Transcripción de prueba suficientemente larga").run()
    at.sidebar.button[0].click().run()
    assert len(at.chat_message) == 0
    assert at.session_state.last_metrics is None


def test_http_error_is_not_saved_as_answer(mocker):
    patch_openai_stream(mocker, openai_stream_chunks(["Hola"]))
    at = _fresh_app(mocker).run()
    at.chat_input[0].set_value("Primera transcripción suficientemente larga").run()
    mocker.patch("app.streamlit_client.httpx.stream", side_effect=httpx.ConnectError("private hostname"))
    at.chat_input[0].set_value("Segunda transcripción suficientemente larga").run()
    assert at.exception == []
    assert len(at.error) == 1
    assert "private hostname" not in at.error[0].value
    assert at.session_state.last_metrics is None
    assert [m["role"] for m in at.session_state.messages] == ["user", "assistant", "user"]


def test_empty_chat_shows_no_messages(mocker):
    at = _fresh_app(mocker).run()

    assert at.exception == []
    assert len(at.chat_message) == 0


def test_sending_message_shows_estimation(mocker):
    patch_openai_stream(mocker, openai_stream_chunks(["## Estimación: Demo"]))
    at = _fresh_app(mocker).run()

    at.chat_input[0].set_value(
        "Transcripción de prueba suficientemente larga para pasar validación"
    ).run()

    assert at.exception == []
    assert len(at.chat_message) == 2
    assert at.chat_message[0].markdown[0].value == (
        "Transcripción de prueba suficientemente larga para pasar validación"
    )
    assert "Estimación" in at.chat_message[1].markdown[0].value


def test_history_persists_across_turns(mocker):
    patch_openai_stream(mocker, openai_stream_chunks(["Respuesta 1"]))
    at = _fresh_app(mocker).run()
    at.chat_input[0].set_value("Primera pregunta suficientemente larga para el test").run()

    patch_openai_stream(mocker, openai_stream_chunks(["Respuesta 2"]))
    at.chat_input[0].set_value("Segunda pregunta suficientemente larga para el test").run()

    assert at.exception == []
    assert len(at.chat_message) == 4
    assert at.chat_message[1].markdown[0].value == "Respuesta 1"
    assert at.chat_message[3].markdown[0].value == "Respuesta 2"


def test_sidebar_shows_prompt_examples_and_metrics(mocker):
    patch_openai_stream(
        mocker,
        openai_stream_chunks(["## Estimación: Demo"], prompt_tokens=111, completion_tokens=22),
    )
    at = _fresh_app(mocker).run()
    at.chat_input[0].set_value(
        "Transcripción de prueba suficientemente larga para pasar validación"
    ).run()

    assert at.exception == []
    prompt_text_areas = [ta.value for ta in at.sidebar.text_area]
    assert any("Senior Software Estimation Architect" in v for v in prompt_text_areas)

    sidebar_markdown = " ".join(m.value for m in at.sidebar.markdown)
    assert "Plataforma de Gestión de Inventario" in sidebar_markdown  # first catalog example

    metric_values = {m.label: m.value for m in at.sidebar.metric}
    assert metric_values["Tokens de entrada"] == "111"
    assert metric_values["Tokens de salida"] == "22"
