import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fixture")
    monkeypatch.setenv("CACHE_ENABLED", "false")
    from app.config import get_settings
    get_settings.cache_clear()
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_health_returns_200(client):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_response_shape(client):
    data = client.get("/health").json()
    assert data["status"] == "healthy"
    assert "environment" in data
    assert "provider" in data
    assert "model" in data
    assert data["cache"] == {"enabled": False, "reachable": None}


def test_health_does_not_expose_api_key(client):
    resp_text = client.get("/health").text
    assert "sk-test-fixture" not in resp_text
    assert "api_key" not in resp_text.lower()


def test_swagger_ui_available(client):
    assert client.get("/docs").status_code == 200


def test_openapi_title(client):
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "Software Estimation CAG API"


def test_estimate_endpoint_is_registered(client):
    # Just verify the route exists (not calling LLM); 422 means the route is there
    resp = client.post("/api/v1/estimate", json={})
    assert resp.status_code == 422


def test_stream_endpoint_is_registered(client):
    assert client.post("/api/v1/estimate/stream", json={}).status_code == 422


def test_context_endpoint_does_not_expose_credentials(client):
    resp = client.get("/api/v1/context")
    assert resp.status_code == 200
    assert "sk-test-fixture" not in resp.text
    assert "Senior Software Estimation Architect" in resp.json()["system_prompt"]
