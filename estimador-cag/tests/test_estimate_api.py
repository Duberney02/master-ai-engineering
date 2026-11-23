"""`POST /v1/estimate/from-transcript`: 200, 422, 401, 502 saneado e idempotencia a través de la API."""

import pytest

from app.dependencies import get_chunk_retriever, get_grounded_estimator, get_idempotency_store
from app.main import app
from tests._grounded import (
    BRIEF,
    ESTIMATE_KEY,
    SECRET,
    TRANSCRIPT,
    FakeRetriever,
    ScriptedGenerator,
    api_client,
    build_estimator,
    estimate_payload,
)

URL = "/v1/estimate/from-transcript"
HEADERS = {"X-API-Key": ESTIMATE_KEY}


def test_grounded_estimate_contract(monkeypatch):
    client = api_client(monkeypatch, build_estimator(ScriptedGenerator(BRIEF, estimate_payload(source_ids=(1, 2)))))

    response = client.post(URL, json={"transcript": TRANSCRIPT}, headers=HEADERS)

    payload = response.json()
    assert response.status_code == 200
    assert {"modules", "total_engineer_days", "duration_weeks", "sources", "assumptions", "confidence", "reasoning"} <= set(payload)
    assert payload["modules"][0]["tasks"][0]["engineer_days"] == 12
    assert payload["confidence"] == "high" and response.headers["X-Request-ID"]


def test_soft_fail_is_a_200_insufficient(monkeypatch):
    client = api_client(monkeypatch, build_estimator(ScriptedGenerator(BRIEF), FakeRetriever([])))

    payload = client.post(URL, json={"transcript": TRANSCRIPT}, headers=HEADERS).json()

    assert payload["confidence"] == "insufficient" and payload["modules"] == []
    assert payload["total_engineer_days"] is None and payload["insufficient_context_explanation"]


@pytest.mark.parametrize("body", [{}, {"transcript": "demasiado corta"}, {"transcript": TRANSCRIPT, "idempotency_key": "k" * 129}])
def test_invalid_input_is_422(monkeypatch, body):
    generator = ScriptedGenerator()
    client = api_client(monkeypatch, build_estimator(generator))

    assert client.post(URL, json=body, headers=HEADERS).status_code == 422
    assert generator.calls == []


def test_without_key_is_401(monkeypatch):
    client = api_client(monkeypatch)

    assert client.post(URL, json={"transcript": TRANSCRIPT}).status_code == 401


def test_llm_failure_is_a_sanitized_502_with_request_id(monkeypatch):
    client = api_client(monkeypatch, build_estimator(ScriptedGenerator(BRIEF, RuntimeError(SECRET))))

    response = client.post(URL, json={"transcript": TRANSCRIPT}, headers={**HEADERS, "X-Request-ID": "trace-502"})

    assert response.status_code == 502
    assert response.json() == {"detail": "No se pudo generar la estimación."}
    assert SECRET not in response.text and response.headers["X-Request-ID"] == "trace-502"


def test_idempotent_retries_call_the_llm_once(monkeypatch):
    generator = ScriptedGenerator(BRIEF, estimate_payload())
    client = api_client(monkeypatch, build_estimator(generator))
    body = {"transcript": TRANSCRIPT, "idempotency_key": "client-retry-1"}

    first = client.post(URL, json=body, headers=HEADERS)
    second = client.post(URL, json=body, headers=HEADERS)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() and len(generator.calls) == 2


def test_real_factories_wire_the_shared_idempotency_store(monkeypatch):
    """Sin sustituir el orquestador: la fábrica real reutiliza el almacén del proceso entre peticiones."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    generator = ScriptedGenerator(BRIEF, estimate_payload())
    client = api_client(monkeypatch)
    app.dependency_overrides.pop(get_grounded_estimator)
    app.dependency_overrides[get_chunk_retriever] = lambda: FakeRetriever()
    monkeypatch.setattr("app.generation.rag.estimator.generate_from_messages", generator)
    body = {"transcript": TRANSCRIPT, "idempotency_key": "shared"}

    first = client.post(URL, json=body, headers=HEADERS)
    second = client.post(URL, json=body, headers=HEADERS)

    assert first.status_code == 200 and first.json() == second.json()
    assert len(generator.calls) == 2 and get_idempotency_store().backend == "memory"
