"""`GET/PUT /api/v1/config/retrieval` y la precedencia petición → runtime → settings (Sesión 10)."""

import fakeredis
import pytest
from fakeredis import FakeAsyncRedis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.config import Settings
from app.dependencies import get_runtime_retrieval_config
from app.foundation.llm.runtime_config import HASH_KEY, RETRIEVAL_HASH_KEY, RuntimeRetrievalConfig
from app.main import app
from tests._grounded import ESTIMATE_KEY, RETRIEVAL_KEY, FakeRetriever, api_client, build_estimator

URL = "redis://fake:6379/0"
CONFIG = "/api/v1/config/retrieval"
SEARCH = "/v1/retrieval/search"
RETRIEVAL_HEADERS = {"X-API-Key": RETRIEVAL_KEY}
ESTIMATE_HEADERS = {"X-API-Key": ESTIMATE_KEY}
KNOBS = {
    "search_mode",
    "rerank",
    "routing_enabled",
    "query_transform_enabled",
    "temporal_decay_enabled",
    "task_hours_top_k",
    "task_hours_distance_threshold",
}


def make_settings(**kw) -> Settings:
    kw.setdefault("redis_url", URL)
    return Settings(llm_provider="openai", openai_api_key="sk-test", _env_file=None, **kw)


class DownRedis:
    """Cliente cuyo servidor no responde: lecturas y escrituras fallan con un error de conexión."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def hgetall(self, *args):
        raise RedisConnectionError("redis down")

    def pipeline(self, *args, **kwargs):
        raise RedisConnectionError("redis down")


@pytest.fixture
def server():
    return fakeredis.FakeServer()


@pytest.fixture
def redis(mocker, server):
    """Cada operación abre su cliente: los datos viven en el servidor simulado, como entre procesos."""

    def factory(url, **kwargs):
        return FakeAsyncRedis(server=server, decode_responses=kwargs.get("decode_responses", False))

    return mocker.patch("app.foundation.llm.runtime_config.Redis.from_url", side_effect=factory)


def stored(server) -> dict:
    client = FakeAsyncRedis(server=server, decode_responses=True)
    import asyncio

    return asyncio.run(client.hgetall(RETRIEVAL_HASH_KEY))


@pytest.fixture
def client(monkeypatch, redis):
    """Cliente con el orquestador real de recuperación sobre un `FakeRetriever` y el runtime en Redis simulado."""
    settings = make_settings()
    retriever = FakeRetriever()
    runtime = RuntimeRetrievalConfig(settings)
    client = api_client(monkeypatch, build_estimator(retriever=retriever, runtime_retrieval=runtime))
    app.dependency_overrides[get_runtime_retrieval_config] = lambda: runtime
    client.retriever, client.runtime = retriever, runtime
    return client


def knob(response, name) -> dict:
    return response.json()["retrieval"][name]


# --- GET -------------------------------------------------------------------------------------------------------


def test_without_overrides_every_parameter_is_the_default(client):
    body = client.get(CONFIG).json()

    assert set(body["retrieval"]) == KNOBS
    assert all(item["overridden"] is False and item["effective"] == item["default"] for item in body["retrieval"].values())
    assert body["retrieval"]["search_mode"]["default"] == "vector"
    assert body["retrieval"]["task_hours_top_k"]["default"] == 5
    assert body["reranker_model"] == "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"


def test_defaults_reflect_settings_not_a_hardcoded_value(monkeypatch, redis):
    settings = make_settings(retrieval_search_mode="hybrid", reranker_enabled=True, task_hours_top_k=8)
    runtime = RuntimeRetrievalConfig(settings)
    client = api_client(monkeypatch)
    app.dependency_overrides[get_runtime_retrieval_config] = lambda: runtime

    body = client.get(CONFIG).json()["retrieval"]

    assert body["search_mode"] == {"effective": "hybrid", "default": "hybrid", "overridden": False}
    assert body["rerank"]["effective"] is True and body["task_hours_top_k"]["effective"] == 8


# --- PUT -------------------------------------------------------------------------------------------------------


def test_put_returns_the_shape_of_get_and_marks_the_override(client):
    response = client.put(CONFIG, json={"search_mode": "hybrid"})

    assert response.status_code == 200
    assert knob(response, "search_mode") == {"effective": "hybrid", "default": "vector", "overridden": True}
    assert response.json() == client.get(CONFIG).json()
    assert set(response.json()) == {"retrieval", "reranker_model"}


def test_an_absent_key_does_not_change_and_null_resets_only_that_key(client):
    client.put(CONFIG, json={"search_mode": "hybrid", "rerank": True, "task_hours_top_k": 9})

    response = client.put(CONFIG, json={"rerank": None})

    assert knob(response, "rerank")["overridden"] is False
    assert knob(response, "search_mode") == {"effective": "hybrid", "default": "vector", "overridden": True}
    assert knob(response, "task_hours_top_k")["effective"] == 9


def test_typed_values_round_trip(client):
    response = client.put(
        CONFIG,
        json={
            "routing_enabled": False,
            "query_transform_enabled": False,
            "temporal_decay_enabled": True,
            "task_hours_top_k": 12,
            "task_hours_distance_threshold": 0.3,
        },
    )

    assert [knob(response, n)["effective"] for n in ("routing_enabled", "query_transform_enabled", "temporal_decay_enabled")] == [
        False,
        False,
        True,
    ]
    assert knob(response, "task_hours_top_k")["effective"] == 12
    assert knob(response, "task_hours_distance_threshold")["effective"] == pytest.approx(0.3)


def test_an_empty_update_changes_nothing(client):
    assert client.put(CONFIG, json={}).status_code == 200
    assert all(item["overridden"] is False for item in client.get(CONFIG).json()["retrieval"].values())


@pytest.mark.parametrize(
    "body",
    [
        {"search_mode": "lexical"},
        {"search_mode": ""},
        {"rerank": "maybe"},
        {"task_hours_top_k": 0},
        {"task_hours_top_k": 31},
        {"task_hours_distance_threshold": 2.5},
        {"task_hours_distance_threshold": -0.1},
        {"unknown_knob": True},
    ],
)
def test_invalid_updates_are_422_and_write_nothing(client, server, body):
    response = client.put(CONFIG, json={"rerank": True, **body})

    assert response.status_code == 422
    assert stored(server) == {}  # todo o nada: ni siquiera la clave válida se aplicó


def test_overrides_persist_in_their_own_redis_hash(client, server):
    client.put(CONFIG, json={"search_mode": "hybrid", "rerank": True})

    assert stored(server) == {"search_mode": "hybrid", "rerank": "true"}
    assert RETRIEVAL_HASH_KEY != HASH_KEY  # restablecer los modelos no borra estos parámetros ni al revés


def test_a_corrupt_stored_value_is_ignored_and_the_default_applies(client, server):
    import asyncio

    asyncio.run(FakeAsyncRedis(server=server, decode_responses=True).hset(RETRIEVAL_HASH_KEY, "search_mode", "bogus"))

    assert knob(client.get(CONFIG), "search_mode") == {"effective": "vector", "default": "vector", "overridden": False}


def test_redis_down_on_write_is_a_generic_503(client, mocker):
    mocker.patch("app.foundation.llm.runtime_config.Redis.from_url", return_value=DownRedis())

    response = client.put(CONFIG, json={"search_mode": "hybrid"})

    assert response.status_code == 503
    assert response.json() == {"detail": "El almacén de configuración no está disponible"}
    assert "redis down" not in response.text


def test_without_redis_configured_a_write_is_a_503(monkeypatch):
    runtime = RuntimeRetrievalConfig(make_settings(redis_url=None))
    client = api_client(monkeypatch)
    app.dependency_overrides[get_runtime_retrieval_config] = lambda: runtime

    assert client.put(CONFIG, json={"rerank": True}).status_code == 503
    assert client.get(CONFIG).status_code == 200  # la lectura degrada a los valores por defecto


def test_redis_down_on_read_serves_the_defaults(client, mocker):
    mocker.patch("app.foundation.llm.runtime_config.Redis.from_url", return_value=DownRedis())

    response = client.get(CONFIG)

    assert response.status_code == 200
    assert knob(response, "search_mode") == {"effective": "vector", "default": "vector", "overridden": False}


# --- Precedencia: petición → runtime → settings -------------------------------------------------------------


def search(client, **body):
    return client.post(SEARCH, json={"query_text": "payments marketplace", **body}, headers=RETRIEVAL_HEADERS)


def modes(client) -> tuple[str, bool]:
    call = client.retriever.calls[-1]
    return call["search_mode"], call["rerank"]


def test_without_overrides_the_settings_defaults_apply(client):
    search(client)

    assert modes(client) == ("vector", False)


def test_a_runtime_override_applies_on_the_next_search_without_restart(client):
    client.put(CONFIG, json={"search_mode": "hybrid", "rerank": True})

    search(client)

    assert modes(client) == ("hybrid", True)


def test_an_explicit_request_field_beats_the_runtime_override(client):
    client.put(CONFIG, json={"search_mode": "hybrid", "rerank": True})

    search(client, search_mode="vector", rerank=False)

    assert modes(client) == ("vector", False)


def test_each_field_resolves_independently(client):
    client.put(CONFIG, json={"search_mode": "hybrid", "rerank": True})

    search(client, rerank=False)

    assert modes(client) == ("hybrid", False)


def test_resetting_goes_back_to_the_settings_default(client):
    client.put(CONFIG, json={"search_mode": "hybrid"})
    client.put(CONFIG, json={"search_mode": None})

    search(client)

    assert modes(client) == ("vector", False)


def test_an_unknown_search_mode_in_the_request_is_a_422(client):
    assert search(client, search_mode="lexical").status_code == 422
    assert client.retriever.calls == []


def test_the_grounded_pipeline_stage_uses_the_runtime_values(client):
    client.put(CONFIG, json={"search_mode": "hybrid", "rerank": True})

    response = client.post(
        "/v1/estimate/stages/retrieve", json={"query_text": "payments marketplace"}, headers=ESTIMATE_HEADERS
    )

    assert response.status_code == 200 and modes(client) == ("hybrid", True)


async def test_the_estimator_retrieval_reads_the_runtime_values(client):
    client.put(CONFIG, json={"search_mode": "hybrid"})

    await client.holder["estimator"].retrieve("payments marketplace")

    assert modes(client) == ("hybrid", False)
