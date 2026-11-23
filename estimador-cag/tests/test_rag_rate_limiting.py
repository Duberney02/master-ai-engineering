"""Rate limiting por clave de API de los routers RAG (slowapi): 429 con `Retry-After` y cubos por clave."""

from app.api.rate_limiting import api_key_identifier
from tests._grounded import (
    ESTIMATE_KEY,
    RETRIEVAL_KEY,
    TRANSCRIPT,
    ScriptedGenerator,
    api_client,
    build_estimator,
    configure_keys,
)
from tests._grounded import estimate_payload as payload

ESTIMATE = "/v1/estimate/from-transcript"


class _Request:
    def __init__(self, headers):
        self.headers = headers
        self.client = type("C", (), {"host": "10.0.0.1"})()
        self.scope = {"client": ("10.0.0.1", 1234)}


def _generator(calls: int) -> ScriptedGenerator:
    """Reformulación + generación por llamada al pipeline."""
    outcomes = []
    for _ in range(calls):
        outcomes += [{"function": "payments marketplace", "sector": "finance"}, payload()]
    return ScriptedGenerator(*outcomes)


def test_the_eleventh_estimate_in_a_minute_is_429(monkeypatch):
    client = api_client(monkeypatch, build_estimator(_generator(10)))
    headers = {"X-API-Key": ESTIMATE_KEY}

    statuses = [client.post(ESTIMATE, json={"transcript": TRANSCRIPT}, headers=headers).status_code for _ in range(10)]
    blocked = client.post(ESTIMATE, json={"transcript": TRANSCRIPT}, headers=headers)

    assert statuses == [200] * 10
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"
    assert blocked.json() == {"detail": "Límite de peticiones superado.", "limit": "10 per 1 minute", "retry_after_seconds": 60}


def test_keys_sharing_an_ip_have_separate_buckets(monkeypatch):
    client = api_client(monkeypatch, build_estimator(_generator(20)))
    statuses = []
    # TestClient usa siempre la misma IP. Se rota la clave configurada (solo hay una por router) para que dos
    # claves distintas agoten cada una sus 10 peticiones: si el cubo fuera por IP, la segunda tanda daría 429.
    for key in (ESTIMATE_KEY, "estimate-key-rotated"):
        configure_keys(monkeypatch, estimate=key)
        statuses += [
            client.post(ESTIMATE, json={"transcript": TRANSCRIPT}, headers={"X-API-Key": key}).status_code
            for _ in range(10)
        ]

    assert statuses == [200] * 20


def test_stage_limit_is_30_per_minute(monkeypatch):
    client = api_client(monkeypatch)
    headers = {"X-API-Key": ESTIMATE_KEY}

    statuses = [client.post("/v1/estimate/stages/assemble", json={"chunks": []}, headers=headers).status_code for _ in range(31)]

    assert statuses[:30] == [200] * 30 and statuses[30] == 429


def test_retrieval_limit_is_120_per_minute(monkeypatch):
    client = api_client(monkeypatch)
    headers = {"X-API-Key": RETRIEVAL_KEY}
    body = {"query_text": "payments marketplace"}

    statuses = [client.post("/v1/retrieval/search", json=body, headers=headers).status_code for _ in range(121)]

    assert statuses.count(200) == 120 and statuses[-1] == 429


def test_unauthorized_requests_do_not_consume_the_bucket(monkeypatch):
    client = api_client(monkeypatch, build_estimator(_generator(1)))

    for _ in range(15):
        client.post(ESTIMATE, json={"transcript": TRANSCRIPT}, headers={"X-API-Key": "wrong"})

    ok = client.post(ESTIMATE, json={"transcript": TRANSCRIPT}, headers={"X-API-Key": ESTIMATE_KEY})
    assert ok.status_code == 200


def test_bucket_identity_is_a_key_hash_or_the_client_ip():
    with_key = api_key_identifier(_Request({"X-API-Key": "secret-key"}))
    without_key = api_key_identifier(_Request({}))

    assert with_key.startswith("key:") and "secret-key" not in with_key
    assert with_key == api_key_identifier(_Request({"X-API-Key": "secret-key"}))
    assert with_key != api_key_identifier(_Request({"X-API-Key": "other-key"}))
    assert without_key == "ip:10.0.0.1"
