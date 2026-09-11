from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.estimations import router
from app.services.llm_service import LLMEstimationResult


def _make_result() -> LLMEstimationResult:
    return LLMEstimationResult(
        estimation="## Estimación: Test\nContenido de prueba",
        model="gpt-4o-mini",
        provider="openai",
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        estimated_cost_usd=None,
        generated_at=datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc),
        latency_ms=1200,
    )


@pytest.fixture
def client(mocker) -> TestClient:
    mocker.patch(
        "app.routers.estimations.generate_estimation",
        new=AsyncMock(return_value=_make_result()),
    )
    test_app = FastAPI()
    test_app.include_router(router)
    return TestClient(test_app)


def test_estimate_valid_returns_200(client):
    resp = client.post(
        "/estimate",
        json={"transcription": "El cliente solicita una plataforma de e-commerce con pagos y envíos integrados."},
    )
    assert resp.status_code == 200


def test_estimate_response_shape(client):
    resp = client.post(
        "/estimate",
        json={"transcription": "El cliente solicita una plataforma de e-commerce con pagos y envíos integrados."},
    )
    data = resp.json()
    assert data["estimation"].startswith("## Estimación: Test")
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4o-mini"
    assert data["usage"]["input_tokens"] == 100
    assert data["usage"]["output_tokens"] == 50
    assert data["usage"]["total_tokens"] == 150
    assert data["estimated_cost_usd"] is None
    assert data["latency_ms"] == 1200
    assert "generated_at" in data


def test_estimate_rejects_too_short(client):
    resp = client.post("/estimate", json={"transcription": "Corto"})
    assert resp.status_code == 422


def test_estimate_rejects_empty(client):
    resp = client.post("/estimate", json={"transcription": ""})
    assert resp.status_code == 422


def test_estimate_rejects_missing_field(client):
    resp = client.post("/estimate", json={})
    assert resp.status_code == 422


def test_estimate_rejects_too_long(client):
    resp = client.post("/estimate", json={"transcription": "A" * 50_001})
    assert resp.status_code == 422
