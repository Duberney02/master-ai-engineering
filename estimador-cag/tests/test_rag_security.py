"""Claves de API independientes de los routers RAG de la Sesión 9 (`X-API-Key`, comparación en tiempo constante)."""

import pytest

from tests._grounded import (
    ESTIMATE_KEY,
    RETRIEVAL_KEY,
    TRANSCRIPT,
    FakeRetriever,
    ScriptedGenerator,
    api_client,
    build_estimator,
)

SEARCH = ("/v1/retrieval/search", {"query_text": "payments marketplace"})
ESTIMATE = ("/v1/estimate/from-transcript", {"transcript": TRANSCRIPT})
STAGE = ("/v1/estimate/stages/assemble", {"chunks": []})


def _assert_unauthorized(response):
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "X-API-Key"
    assert response.json() == {"detail": "Clave de API ausente o no válida."}


@pytest.mark.parametrize("path,body", [SEARCH, ESTIMATE, STAGE])
def test_missing_key_is_401_and_runs_nothing(monkeypatch, path, body):
    retriever, generator = FakeRetriever(), ScriptedGenerator()
    client = api_client(monkeypatch, build_estimator(generator, retriever))

    _assert_unauthorized(client.post(path, json=body))
    assert retriever.calls == [] and generator.calls == []


@pytest.mark.parametrize("path,body", [SEARCH, ESTIMATE, STAGE])
def test_wrong_key_is_401(monkeypatch, path, body):
    client = api_client(monkeypatch)

    _assert_unauthorized(client.post(path, json=body, headers={"X-API-Key": "nope"}))


def test_a_key_does_not_open_the_other_router(monkeypatch):
    client = api_client(monkeypatch)

    _assert_unauthorized(client.post(ESTIMATE[0], json=ESTIMATE[1], headers={"X-API-Key": RETRIEVAL_KEY}))
    _assert_unauthorized(client.post(STAGE[0], json=STAGE[1], headers={"X-API-Key": RETRIEVAL_KEY}))
    _assert_unauthorized(client.post(SEARCH[0], json=SEARCH[1], headers={"X-API-Key": ESTIMATE_KEY}))


def test_routers_are_disabled_without_configured_keys(monkeypatch):
    client = api_client(monkeypatch, retrieval=None, estimate=None)

    _assert_unauthorized(client.post(SEARCH[0], json=SEARCH[1], headers={"X-API-Key": RETRIEVAL_KEY}))
    _assert_unauthorized(client.post(ESTIMATE[0], json=ESTIMATE[1], headers={"X-API-Key": ESTIMATE_KEY}))
    _assert_unauthorized(client.post(STAGE[0], json=STAGE[1], headers={"X-API-Key": ""}))


def test_matching_keys_reach_the_endpoints(monkeypatch):
    client = api_client(monkeypatch)

    assert client.post(SEARCH[0], json=SEARCH[1], headers={"X-API-Key": RETRIEVAL_KEY}).status_code == 200
    assert client.post(STAGE[0], json=STAGE[1], headers={"X-API-Key": ESTIMATE_KEY}).status_code == 200


def test_the_comparison_is_constant_time(mocker, monkeypatch):
    spy = mocker.spy(__import__("app.api.security", fromlist=["secrets"]).secrets, "compare_digest")
    client = api_client(monkeypatch)

    client.post(SEARCH[0], json=SEARCH[1], headers={"X-API-Key": "nope"})

    assert spy.call_count == 1
