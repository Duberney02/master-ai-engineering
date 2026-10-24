"""`GET/PUT /api/v1/config/models`: lectura, escritura parcial todo-o-nada, errores y auditoría."""

import fakeredis
import pytest
import structlog
from fakeredis import FakeAsyncRedis
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_runtime_config
from app.foundation.llm.runtime_config import RuntimeModelConfig
from app.main import app

URL = "redis://fake:6379/0"
BOTH_KEYS = {"openai_api_key": "sk-test", "anthropic_api_key": "sk-ant", "redis_url": URL}


def make_settings(**kw) -> Settings:
    return Settings(llm_provider="openai", _env_file=None, **{**BOTH_KEYS, **kw})


@pytest.fixture
def server():
    return fakeredis.FakeServer()


@pytest.fixture
def use_settings(mocker, server):
    """Devuelve una función que fija los `Settings` del almacén y conecta Redis simulado."""

    def factory(url, **kwargs):
        return FakeAsyncRedis(server=server, decode_responses=kwargs.get("decode_responses", False))

    mocker.patch("app.foundation.llm.runtime_config.Redis.from_url", side_effect=factory)

    def apply(**kw):
        settings = make_settings(**kw)
        app.dependency_overrides[get_runtime_config] = lambda: RuntimeModelConfig(settings)
        return settings

    yield apply
    app.dependency_overrides.clear()


@pytest.fixture
def client(use_settings):
    use_settings()
    with TestClient(app) as test_client:
        yield test_client


def models(response) -> dict:
    return response.json()["models"]


def test_get_returns_effective_default_and_overridden_per_knob(client):
    body = client.get("/api/v1/config/models").json()

    assert body["models"]["primary_model"] == {"effective": "gpt-4o-mini", "default": "gpt-4o-mini", "overridden": False}
    assert set(body["models"]) == {
        "primary_model",
        "fallback_model",
        "critic_model",
        "metadata_model",
        "summary_model",
        "propositional_chunker_model",
        "contextual_chunker_model",
    }


def test_embedding_model_is_read_only_and_not_a_knob(client):
    body = client.get("/api/v1/config/models").json()

    assert body["embedding_model"] == "text-embedding-3-small"
    assert "invalidar" in body["embedding_model_note"]
    assert "embedding_model" not in body["models"]
    response = client.put("/api/v1/config/models", json={"models": {"embedding_model": "x"}})
    assert response.status_code == 422


def test_available_models_are_filtered_by_configured_keys(use_settings):
    use_settings(anthropic_api_key=None)
    with TestClient(app) as client:
        available = client.get("/api/v1/config/models").json()["available_models"]

    assert available == ["gpt-4o-mini", "gpt-4o"]


def test_put_overrides_and_returns_the_fresh_snapshot(client):
    response = client.put("/api/v1/config/models", json={"models": {"primary_model": "gpt-4o"}})

    assert response.status_code == 200
    assert models(response)["primary_model"] == {"effective": "gpt-4o", "default": "gpt-4o-mini", "overridden": True}
    assert models(client.get("/api/v1/config/models"))["primary_model"]["effective"] == "gpt-4o"


def test_put_is_partial_and_null_resets(client):
    client.put("/api/v1/config/models", json={"models": {"primary_model": "gpt-4o", "critic_model": "claude-sonnet-4-5"}})

    response = client.put("/api/v1/config/models", json={"models": {"primary_model": None}})

    snapshot = models(response)
    assert snapshot["primary_model"]["overridden"] is False
    assert snapshot["critic_model"] == {"effective": "claude-sonnet-4-5", "default": "gpt-4o-mini", "overridden": True}


def test_put_unknown_knob_is_422(client):
    response = client.put("/api/v1/config/models", json={"models": {"nope": "gpt-4o"}})

    assert response.status_code == 422 and "nope" in response.json()["detail"]


def test_put_model_outside_the_catalog_is_422(client):
    response = client.put("/api/v1/config/models", json={"models": {"primary_model": "gpt-9-turbo"}})

    assert response.status_code == 422 and "catálogo" in response.json()["detail"]


def test_put_model_whose_provider_key_is_missing_is_400_naming_the_key(use_settings):
    use_settings(anthropic_api_key=None)
    with TestClient(app) as client:
        response = client.put("/api/v1/config/models", json={"models": {"primary_model": "claude-sonnet-4-5"}})

    assert response.status_code == 400
    assert "ANTHROPIC_API_KEY" in response.json()["detail"] and "sk-ant" not in response.text


def test_put_chunker_model_must_match_the_provider_the_chunker_uses(client):
    wrong = client.put("/api/v1/config/models", json={"models": {"propositional_chunker_model": "claude-haiku-4-5"}})
    right = client.put("/api/v1/config/models", json={"models": {"propositional_chunker_model": "gpt-4o"}})
    contextual = client.put("/api/v1/config/models", json={"models": {"contextual_chunker_model": "gpt-4o"}})

    assert wrong.status_code == 422 and contextual.status_code == 422 and right.status_code == 200


def test_put_is_all_or_nothing(client):
    response = client.put(
        "/api/v1/config/models",
        json={"models": {"primary_model": "gpt-4o", "critic_model": "gpt-9-turbo", "summary_model": "gpt-4o"}},
    )

    assert response.status_code == 422
    snapshot = models(client.get("/api/v1/config/models"))
    assert not any(item["overridden"] for item in snapshot.values())


def test_put_requires_at_least_one_knob(client):
    assert client.put("/api/v1/config/models", json={"models": {}}).status_code == 422


def test_put_store_down_is_503_and_nothing_is_applied(mocker, use_settings):
    use_settings()
    mocker.patch("app.foundation.llm.runtime_config.Redis.from_url", side_effect=ConnectionError("down"))
    with TestClient(app) as client:
        response = client.put("/api/v1/config/models", json={"models": {"primary_model": "gpt-4o"}})
        read = client.get("/api/v1/config/models")

    assert response.status_code == 503
    assert "ConnectionError" not in response.text
    # La lectura sigue funcionando con los valores por defecto.
    assert read.status_code == 200 and models(read)["primary_model"]["overridden"] is False


def test_each_change_leaves_an_audit_log(client):
    with structlog.testing.capture_logs() as logs:
        client.put("/api/v1/config/models", json={"models": {"primary_model": "gpt-4o"}})
        client.put("/api/v1/config/models", json={"models": {"primary_model": None}})

    changes = [entry for entry in logs if entry["event"] == "runtime_config_changed"]
    assert [(c["key"], c["old_effective"], c["new_value"], c["reset"]) for c in changes] == [
        ("primary_model", "gpt-4o-mini", "gpt-4o", False),
        ("primary_model", "gpt-4o", None, True),
    ]


def test_rejected_changes_leave_no_audit_log(client):
    with structlog.testing.capture_logs() as logs:
        client.put("/api/v1/config/models", json={"models": {"primary_model": "gpt-9-turbo"}})

    assert not [entry for entry in logs if entry["event"] == "runtime_config_changed"]


def test_audit_fields_are_in_the_safe_log_list():
    from app.logging_config import SAFE_FIELDS

    assert {"key", "old_effective", "new_value", "reset"} <= SAFE_FIELDS


def test_the_route_is_documented_and_additive(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/config/models" in paths and set(paths["/api/v1/config/models"]) == {"get", "put"}
    assert "/api/v1/estimate" in paths
