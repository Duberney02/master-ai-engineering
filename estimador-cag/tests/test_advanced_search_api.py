"""`POST /v1/retrieval/advanced-search`: contrato, diagnóstico, precedencia, filtros y errores saneados (Sesión 10)."""

from datetime import date

import fakeredis
import pytest
from fakeredis import FakeAsyncRedis

from app.config import Settings
from app.dependencies import get_advanced_retriever, get_runtime_retrieval_config
from app.foundation.llm.runtime_config import RuntimeRetrievalConfig
from app.generation.rag.errors import EmbedderUnavailableError, RetrievalError
from app.generation.rag.retrieval.advanced_pipeline import AdvancedRetrievalOutcome
from app.generation.rag.retrieval.collections import Collection, HardFilters
from app.generation.rag.retrieval.query_transform import SubQuery
from app.generation.rag.retrieval.router import RoutingDecision
from app.main import app
from tests._grounded import RETRIEVAL_KEY, SECRET, api_client, make_chunk

URL = "/v1/retrieval/advanced-search"
HEADERS = {"X-API-Key": RETRIEVAL_KEY}
REDIS_URL = "redis://fake:6379/0"


class FakeAdvancedRetriever:
    """Sustituye a `AdvancedRetriever`: devuelve un resultado fijo (o falla) y registra las llamadas."""

    def __init__(self, outcome: AdvancedRetrievalOutcome | None = None, error: Exception | None = None) -> None:
        self.outcome = outcome or default_outcome()
        self.error = error
        self.calls: list[dict] = []

    async def search(self, query_text, *, stages, reference_date, explicit_collections=None, hard_filters=None):
        self.calls.append(
            {
                "query_text": query_text,
                "stages": stages,
                "reference_date": reference_date,
                "explicit_collections": explicit_collections,
                "hard_filters": hard_filters,
            }
        )
        if self.error:
            raise self.error
        return self.outcome


def default_outcome() -> AdvancedRetrievalOutcome:
    return AdvancedRetrievalOutcome(
        chunks=[
            make_chunk(7, 0.12, collection="transcript", source_id="TR-1", document_date=date(2025, 3, 10)),
            make_chunk(9, 0.4, source_id="BUD-9", relevance_score=0.7),
        ],
        routing=RoutingDecision([Collection.TRANSCRIPT, Collection.BUDGET], "rules", "El vocabulario coincide con: x."),
        technique="decompose",
        subqueries=[SubQuery(topic="auth", query="oauth"), SubQuery(topic="ledger", query="transaction ledger")],
        cardinality={"transcript": 12, "budget": 0},
        low_confidence=False,
    )


@pytest.fixture
def fake():
    return FakeAdvancedRetriever()


@pytest.fixture
def client(monkeypatch, fake):
    client = api_client(monkeypatch)
    app.dependency_overrides[get_advanced_retriever] = lambda: fake
    return client


def post(client, **body):
    return client.post(URL, json={"query_text": "payments marketplace with kyc", **body}, headers=HEADERS)


# --- Contrato y diagnóstico ---------------------------------------------------------------------------------


def test_the_response_carries_the_chunks_and_every_diagnostic(client):
    response = post(client)

    payload = response.json()
    assert response.status_code == 200
    assert set(payload) == {"chunks", "low_confidence", "routing", "technique", "subqueries", "cardinality"}
    assert payload["routing"] == {
        "level": "rules",
        "targets": ["transcript", "budget"],
        "reason": "El vocabulario coincide con: x.",
    }
    assert payload["technique"] == "decompose"
    assert payload["subqueries"] == [
        {"topic": "auth", "query": "oauth"},
        {"topic": "ledger", "query": "transaction ledger"},
    ]
    assert payload["cardinality"] == {"transcript": 12, "budget": 0}  # el 0 es visible, no un vacío silencioso
    assert payload["low_confidence"] is False


def test_every_chunk_declares_its_collection_source_id_and_date(client):
    first, second = post(client).json()["chunks"]

    assert (first["collection"], first["source_id"], first["document_date"]) == ("transcript", "TR-1", "2025-03-10")
    assert (second["collection"], second["source_id"], second["relevance_score"]) == ("budget", "BUD-9", 0.7)


def test_a_soft_fail_is_a_200_with_low_confidence(monkeypatch):
    empty = default_outcome()
    empty.chunks, empty.low_confidence = [], True
    fake = FakeAdvancedRetriever(empty)
    client = api_client(monkeypatch)
    app.dependency_overrides[get_advanced_retriever] = lambda: fake

    response = post(client)

    assert response.status_code == 200 and response.json()["chunks"] == [] and response.json()["low_confidence"] is True


def test_the_request_is_forwarded_with_filters_collections_and_a_reference_date(client, fake):
    post(
        client,
        collections=["technical_doc"],
        technologies=["ruby_on_rails"],
        sectors=["finance"],
        min_date="2024-01-01",
        doc_version="2.1",
        top_k=3,
    )

    call = fake.calls[0]
    assert call["query_text"] == "payments marketplace with kyc"
    assert call["explicit_collections"] == [Collection.TECHNICAL_DOC]
    assert call["hard_filters"] == HardFilters(
        technologies=("ruby_on_rails",), sectors=("finance",), min_date=date(2024, 1, 1), version="2.1"
    )
    assert call["stages"].top_k == 3 and isinstance(call["reference_date"], date)


# --- Precedencia ---------------------------------------------------------------------------------------------


def test_without_overrides_the_settings_defaults_drive_the_stages(client, fake):
    post(client)

    stages = fake.calls[0]["stages"]
    assert (stages.search_mode, stages.rerank, stages.routing_enabled) == ("vector", False, True)
    assert (stages.query_transform_enabled, stages.temporal_decay_enabled) == (True, False)
    assert (stages.top_k, stages.recall_k, stages.rrf_k, stages.half_life_days) == (5, 50, 60, 900)
    assert (stages.max_subqueries, stages.max_targets, stages.distance_threshold) == (4, 3, 0.6)


def test_explicit_request_fields_override_every_stage(client, fake):
    post(
        client,
        search_mode="hybrid",
        rerank=True,
        routing_enabled=False,
        query_transform_enabled=False,
        temporal_decay_enabled=True,
    )

    stages = fake.calls[0]["stages"]
    assert (stages.search_mode, stages.rerank, stages.routing_enabled) == ("hybrid", True, False)
    assert (stages.query_transform_enabled, stages.temporal_decay_enabled) == (False, True)


def test_request_beats_runtime_and_runtime_beats_settings(monkeypatch, mocker, fake):
    server = fakeredis.FakeServer()
    mocker.patch(
        "app.foundation.llm.runtime_config.Redis.from_url",
        side_effect=lambda url, **kw: FakeAsyncRedis(server=server, decode_responses=kw.get("decode_responses", False)),
    )
    runtime = RuntimeRetrievalConfig(
        Settings(llm_provider="openai", openai_api_key="sk-test", redis_url=REDIS_URL, _env_file=None)
    )
    client = api_client(monkeypatch)
    app.dependency_overrides[get_advanced_retriever] = lambda: fake
    app.dependency_overrides[get_runtime_retrieval_config] = lambda: runtime
    client.put(
        "/api/v1/config/retrieval",
        json={"search_mode": "hybrid", "rerank": True, "routing_enabled": False, "temporal_decay_enabled": True},
    )

    post(client)  # sin campos: gana el runtime
    post(client, search_mode="vector", temporal_decay_enabled=False)  # con campos: gana la petición

    runtime_stages, request_stages = fake.calls[0]["stages"], fake.calls[1]["stages"]
    assert (runtime_stages.search_mode, runtime_stages.rerank, runtime_stages.routing_enabled) == ("hybrid", True, False)
    assert runtime_stages.temporal_decay_enabled is True
    assert (request_stages.search_mode, request_stages.temporal_decay_enabled) == ("vector", False)
    assert (request_stages.rerank, request_stages.routing_enabled) == (True, False)  # lo no enviado sigue el runtime
    assert request_stages.query_transform_enabled is True  # y lo no fijado en runtime, `Settings`


# --- Validación (422) ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"query_text": ""},
        {"query_text": "     "},
        {"query_text": "x" * 2001},
        {"query_text": "payments", "top_k": 0},
        {"query_text": "payments", "top_k": 31},
        {"query_text": "payments", "collections": ["archive"]},
        {"query_text": "payments", "collections": ["budget", "budget", "transcript", "technical_doc"]},
        {"query_text": "payments", "search_mode": "lexical"},
        {"query_text": "payments", "min_date": "not-a-date"},
        {"query_text": "payments", "doc_version": ""},
        {},
    ],
)
def test_invalid_input_is_422_and_never_reaches_the_retriever(client, fake, body):
    assert client.post(URL, json=body, headers=HEADERS).status_code == 422
    assert fake.calls == []


# --- Seguridad y errores -------------------------------------------------------------------------------------


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_a_missing_or_wrong_key_is_401(client, fake, headers):
    response = client.post(URL, json={"query_text": "payments marketplace"}, headers=headers)

    assert response.status_code == 401 and fake.calls == []


def test_the_estimate_key_does_not_open_the_retrieval_router(client):
    response = client.post(URL, json={"query_text": "payments"}, headers={"X-API-Key": "estimate-key-456"})

    assert response.status_code == 401


def test_without_a_configured_key_the_router_answers_401_to_everything(monkeypatch, fake):
    client = api_client(monkeypatch, retrieval=None)
    app.dependency_overrides[get_advanced_retriever] = lambda: fake

    assert client.post(URL, json={"query_text": "payments"}, headers=HEADERS).status_code == 401


def test_the_rate_limit_is_120_per_minute_per_key_with_retry_after(client, fake):
    statuses = [post(client).status_code for _ in range(120)]
    over = post(client)

    assert set(statuses) == {200}
    assert over.status_code == 429 and over.headers["Retry-After"] == "60"
    assert over.json()["limit"] == "120 per 1 minute"
    assert len(fake.calls) == 120


def test_a_pipeline_failure_is_a_sanitized_502(monkeypatch):
    fake = FakeAdvancedRetriever(error=RetrievalError(SECRET))
    client = api_client(monkeypatch)
    app.dependency_overrides[get_advanced_retriever] = lambda: fake

    response = post(client)

    assert response.status_code == 502
    assert response.json() == {"detail": "No se pudo ejecutar la recuperación."}
    assert SECRET not in response.text


def test_an_unexpected_failure_is_also_a_sanitized_502(monkeypatch):
    fake = FakeAdvancedRetriever(error=RuntimeError(SECRET))
    client = api_client(monkeypatch)
    app.dependency_overrides[get_advanced_retriever] = lambda: fake

    response = post(client)

    assert response.status_code == 502 and SECRET not in response.text


def test_a_missing_embedder_is_a_generic_500(monkeypatch):
    fake = FakeAdvancedRetriever(error=EmbedderUnavailableError("no key"))
    client = api_client(monkeypatch)
    app.dependency_overrides[get_advanced_retriever] = lambda: fake

    response = post(client)

    assert response.status_code == 500
    assert response.json() == {"detail": "El servicio de embeddings no está disponible."}


def test_the_session_9_search_endpoint_keeps_its_contract(client):
    # `/v1/retrieval/search` sigue sin diagnóstico de routing: solo chunks, soft-fail y cobertura.
    from app.dependencies import get_grounded_estimator
    from tests._grounded import FakeRetriever, build_estimator

    app.dependency_overrides[get_grounded_estimator] = lambda: build_estimator(retriever=FakeRetriever())

    response = client.post("/v1/retrieval/search", json={"query_text": "payments marketplace"}, headers=HEADERS)

    assert set(response.json()) == {"chunks", "low_confidence", "candidates_evaluated"}
