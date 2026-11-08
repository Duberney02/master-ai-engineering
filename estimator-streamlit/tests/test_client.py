import httpx
import pytest

from estimator_chat.client import (
    ConversationExpiredError,
    EstimationError,
    create_conversation,
    fetch_prompt_preview,
    request_estimation,
)
from tests.conftest import DESCRIPTION, FACTS, PREVIEW, RESULT, estimation_body, reply

BASE = "http://backend:3000"
OPTIONS = {"project_type": "web_saas", "detail_level": "medium", "output_format": "phases_table", "prompt_version": "v3"}


def _estimate(**overrides):
    return request_estimation(BASE, "abc", description=DESCRIPTION, **(OPTIONS | overrides))


def test_create_conversation_returns_the_conversation_id(api):
    assert create_conversation(BASE) == api.conversations[0]


@pytest.mark.parametrize("body", [{}, {"conversation_id": 5}, {"conversation_id": ""}, ["x"]])
def test_create_conversation_rejects_an_invalid_body(mocker, body):
    mocker.patch("estimator_chat.client.httpx.post", return_value=reply(201, body))
    with pytest.raises(EstimationError, match="inválidos"):
        create_conversation(BASE)


def test_create_conversation_maps_failures(mocker):
    mocker.patch("estimator_chat.client.httpx.post", return_value=reply(502, {"detail": "El servicio no pudo completar la solicitud."}))
    with pytest.raises(EstimationError, match="no pudo completar"):
        create_conversation(BASE)
    mocker.patch("estimator_chat.client.httpx.post", side_effect=httpx.ConnectError("private"))
    with pytest.raises(EstimationError, match="No se pudo conectar") as caught:
        create_conversation(BASE)
    assert "private" not in str(caught.value)


def test_request_estimation_returns_the_validated_response(api):
    api.facts = FACTS

    response = _estimate()

    assert response.result.summary == RESULT["summary"] and response.result.total_cost_eur == 12000
    assert response.project_metadata.mentioned_technologies == ["Django", "PostgreSQL"]
    assert api.estimates[0]["url"] == f"{BASE}/api/conversations/abc/estimations"
    assert api.estimates[0]["data"]["description"] == DESCRIPTION


def test_request_estimation_sends_no_files_part_without_attachments_and_one_per_file_with_them(api):
    _estimate()
    request_estimation(BASE, "abc", description="x", attachments=[("a.pdf", b"1"), ("b.docx", b"2")], **OPTIONS)

    assert api.estimates[0]["files"] is None
    assert api.estimates[1]["files"] == [("attachments", ("a.pdf", b"1")), ("attachments", ("b.docx", b"2"))]


def test_request_estimation_maps_404_to_conversation_expired(mocker):
    mocker.patch("estimator_chat.client.httpx.post", return_value=reply(404, {"detail": "expiró"}))
    with pytest.raises(ConversationExpiredError):
        _estimate()


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (422, {"detail": "La descripción debe tener entre 20 y 80000 caracteres."}, "La descripción debe tener entre 20 y 80000 caracteres."),
        (413, {"detail": "Cada adjunto puede pesar como máximo 10 MB."}, "Cada adjunto puede pesar como máximo 10 MB."),
        (422, {"detail": [{"loc": ["body"], "input": "texto privado"}]}, "El backend rechazó la solicitud (HTTP 422)."),
        (422, {"detail": "m" * 500}, "m" * 300),
        (502, {"detail": "La API del estimador no pudo completar la solicitud. Inténtalo de nuevo."}, "no pudo completar"),
        (500, {}, "El backend rechazó la solicitud (HTTP 500)."),
        (418, "no json", "El backend rechazó la solicitud (HTTP 418)."),
    ],
)
def test_request_estimation_sanitizes_error_responses(mocker, status, body, expected):
    mocker.patch("estimator_chat.client.httpx.post", return_value=reply(status, body))
    with pytest.raises(EstimationError) as caught:
        _estimate()
    assert expected in str(caught.value)
    assert not isinstance(caught.value, ConversationExpiredError)


def test_request_estimation_rejects_bodies_outside_the_contract(mocker):
    for body in ({"sin": "result"}, estimation_body() | {"project_metadata": "x"}, [1]):
        mocker.patch("estimator_chat.client.httpx.post", return_value=reply(200, body))
        with pytest.raises(EstimationError, match="inválidos"):
            _estimate()
    mocker.patch(
        "estimator_chat.client.httpx.post",
        return_value=httpx.Response(200, text="<html>", request=httpx.Request("POST", BASE)),
    )
    with pytest.raises(EstimationError, match="inválidos"):
        _estimate()


def test_request_estimation_connection_failure_is_sanitized(mocker):
    mocker.patch("estimator_chat.client.httpx.post", side_effect=httpx.ConnectError("private hostname"))
    with pytest.raises(EstimationError, match="No se pudo conectar con el backend") as caught:
        _estimate()
    assert "private hostname" not in str(caught.value)


def test_fetch_prompt_preview_returns_prompt_and_examples(api):
    preview = fetch_prompt_preview(BASE, **OPTIONS)

    assert preview.system_prompt == PREVIEW["system_prompt"]
    assert [example.title for example in preview.examples] == [e["title"] for e in PREVIEW["examples"]]
    assert api.previews == [OPTIONS]


def test_fetch_prompt_preview_maps_failures(mocker):
    mocker.patch("estimator_chat.client.httpx.get", return_value=reply(422, {"detail": "prompt inválido"}, "GET"))
    with pytest.raises(EstimationError, match="prompt inválido"):
        fetch_prompt_preview(BASE, **OPTIONS)
    mocker.patch("estimator_chat.client.httpx.get", return_value=reply(200, {"examples": []}, "GET"))
    with pytest.raises(EstimationError, match="inválidos"):
        fetch_prompt_preview(BASE, **OPTIONS)
    mocker.patch("estimator_chat.client.httpx.get", side_effect=httpx.ConnectError("private"))
    with pytest.raises(EstimationError, match="No se pudo conectar"):
        fetch_prompt_preview(BASE, **OPTIONS)
