from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from tests.conftest import DESCRIPTION, EMPTY_FACTS, FACTS, OUT_OF_SCOPE, RESULT, SYSTEM_PROMPT, reply

APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


def _fresh_app():
    # Windows/CI pueden superar los 3 s por defecto de Streamlit al cargar la interfaz.
    return AppTest.from_file(APP_PATH, default_timeout=10)


def _submit(at, description=DESCRIPTION, *, project=2, detail=2, fmt=1, version=0):
    at.text_area[0].set_value(description)
    at.selectbox[0].select_index(project)
    at.selectbox[1].select_index(detail)
    at.selectbox[2].select_index(fmt)
    at.selectbox[3].select_index(version)
    next(b for b in at.button if b.label == "Estimar").click()
    return at.run()


def test_initial_page_opens_one_conversation_and_shows_form_metadata_panel_and_prompt(api):
    at = _fresh_app().run()

    assert at.exception == []
    assert len(api.conversations) == 1 and at.session_state.conversation_id == api.conversations[0]
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
    assert at.sidebar.text_area[0].value == SYSTEM_PROMPT
    assert api.previews == [
        {"prompt_version": "v3", "project_type": "mobile_app", "detail_level": "medium", "output_format": "phases_table"}
    ]
    sidebar_markdown = " ".join(m.value for m in at.sidebar.markdown)
    assert "Portal de reservas para un gimnasio" in sidebar_markdown
    assert any("Aún no se ha generado" in c.value for c in at.sidebar.caption)


def test_rerunning_the_page_keeps_the_same_conversation_and_the_preview(api):
    at = _fresh_app().run()
    at.run()

    assert len(api.conversations) == 1
    assert len(api.previews) == 1


def test_unreachable_backend_on_load_shows_a_sanitized_error_and_no_form(mocker):
    mocker.patch("estimator_chat.client.httpx.post", side_effect=httpx.ConnectError("private hostname"))
    at = _fresh_app().run()

    assert at.exception == []
    assert "private hostname" not in at.error[0].value and "No se pudo conectar" in at.error[0].value
    assert len(at.text_area) == 0


def test_submit_posts_multipart_to_the_conversation_and_shows_the_structured_result(api):
    at = _submit(_fresh_app().run(), version=2)  # PROMPT_VERSIONS = (v3, v1, v2)

    assert at.exception == []
    [call] = api.estimates
    assert call["url"].endswith(f"/api/conversations/{api.conversations[0]}/estimations")
    assert call["data"] == {
        "description": DESCRIPTION,
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
    # La barra pide al backend el prompt de las opciones de la última solicitud.
    assert api.previews[-1] == {
        "prompt_version": "v2", "project_type": "internal_tool", "detail_level": "detailed", "output_format": "line_items",
    }


def test_project_metadata_panel_shows_the_facts_returned_by_the_backend(api):
    api.facts = FACTS
    at = _submit(_fresh_app().run())

    sidebar = " ".join(m.value for m in at.sidebar.markdown)
    assert "**Nombre:** Vacaciones" in sidebar
    assert "**Equipo supuesto:** 3" in sidebar
    assert "**Tecnologías:** Django, PostgreSQL" in sidebar
    assert "**Alcance acordado:** Calendario y aprobaciones" in sidebar
    assert not any("Aún no hay datos del proyecto" in c.value for c in at.sidebar.caption)


def test_following_submissions_reuse_the_same_conversation(api):
    at = _submit(_fresh_app().run())
    at = _submit(at, description=DESCRIPTION + " Segundo mensaje.")

    assert len(api.conversations) == 1
    assert [e["conversation_id"] for e in api.estimates] == [api.conversations[0]] * 2
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


def test_attachments_allow_a_short_message_and_leave_length_validation_to_the_backend(api):
    at = _fresh_app().run()
    at.file_uploader[1].set_value([("req.pdf", b"%PDF", "application/pdf")])
    at = _submit(at, description="Revisa el PDF")

    assert at.exception == [] and len(at.error) == 0
    assert api.estimates[0]["data"]["description"] == "Revisa el PDF"


def test_new_conversation_opens_another_one_and_resets_the_state(api):
    api.facts = FACTS
    at = _submit(_fresh_app().run())
    first = at.session_state.conversation_id

    at.sidebar.button[0].click().run()

    assert at.exception == []
    assert len(api.conversations) == 2 and at.session_state.conversation_id == api.conversations[1] != first
    assert len(at.chat_message) == 0
    assert at.session_state.last_metrics is None
    assert at.session_state.project_metadata == EMPTY_FACTS
    assert any("Aún no hay datos del proyecto" in c.value for c in at.sidebar.caption)
    at = _submit(at)
    assert api.estimates[-1]["conversation_id"] == api.conversations[1]


def test_expired_conversation_starts_a_new_one_and_warns(api):
    at = _submit(_fresh_app().run())
    api.replies.append(reply(404, {"detail": "La conversación anterior expiró en el servidor."}))

    at = _submit(at, description=DESCRIPTION + " Otra vez.")

    assert at.exception == []
    assert len(api.conversations) == 2 and at.session_state.conversation_id == api.conversations[1]
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


def test_guardrail_rejection_shows_the_backend_detail_and_is_not_saved(api):
    message = "La descripción contiene una dirección de correo electrónico. Elimínala."
    at = _fresh_app().run()
    api.replies.append(reply(422, {"detail": message}))
    at = _submit(at)

    assert at.exception == []
    assert at.error[0].value == message
    assert [m["role"] for m in at.session_state.messages] == ["user"]


def test_attachment_rejection_shows_the_backend_detail(api):
    at = _fresh_app().run()
    api.replies.append(reply(422, {"detail": "Los adjuntos deben ser PDF (.pdf) o Word (.docx)."}))
    at = _submit(at)

    assert at.error[0].value == "Los adjuntos deben ser PDF (.pdf) o Word (.docx)."


def test_backend_error_never_leaks_internal_details(api):
    at = _fresh_app().run()
    api.replies.append(reply(500, {"trace": "Traceback sk-secret http://estimador-cag:8000"}))
    at = _submit(at)

    assert len(at.error) == 1
    for leak in ("Traceback", "sk-secret", "estimador-cag", "8000"):
        assert leak not in at.error[0].value


def test_prompt_preview_failure_shows_a_notice_and_the_page_keeps_working(api):
    api.preview_reply = httpx.ConnectError("private hostname")
    at = _fresh_app().run()

    assert at.exception == []
    assert len(at.sidebar.text_area) == 0
    assert any("contexto del prompt no está disponible" in c.value for c in at.sidebar.caption)
    at = _submit(at)
    assert len(api.estimates) == 1 and at.exception == []


def test_description_field_is_capped_at_80000_chars(api):
    at = _fresh_app().run()

    assert at.exception == []
    assert at.text_area[0].max_chars == 80_000


def test_long_transcription_is_accepted_and_summarised_in_the_chat(api):
    long_text = ("Reunión de planificación del portal de clientes. " * 1700)[:80_000]
    at = _submit(_fresh_app().run(), description=long_text)

    assert at.exception == []
    assert api.estimates[0]["data"]["description"] == long_text
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
    assert api.estimates[0]["data"]["description"] == transcript
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
