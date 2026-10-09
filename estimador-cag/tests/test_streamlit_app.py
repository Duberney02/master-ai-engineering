import json
import uuid
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from app.prompts.loader import render_estimation_prompt
from app.schemas import EstimationRequest, EstimationResult
from app.streamlit_client import (
    EstimationStreamError,
    SessionExpiredError,
    create_session,
    request_session_estimation,
    request_structured_estimation,
)
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
EMPTY_FACTS = {"project_name": None, "assumed_team_size": None, "mentioned_technologies": [], "agreed_scope": None}
FACTS = {
    "project_name": "Vacaciones",
    "assumed_team_size": 3,
    "mentioned_technologies": ["Django", "PostgreSQL"],
    "agreed_scope": "Calendario y aprobaciones",
}


def _fresh_app():
    # Windows/CI can exceed Streamlit's 3 s default while loading the UI.
    return AppTest.from_file(APP_PATH, default_timeout=10)


def _metadata(prompt_version="v3", input_tokens=111, output_tokens=22, **overrides):
    return {
        "prompt_version": prompt_version,
        "model": "gpt-4o-mini",
        "provider": "openai",
        "finish_reason": "stop",
        "latency_ms": 10,
        "cache_hit": False,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
        "estimated_cost_usd": None,
        "request_cost_usd": None,
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


def session_body(session_id, result=RESULT, facts=EMPTY_FACTS, prompt_version="v3", turn=1, **metrics):
    metrics_body = _metadata(**metrics)
    metrics_body.pop("prompt_version")
    return {
        "result": result | {"out_of_scope": result["confidence_pct"] < 30},
        "prompt_version": prompt_version,
        "cached": False,
        "cache_source": "none",
        "estimation_id": None,
        "metrics": metrics_body,
        "session_id": session_id,
        "project_metadata": facts,
        "turn_count": turn,
        "max_turns": 6,
    }


class FakeApi:
    """API de sesiones simulada en la frontera HTTP (`httpx.post` del cliente)."""

    def __init__(self, mocker):
        self.sessions: list[str] = []
        self.estimates: list[dict] = []
        self.replies: list = []  # `httpx.Response` o excepción por estimación; vacío = respuesta correcta
        self.facts = EMPTY_FACTS
        self.result = RESULT
        mocker.patch("app.streamlit_client.httpx.post", self.post)

    def post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        if url.endswith("/api/v1/sessions"):
            self.sessions.append(str(uuid.uuid4()))
            return httpx.Response(201, json={"session_id": self.sessions[-1]}, request=request)
        session_id = url.split("/sessions/")[1].split("/")[0]
        self.estimates.append({"url": url, "session_id": session_id, **kwargs})
        if self.replies:
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        body = session_body(session_id, self.result, self.facts, kwargs["data"]["prompt_version"], len(self.estimates))
        return httpx.Response(200, json=body, request=request)


@pytest.fixture
def api(mocker) -> FakeApi:
    return FakeApi(mocker)


def reply(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("POST", "http://api"))


def _submit(at, description=DESCRIPTION, *, project=2, detail=2, fmt=1, version=0):
    at.text_area[0].set_value(description)
    at.selectbox[0].select_index(project)
    at.selectbox[1].select_index(detail)
    at.selectbox[2].select_index(fmt)
    at.selectbox[3].select_index(version)
    next(b for b in at.button if b.label == "Estimar").click()
    return at.run()


def test_initial_page_creates_one_session_and_shows_form_metadata_panel_and_prompt(api):
    at = _fresh_app().run()

    assert at.exception == []
    assert len(api.sessions) == 1 and at.session_state.session_id == api.sessions[0]
    assert len(at.chat_message) == 0
    assert [s.label for s in at.selectbox] == [
        "Tipo de proyecto",
        "Nivel de detalle",
        "Formato de salida",
        "Versión del prompt",
    ]
    assert [b.label for b in at.sidebar.button] == ["Nueva conversación"]
    assert [u.label for u in at.file_uploader][1].startswith("Adjuntos (PDF o Word")
    assert at.file_uploader[1].accept_multiple_files and at.file_uploader[1].allowed_type == [".pdf", ".docx"]
    assert any("Aún no hay datos del proyecto" in c.value for c in at.sidebar.caption)
    system_prompt = at.sidebar.text_area[0].value
    assert "arquitecto sénior de estimación" in system_prompt
    assert "## Contrato de salida (JSON)" in system_prompt
    assert "<project_metadata>\n</project_metadata>" in system_prompt
    sidebar_markdown = " ".join(m.value for m in at.sidebar.markdown)
    assert "Portal de reservas para un gimnasio" in sidebar_markdown
    assert any("Aún no se ha generado" in c.value for c in at.sidebar.caption)


def test_rerunning_the_page_keeps_the_same_session(api):
    at = _fresh_app().run()
    at.run()

    assert len(api.sessions) == 1


def test_unreachable_api_on_load_shows_a_sanitized_error_and_no_form(mocker):
    mocker.patch("app.streamlit_client.httpx.post", side_effect=httpx.ConnectError("private hostname"))
    at = _fresh_app().run()

    assert at.exception == []
    assert "private hostname" not in at.error[0].value and "No se pudo conectar" in at.error[0].value
    assert len(at.text_area) == 0


def test_submit_posts_multipart_to_the_session_and_shows_the_structured_result(api):
    at = _submit(_fresh_app().run(), version=2)  # PROMPT_VERSIONS = (v3, v1, v2)

    assert at.exception == []
    [call] = api.estimates
    assert call["url"].endswith(f"/api/v1/sessions/{api.sessions[0]}/estimate")
    assert call["data"] == {
        "transcript": DESCRIPTION,
        "project_type": "internal_tool",
        "detail_level": "detailed",
        "output_format": "line_items",
        "prompt_version": "v2",
    }
    assert call["files"] is None

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


def test_project_metadata_panel_shows_the_facts_returned_by_the_api(api):
    api.facts = FACTS
    at = _submit(_fresh_app().run())

    sidebar = " ".join(m.value for m in at.sidebar.markdown)
    assert "**Nombre:** Vacaciones" in sidebar
    assert "**Equipo supuesto:** 3" in sidebar
    assert "**Tecnologías:** Django, PostgreSQL" in sidebar
    assert "**Alcance acordado:** Calendario y aprobaciones" in sidebar
    assert not any("Aún no hay datos del proyecto" in c.value for c in at.sidebar.caption)
    # La barra muestra el prompt que recibirá el siguiente turno, ya con los hechos conocidos.
    assert "- Nombre del proyecto: Vacaciones" in at.sidebar.text_area[0].value


def test_following_submissions_reuse_the_same_session(api):
    at = _submit(_fresh_app().run())
    at = _submit(at, description=DESCRIPTION + " Segundo mensaje.")

    assert len(api.sessions) == 1
    assert [e["session_id"] for e in api.estimates] == [api.sessions[0]] * 2
    assert len(at.chat_message) == 4


def test_several_attachments_are_sent_as_multipart_files(api):
    at = _fresh_app().run()
    at.file_uploader[1].set_value(
        [
            ("requisitos.pdf", b"%PDF-1.4 uno", "application/pdf"),
            ("alcance.docx", b"PK dos", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ]
    )
    at = _submit(at)

    assert at.exception == []
    assert api.estimates[0]["files"] == [
        ("attachments", ("requisitos.pdf", b"%PDF-1.4 uno")),
        ("attachments", ("alcance.docx", b"PK dos")),
    ]
    assert "`requisitos.pdf`, `alcance.docx`" in at.chat_message[0].markdown[0].value


def test_attachments_allow_a_short_message_and_leave_length_validation_to_the_server(api):
    at = _fresh_app().run()
    at.file_uploader[1].set_value([("req.pdf", b"%PDF", "application/pdf")])
    at = _submit(at, description="Revisa el PDF")

    assert at.exception == [] and len(at.error) == 0
    assert api.estimates[0]["data"]["transcript"] == "Revisa el PDF"


def test_new_conversation_creates_another_session_and_resets_the_state(api):
    api.facts = FACTS
    at = _submit(_fresh_app().run())
    first = at.session_state.session_id

    at.sidebar.button[0].click().run()

    assert at.exception == []
    assert len(api.sessions) == 2 and at.session_state.session_id == api.sessions[1] != first
    assert len(at.chat_message) == 0
    assert at.session_state.last_metrics is None
    assert at.session_state.project_metadata == EMPTY_FACTS
    assert any("Aún no hay datos del proyecto" in c.value for c in at.sidebar.caption)
    assert "- Nombre del proyecto" not in at.sidebar.text_area[0].value
    at = _submit(at)
    assert api.estimates[-1]["session_id"] == api.sessions[1]


def test_expired_session_starts_a_new_conversation_and_warns(api):
    at = _submit(_fresh_app().run())
    api.replies.append(reply(404, {"detail": "Session not found or expired"}))

    at = _submit(at, description=DESCRIPTION + " Otra vez.")

    assert at.exception == []
    assert len(api.sessions) == 2 and at.session_state.session_id == api.sessions[1]
    assert "expiró" in at.warning[0].value
    assert at.session_state.messages == []
    assert len(at.error) == 0


def test_out_of_scope_is_presented_as_not_estimable_without_figures(api):
    api.result = OUT_OF_SCOPE
    at = _submit(_fresh_app().run())

    assert at.exception == []
    assert "No estimable" in at.warning[0].value
    assert "faltan procesos y objetivos" in at.warning[0].value
    assistant = at.chat_message[1]
    assert len(assistant.metric) == 0 and len(assistant.dataframe) == 0
    assert at.session_state.last_metrics["prompt_version"] == "v3"


def test_history_persists_across_submissions(api):
    api.result = RESULT | {"summary": "Respuesta 1"}
    at = _submit(_fresh_app().run())
    api.result = RESULT | {"summary": "Respuesta 2"}
    at = _submit(at, description=DESCRIPTION + " Segunda versión.")

    assert len(at.chat_message) == 4
    assert "Respuesta 1" in at.chat_message[1].markdown[0].value
    assert "Respuesta 2" in at.chat_message[3].markdown[0].value


def test_short_description_shows_validation_error_without_http(api):
    at = _submit(_fresh_app().run(), description="Muy corta")

    assert at.exception == []
    assert api.estimates == []
    assert "20 y 80000 caracteres" in at.error[0].value
    assert len(at.chat_message) == 0


def test_network_error_is_sanitized_and_not_saved_as_answer(api):
    at = _fresh_app().run()
    api.replies.append(httpx.ConnectError("private hostname"))
    at = _submit(at)

    assert at.exception == []
    assert len(at.error) == 1
    assert "private hostname" not in at.error[0].value
    assert at.session_state.last_metrics is None
    assert [m["role"] for m in at.session_state.messages] == ["user"]


def test_guardrail_rejection_shows_server_message_and_is_not_saved(api):
    message = "La descripción contiene una dirección de correo electrónico. Elimínala."
    at = _fresh_app().run()
    api.replies.append(reply(400, {"reason": "pii_email", "message": message}))
    at = _submit(at)

    assert at.exception == []
    assert at.error[0].value == message
    assert [m["role"] for m in at.session_state.messages] == ["user"]


def test_attachment_rejection_shows_the_server_message(api):
    at = _fresh_app().run()
    api.replies.append(reply(415, {"detail": "Solo se admiten adjuntos PDF (.pdf) y Word (.docx)."}))
    at = _submit(at)

    assert at.error[0].value == "Solo se admiten adjuntos PDF (.pdf) y Word (.docx)."


def _request() -> EstimationRequest:
    return EstimationRequest(
        description=DESCRIPTION,
        project_type="web_saas",
        detail_level="summary",
        output_format="narrative",
    )


def test_structured_client_returns_validated_result_and_metadata(mocker):
    patch_stream(mocker, RESULT, _metadata())

    result, metadata = request_structured_estimation(_request(), "http://api/")

    assert result == EstimationResult.model_validate(RESULT)
    assert metadata.prompt_version == "v3" and metadata.usage.total_tokens == 133


@pytest.mark.parametrize(
    "result, metadata, final",
    [
        (RESULT, None, "error"),  # error del servidor
        (RESULT, _metadata(), None),  # conexión cortada sin done
        (RESULT, {"model": "x"}, "done"),  # metadatos fuera del contrato
        ({"summary": "x"}, _metadata(), "done"),  # resultado fuera del contrato
        (None, _metadata(), "done"),  # sin resultado
    ],
)
def test_structured_client_never_accepts_incomplete_streams(mocker, result, metadata, final):
    patch_stream(mocker, result, metadata, final=final)
    with pytest.raises(EstimationStreamError):
        request_structured_estimation(_request(), "http://api/")


def _estimate_call(**overrides):
    kwargs = {
        "transcript": DESCRIPTION,
        "project_type": "web_saas",
        "detail_level": "summary",
        "output_format": "narrative",
    }
    return request_session_estimation("http://api/", str(uuid.uuid4()), **(kwargs | overrides))


def test_create_session_returns_the_session_id(api):
    session_id = create_session("http://api/")

    assert len(api.sessions) == 1 and session_id == api.sessions[0]


def test_create_session_rejects_an_invalid_body(mocker):
    mocker.patch("app.streamlit_client.httpx.post", return_value=reply(201, {"otro": 1}))

    with pytest.raises(EstimationStreamError, match="inválidos"):
        create_session("http://api")


def test_session_client_returns_the_validated_response(api):
    api.facts = FACTS

    response = _estimate_call()

    assert response.result == EstimationResult.model_validate(RESULT)
    assert response.project_metadata.project_name == "Vacaciones" and response.turn_count == 1


def test_session_client_sends_no_files_part_without_attachments(api):
    _estimate_call()
    _estimate_call(attachments=[("a.pdf", b"x")])

    assert api.estimates[0]["files"] is None
    assert api.estimates[1]["files"] == [("attachments", ("a.pdf", b"x"))]


def test_session_client_maps_404_to_session_expired(mocker):
    mocker.patch("app.streamlit_client.httpx.post", return_value=reply(404, {"detail": "x"}))

    with pytest.raises(SessionExpiredError):
        _estimate_call()


@pytest.mark.parametrize(
    "status, body, expected",
    [
        (400, {"reason": "pii_email", "message": "Elimina el correo."}, "Elimina el correo."),
        (413, {"detail": "Cada adjunto puede pesar como máximo 10 MB."}, "Cada adjunto puede pesar como máximo 10 MB."),
        (
            422,
            {"detail": [{"loc": ["body"], "msg": "x", "input": "texto privado"}]},
            "La API rechazó la solicitud (HTTP 422).",
        ),
        (
            502,
            {"detail": "LLM returned an invalid estimation"},
            "La API no pudo completar la estimación. Intenta de nuevo.",
        ),
        (418, {}, "La API rechazó la solicitud (HTTP 418)."),
    ],
)
def test_session_client_sanitizes_error_responses(mocker, status, body, expected):
    mocker.patch("app.streamlit_client.httpx.post", return_value=reply(status, body))

    with pytest.raises(EstimationStreamError) as exc:
        _estimate_call()

    assert str(exc.value) == expected


def test_session_client_rejects_bodies_outside_the_contract(mocker):
    mocker.patch("app.streamlit_client.httpx.post", return_value=reply(200, {"result": {"summary": "x"}}))

    with pytest.raises(EstimationStreamError, match="inválidos"):
        _estimate_call()


def test_session_client_connection_failure_is_sanitized(mocker):
    mocker.patch("app.streamlit_client.httpx.post", side_effect=httpx.ConnectError("private hostname"))

    with pytest.raises(EstimationStreamError) as exc:
        _estimate_call()

    assert "private hostname" not in str(exc.value)


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


def test_description_field_is_capped_at_80000_chars(api):
    at = _fresh_app().run()

    assert at.exception == []
    assert at.text_area[0].max_chars == 80_000


def test_long_transcription_is_accepted_and_summarised_in_the_chat(api):
    long_text = ("Reunión de planificación del portal de clientes. " * 1700)[:80_000]
    at = _submit(_fresh_app().run(), description=long_text)

    assert at.exception == []
    assert api.estimates[0]["data"]["transcript"] == long_text
    user_message = at.chat_message[0].markdown[0].value
    assert len(user_message) < 1_000 and "80,000 caracteres" in user_message


def test_elapsed_time_is_shown_with_the_result(api):
    at = _submit(_fresh_app().run())

    assert any(c.value.startswith("Tiempo: ") and c.value.endswith(" s") for c in at.chat_message[1].caption)
    assert at.session_state.messages[-1]["elapsed"] >= 0


def test_form_offers_a_txt_uploader(api):
    at = _fresh_app().run()

    assert at.exception == []
    assert any("transcripción (.txt" in str(el) for el in at.main)


def _upload(at, content: bytes, name="reunion.txt"):
    at.file_uploader[0].upload(name, content, "text/plain")
    return at


def test_uploaded_txt_replaces_the_description(api):
    transcript = "Reunión de kickoff: el cliente pide un portal de facturación con incidencias."
    at = _upload(_fresh_app().run(), transcript.encode("utf-8"))

    at = _submit(at, description="texto que se ignora")

    assert at.exception == []
    assert api.estimates[0]["data"]["transcript"] == transcript
    assert len(at.error) == 0


def test_uploaded_file_with_invalid_encoding_is_rejected_without_http(api):
    at = _upload(_fresh_app().run(), "Reunión de planificación del portal".encode("latin-1"))

    at = _submit(at)

    assert at.exception == []
    assert api.estimates == []
    assert "UTF-8" in at.error[0].value


def test_uploaded_file_shorter_than_20_chars_shows_the_range_message(api):
    at = _submit(_upload(_fresh_app().run(), b"corto"))

    assert api.estimates == [] and "20 y 80000 caracteres" in at.error[0].value
