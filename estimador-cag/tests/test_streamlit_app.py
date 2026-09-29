import json
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from app.schemas import EstimationRequest
from app.streamlit_client import EstimationStreamError, stream_structured_estimation
from app.streamlit_support import few_shot_examples
from app.prompts.loader import render_estimation_prompt

APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")
DESCRIPTION = "Herramienta interna para planificar las vacaciones del equipo de soporte."


def _fresh_app():
    # Windows/CI can exceed Streamlit's 3 s default while loading the UI.
    return AppTest.from_file(APP_PATH, default_timeout=10)


def _metadata(prompt_version="v1", input_tokens=111, output_tokens=22, **overrides):
    return {
        "prompt_version": prompt_version, "model": "gpt-4o-mini", "provider": "openai",
        "finish_reason": "stop", "latency_ms": 10, "cache_hit": False,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "total_tokens": input_tokens + output_tokens},
        "estimated_cost_usd": None, "request_cost_usd": None,
    } | overrides


def patch_stream(mocker, tokens, metadata=None, *, final="done"):
    """Simula el SSE de la API en la frontera HTTP; nunca invoca SDK de proveedores."""
    calls = []

    @contextmanager
    def stream(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        events = [("token", {"text": t}) for t in tokens]
        if metadata is not None:
            events.append(("metadata", metadata))
        if final:
            events.append((final, {}))
        body = "".join(f"event: {name}\ndata: {json.dumps(value)}\n\n" for name, value in events)
        yield httpx.Response(200, text=body, request=httpx.Request(method, url))

    mocker.patch("app.streamlit_client.httpx.stream", stream)
    return calls


def _submit(at, description=DESCRIPTION, *, project=2, detail=2, fmt=1, version=0):
    at.text_area[0].set_value(description)
    at.selectbox[0].select_index(project)
    at.selectbox[1].select_index(detail)
    at.selectbox[2].select_index(fmt)
    at.selectbox[3].select_index(version)
    next(b for b in at.button if b.label == "Estimar").click()
    return at.run()


def test_initial_page_shows_form_prompt_preview_and_examples():
    at = _fresh_app().run()

    assert at.exception == []
    assert len(at.chat_message) == 0
    assert [s.label for s in at.selectbox] == [
        "Tipo de proyecto", "Nivel de detalle", "Formato de salida", "Versión del prompt",
    ]
    system_prompt = at.sidebar.text_area[0].value
    assert "arquitecto sénior de estimación" in system_prompt
    sidebar_markdown = " ".join(m.value for m in at.sidebar.markdown)
    assert "App de reservas para una cadena de gimnasios" in sidebar_markdown
    assert any("Aún no se ha generado" in c.value for c in at.sidebar.caption)


def test_submit_streams_typed_request_and_updates_sidebar(mocker):
    calls = patch_stream(mocker, ["## Estimación", ": Vacaciones"], _metadata("v2"))
    at = _submit(_fresh_app().run(), version=1)

    assert at.exception == []
    assert len(calls) == 1
    assert calls[0]["url"].endswith("/api/v1/estimate/stream")
    assert calls[0]["params"] == {"prompt_version": "v2"}
    assert calls[0]["json"] == EstimationRequest(
        description=DESCRIPTION, project_type="internal_tool",
        detail_level="detailed", output_format="line_items",
    ).model_dump(mode="json")

    assert len(at.chat_message) == 2
    assert DESCRIPTION in at.chat_message[0].markdown[0].value
    assert at.chat_message[1].markdown[0].value == "## Estimación: Vacaciones"

    metrics = {m.label: m.value for m in at.sidebar.metric}
    assert metrics["Tokens de entrada"] == "111"
    assert metrics["Tokens de salida"] == "22"
    assert metrics["Versión del prompt"] == "v2"
    system_prompt = at.sidebar.text_area[0].value
    assert "consultor de preventa" in system_prompt  # plantillas v2 de la última solicitud
    assert "- [Fase] Tarea — N h" in system_prompt  # formato line_items
    sidebar_markdown = " ".join(m.value for m in at.sidebar.markdown)
    assert "Plataforma de citas para clínicas veterinarias" in sidebar_markdown


def test_history_persists_across_submissions_and_can_be_cleared(mocker):
    patch_stream(mocker, ["Respuesta 1"], _metadata())
    at = _submit(_fresh_app().run())
    patch_stream(mocker, ["Respuesta 2"], _metadata())
    at = _submit(at, description=DESCRIPTION + " Segunda versión.")

    assert len(at.chat_message) == 4
    assert at.chat_message[1].markdown[0].value == "Respuesta 1"
    assert at.chat_message[3].markdown[0].value == "Respuesta 2"

    at.sidebar.button[0].click().run()

    assert len(at.chat_message) == 0
    assert at.session_state.last_metrics is None


def test_short_description_shows_validation_error_without_http(mocker):
    calls = patch_stream(mocker, ["x"], _metadata())
    at = _submit(_fresh_app().run(), description="Muy corta")

    assert at.exception == []
    assert calls == []
    assert "20 y 2000 caracteres" in at.error[0].value
    assert len(at.chat_message) == 0


def test_network_error_is_sanitized_and_not_saved_as_answer(mocker):
    mocker.patch("app.streamlit_client.httpx.stream", side_effect=httpx.ConnectError("private hostname"))
    at = _submit(_fresh_app().run())

    assert at.exception == []
    assert len(at.error) == 1
    assert "private hostname" not in at.error[0].value
    assert at.session_state.last_metrics is None
    assert [m["role"] for m in at.session_state.messages] == ["user"]


def _request() -> EstimationRequest:
    return EstimationRequest(
        description=DESCRIPTION, project_type="web_saas",
        detail_level="summary", output_format="narrative",
    )


@pytest.mark.parametrize("tokens, metadata, final", [
    (["parcial"], None, "error"),           # error del servidor tras texto parcial
    (["parcial"], _metadata(), None),       # conexión cortada sin done
    (["texto"], {"model": "x"}, "done"),    # metadatos fuera del contrato
])
def test_structured_client_never_accepts_incomplete_streams(mocker, tokens, metadata, final):
    patch_stream(mocker, tokens, metadata, final=final)
    metrics = {"old": 1}
    with pytest.raises(EstimationStreamError):
        list(stream_structured_estimation(_request(), "http://api/", metrics))
    assert metrics == {}


def test_few_shot_examples_are_extracted_from_the_rendered_prompt():
    system, _ = render_estimation_prompt(_request(), version="v1")

    examples = few_shot_examples(system)

    assert [title for title, _ in examples] == [
        "App de reservas para una cadena de gimnasios",
        "Portal SaaS de facturación para despachos contables",
        "Pipeline diario de ventas hacia un data warehouse",
    ]
    assert examples[0][1].startswith("Aplicación iOS y Android")
