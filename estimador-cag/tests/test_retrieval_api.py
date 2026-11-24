"""`POST /v1/retrieval/search`: contrato, validación (422), soft-fail y errores saneados (500/502)."""

import pytest

from app.generation.rag.retriever import RetrievalFilters
from tests._grounded import (
    RETRIEVAL_KEY,
    SECRET,
    FakeRetriever,
    api_client,
    build_estimator,
    failing_retriever,
    make_chunk,
)

URL = "/v1/retrieval/search"
HEADERS = {"X-API-Key": RETRIEVAL_KEY}


def test_search_returns_the_contract_and_forwards_filters(monkeypatch):
    retriever = FakeRetriever([make_chunk(7, 0.12), make_chunk(9, 0.4)])
    client = api_client(monkeypatch, build_estimator(retriever=retriever))
    body = {
        "query_text": "payments marketplace",
        "top_k": 5,
        "distance_threshold": 0.5,
        "sectors": ["finance"],
        "project_year_min": 2022,
        "project_year_max": 2024,
        "chunk_types": ["budget_component"],
    }

    response = client.post(URL, json=body, headers=HEADERS)

    payload = response.json()
    assert response.status_code == 200
    assert set(payload) == {"chunks", "low_confidence", "candidates_evaluated"}
    assert payload["low_confidence"] is False and payload["candidates_evaluated"] == 25
    assert set(payload["chunks"][0]) >= {"id", "content", "sector", "project_year", "chunk_type", "distance", "budget_id"}
    assert [chunk["id"] for chunk in payload["chunks"]] == [7, 9]
    assert retriever.calls == [
        {
            "query_text": "payments marketplace",
            "top_k": 5,
            "distance_threshold": 0.5,
            "filters": RetrievalFilters(["finance"], 2022, 2024, ["budget_component"]),
            "search_mode": "vector",
            "rerank": False,
        }
    ]


def test_defaults_come_from_settings(monkeypatch):
    retriever = FakeRetriever()
    client = api_client(
        monkeypatch, build_estimator(retriever=retriever, retrieval_top_k=7, retrieval_distance_threshold=0.42)
    )

    client.post(URL, json={"query_text": "payments marketplace"}, headers=HEADERS)

    assert (retriever.calls[0]["top_k"], retriever.calls[0]["distance_threshold"]) == (7, 0.42)
    assert retriever.calls[0]["filters"] == RetrievalFilters()


def test_soft_fail_is_a_200_with_low_confidence(monkeypatch):
    client = api_client(monkeypatch, build_estimator(retriever=FakeRetriever([])))

    response = client.post(URL, json={"query_text": "quantum gardening robots"}, headers=HEADERS)

    assert response.status_code == 200
    assert response.json() == {"chunks": [], "low_confidence": True, "candidates_evaluated": 25}


@pytest.mark.parametrize(
    "body",
    [
        {"query_text": ""},
        {"query_text": "     "},
        {"query_text": "x" * 2001},
        {"query_text": "payments", "top_k": 0},
        {"query_text": "payments", "top_k": 31},
        {"query_text": "payments", "distance_threshold": 2.5},
        {"query_text": "payments", "project_year_min": 1800},
        {},
    ],
)
def test_invalid_input_is_422(monkeypatch, body):
    retriever = FakeRetriever()
    client = api_client(monkeypatch, build_estimator(retriever=retriever))

    assert client.post(URL, json=body, headers=HEADERS).status_code == 422
    assert retriever.calls == []


def test_missing_embedder_is_a_generic_500(monkeypatch):
    client = api_client(monkeypatch, build_estimator(retriever=failing_retriever("embedder")))

    response = client.post(URL, json={"query_text": "payments"}, headers=HEADERS)

    assert response.status_code == 500
    assert response.json() == {"detail": "El servicio de embeddings no está disponible."}


def test_provider_or_database_failure_is_a_sanitized_502(monkeypatch):
    client = api_client(monkeypatch, build_estimator(retriever=failing_retriever()))

    response = client.post(URL, json={"query_text": "payments"}, headers=HEADERS)

    assert response.status_code == 502
    assert response.json() == {"detail": "No se pudo ejecutar la recuperación."}
    assert SECRET not in response.text


def test_the_session_8_search_endpoint_is_untouched(monkeypatch):
    client = api_client(monkeypatch)

    # Sin DATABASE_URL, `POST /search` sigue respondiendo como en la Sesión 8 (503) y sin clave de API.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert client.post("/search", json={"query": "oauth", "k": 3}).status_code == 503
