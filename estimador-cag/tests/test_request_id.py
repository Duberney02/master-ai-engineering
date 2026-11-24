"""`X-Request-ID`: se propaga o se genera en cada respuesta y correlaciona los logs de las etapas RAG."""

import uuid

import pytest
from structlog.testing import capture_logs

from app.api.request_id import resolve_request_id
from app.generation.rag.observability import log_stage
from tests._grounded import ESTIMATE_KEY, api_client, make_chunk

ASSEMBLE = "/v1/estimate/stages/assemble"


def _body() -> dict:
    return {"chunks": [make_chunk(1).model_dump()]}


def test_the_incoming_id_is_echoed_and_bound_to_the_stage_logs(monkeypatch):
    client = api_client(monkeypatch)

    with capture_logs() as logs:
        response = client.post(ASSEMBLE, json=_body(), headers={"X-API-Key": ESTIMATE_KEY, "X-Request-ID": "abc"})

    assert response.status_code == 200 and response.headers["X-Request-ID"] == "abc"
    stage_logs = [log for log in logs if log["event"].startswith("rag_stage_")]
    assert [log["event"] for log in stage_logs] == ["rag_stage_started", "rag_stage_completed"]
    assert all(log["request_id"] == "abc" and log["stage"] == "augmentation" for log in stage_logs)
    assert isinstance(stage_logs[-1]["duration_ms"], int)


def test_a_uuid_is_generated_when_missing(monkeypatch):
    client = api_client(monkeypatch)

    response = client.get("/health")

    assert uuid.UUID(response.headers["X-Request-ID"])


def test_every_response_carries_the_header_even_errors(monkeypatch):
    client = api_client(monkeypatch)

    response = client.post(ASSEMBLE, json=_body(), headers={"X-Request-ID": "req-401"})

    assert response.status_code == 401 and response.headers["X-Request-ID"] == "req-401"


@pytest.mark.parametrize("unsafe", ["", "a b", "x" * 200, "line\nbreak", "<script>"])
def test_unsafe_incoming_ids_are_replaced(unsafe):
    assert uuid.UUID(resolve_request_id(unsafe))


def test_log_stage_records_failures_with_the_error_type_only():
    with capture_logs() as logs, pytest.raises(RuntimeError):
        with log_stage("reformulation", "rid-1"):
            raise RuntimeError("sk-secret-detail")

    failed = logs[-1]
    assert failed["event"] == "rag_stage_failed" and failed["stage"] == "reformulation"
    assert failed["request_id"] == "rid-1" and failed["error_type"] == "RuntimeError"
    assert "sk-secret-detail" not in str(logs)
