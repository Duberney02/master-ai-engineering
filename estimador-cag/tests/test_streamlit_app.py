import json
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from app.prompts.loader import render_estimation_prompt
from app.schemas import EstimationRequest, EstimationResult
from app.streamlit_client import EstimationStreamError, request_structured_estimation
from app.streamlit_support import few_shot_examples

APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")
DESCRIPTION = "Herramienta interna para planificar las vacaciones del equipo de soporte."
RESULT = {
    "summary": "Proyecto pequeño con calendario y aprobaciones.",
    "confidence_pct": 80,
    "phases": [
        {"name": "Diseño", "description": "Pantallas", "duration_weeks": 1, "cost_eur": 2400},
        {"name": "Desarrollo", "description": "Calendario", "duration_weeks": 4, "cost_eur": 9600},
    ],
    "total_duration_weeks": 5,
    "total_cost_eur": 12000,
}
OUT_OF_SCOPE = {
    "summary": "Out of scope: faltan procesos y objetivos.",
    "confidence_pct": 10,
    "phases": [{"name": "No estimable", "description": "x", "duration_weeks": 1, "cost_eur": 0}],
    "total_duration_weeks": 1,
    "total_cost_eur": 0,
}


def _fresh_app():
    # Windows/CI can exceed Streamlit's 3 s default while loading the UI.
    return AppTest.from_file(APP_PATH, default_timeout=10)


def _metadata(prompt_version="v3", input_tokens=111, output_tokens=22, **overrides):
    return {
        "prompt_version": prompt_version, "model": "gpt-4o-mini", "provider": "openai",
        "finish_reason": "stop", "latency_ms": 10, "cache_hit": False,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                  "total_tokens": input_tokens + output_tokens},
        "estimated_cost_usd": None, "request_cost_usd": None,
    } | overrides


def patch_stream(mocker, result=RESULT, metadata=None, *, final="done", status=200, body=None):
    """Simula el SSE de la API en la frontera HTTP; nunca invoca SDK de proveedores."""
    calls = []

    @contextmanager
    def stream(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if status != 200:
            yield httpx.Response(status, json=body, request=httpx.Request(method, url))
            return
        events = []
        if result is not None:
            events.append(("result", result))
        if metadata is not None:
            events.append(("metadata", metadata))
        if final:
            events.append((final, {}))
        text = "".join(f"event: {name}\ndata: {json.dumps(value)}\n\n" for name, value in events)
        yield httpx.Response(200, text=text, request=httpx.Request(method, url))

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
    assert "## Contrato de salida (JSON)" in system_prompt
    sidebar_markdown = " ".join(m.value for m in at.sidebar.markdown)
    assert "Portal de reservas para un gimnasio" in sidebar_markdown
    assert any("Aún no se ha generado" in c.value for c in at.sidebar.caption)


def test_submit_requests_typed_estimation_and_shows_structured_result(mocker):
    calls = patch_stream(mocker, RESULT, _metadata("v2"))
    at = _submit(_fresh_app().run(), version=2)  # PROMPT_VERSIONS = (v3, v1, v2)

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
    assistant = at.chat_message[1]
    assert RESULT["summary"] in assistant.markdown[0].value
    assert [m.label for m in assistant.metric] == ["Confianza", "Duración total", "Coste total"]
    assert [m.value for m in assistant.metric] == ["80%", "5 semanas", "12,000.00 EUR"]
    assert list(assistant.dataframe[0].value["Fase"]) == ["Diseño", "Desarrollo"]
    assert not at.warning

    metrics = {m.label: m.value for m in at.sidebar.metric}
    assert metrics["Tokens de entrada"] == "111"
    assert metrics["Tokens de salida"] == "22"
    assert metrics["Versión del prompt"] == "v2"
    system_prompt = at.sidebar.text_area[0].value
    assert "consultor de preventa" in system_prompt  # plantillas v2 de la última solicitud


def test_out_of_scope_is_presented_as_not_estimable_without_figures(mocker):
    patch_stream(mocker, OUT_OF_SCOPE, _metadata())
    at = _submit(_fresh_app().run())

    assert at.exception == []
    assert "No estimable" in at.warning[0].value
    assert "faltan procesos y objetivos" in at.warning[0].value
    assistant = at.chat_message[1]
    assert len(assistant.metric) == 0 and len(assistant.dataframe) == 0
    assert at.session_state.last_metrics["prompt_version"] == "v3"


def test_history_persists_across_submissions_and_can_be_cleared(mocker):
    patch_stream(mocker, RESULT | {"summary": "Respuesta 1"}, _metadata())
    at = _submit(_fresh_app().run())
    patch_stream(mocker, RESULT | {"summary": "Respuesta 2"}, _metadata())
    at = _submit(at, description=DESCRIPTION + " Segunda versión.")

    assert len(at.chat_message) == 4
    assert "Respuesta 1" in at.chat_message[1].markdown[0].value
    assert "Respuesta 2" in at.chat_message[3].markdown[0].value

    at.sidebar.button[0].click().run()

    assert len(at.chat_message) == 0
    assert at.session_state.last_metrics is None


def test_short_description_shows_validation_error_without_http(mocker):
    calls = patch_stream(mocker, RESULT, _metadata())
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


def test_guardrail_rejection_shows_server_message_and_is_not_saved(mocker):
    message = "La descripción contiene una dirección de correo electrónico. Elimínala."
    patch_stream(mocker, status=400, body={"reason": "pii_email", "message": message})
    at = _submit(_fresh_app().run())

    assert at.exception == []
    assert at.error[0].value == message
    assert [m["role"] for m in at.session_state.messages] == ["user"]


def _request() -> EstimationRequest:
    return EstimationRequest(
        description=DESCRIPTION, project_type="web_saas",
        detail_level="summary", output_format="narrative",
    )


def test_structured_client_returns_validated_result_and_metadata(mocker):
    patch_stream(mocker, RESULT, _metadata())

    result, metadata = request_structured_estimation(_request(), "http://api/")

    assert result == EstimationResult.model_validate(RESULT)
    assert metadata.prompt_version == "v3" and metadata.usage.total_tokens == 133


@pytest.mark.parametrize("result, metadata, final", [
    (RESULT, None, "error"),                      # error del servidor
    (RESULT, _metadata(), None),                  # conexión cortada sin done
    (RESULT, {"model": "x"}, "done"),             # metadatos fuera del contrato
    ({"summary": "x"}, _metadata(), "done"),      # resultado fuera del contrato
    (None, _metadata(), "done"),                  # sin resultado
])
def test_structured_client_never_accepts_incomplete_streams(mocker, result, metadata, final):
    patch_stream(mocker, result, metadata, final=final)
    with pytest.raises(EstimationStreamError):
        request_structured_estimation(_request(), "http://api/")


def test_few_shot_examples_are_extracted_from_the_rendered_prompt():
    system, _ = render_estimation_prompt(_request(), version="v1")

    examples = few_shot_examples(system)

    assert [title for title, _ in examples] == [
        "App de reservas para una cadena de gimnasios",
        "Portal SaaS de facturación para despachos contables",
        "Pipeline diario de ventas hacia un data warehouse",
    ]
    assert examples[0][1].startswith("Aplicación iOS y Android")
    v3_titles = [t for t, _ in few_shot_examples(render_estimation_prompt(_request())[0])]
    assert v3_titles == ["Portal de reservas para un gimnasio", "Plataforma de IA para todo el hospital"]
