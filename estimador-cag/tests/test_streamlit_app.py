from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests._fakes import openai_settings, openai_stream_chunks, patch_openai_stream, patch_settings

APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


def _fresh_app(mocker):
    patch_settings(mocker, openai_settings())
    return AppTest.from_file(APP_PATH)


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
