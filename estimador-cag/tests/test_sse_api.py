"""Endpoint SSE `/api/v1/estimate/stream`: contrato de eventos, errores, caché y desconexión."""

import asyncio
import json

import pytest

from app.llm.errors import LLMAuthError, LLMUnavailableError
from app.routers.estimations import _sse_events
from app.services.estimation_service import GenerationOptions
from app.transport.sse import HEARTBEAT, format_sse, with_heartbeat
from estimator_client.sse import iter_sse
from tests._fakes import (
    FakeProvider,
    FakeRedis,
    StreamScript,
    completion,
    make_client,
    make_resources,
    openai_settings,
)

URL = "/api/v1/estimate/stream"
T = "Transcripción de una reunión con suficiente longitud para el test"
MULTILINE = ["## Estimación: Demo\n", "\n### Supuestos\n", "-  dos espacios  \n", "\r\nfin ok"]


def _events(client, body, **kw):
    with client.stream("POST", URL, json=body, **kw) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        raw = "".join(resp.iter_text())
    return [(e.event, json.loads(e.data)) for e in iter_sse([raw])], raw


@pytest.fixture
def provider():
    return FakeProvider("openai", [])


@pytest.fixture
def resources(provider):
    return make_resources(openai_settings(cache_enabled=True), {"openai": provider}, FakeRedis())


@pytest.fixture
def client(resources):
    with make_client(resources) as c:
        yield c


def test_successful_stream_follows_the_contract_and_preserves_multiline_content(client, provider):
    provider.outcomes = [StreamScript(MULTILINE, model="gpt-4o-mini-2024-07-18")]
    events, raw = _events(client, {"transcription": T})

    names = [name for name, _ in events]
    assert names[0] == "start" and names[-2:] == ["metadata", "done"]
    assert set(names[1:-2]) == {"delta"}
    assert "".join(data["text"] for name, data in events if name == "delta") == "".join(MULTILINE)
    # Cada `data:` es una sola línea: el contenido multilínea nunca rompe el framing SSE.
    assert all(not line or line.startswith(("event: ", "data: ")) for line in raw.split("\n"))

    meta = dict(events)["metadata"]
    assert meta["model"] == "gpt-4o-mini-2024-07-18" and meta["provider"] == "openai"
    assert meta["usage"]["phases"][0]["requested_model"] == "gpt-4o-mini"
    assert meta["finish_reason"] == "stop" and meta["cache"]["status"] == "miss"
    assert meta["cost"]["incurred_usd"] is not None and "evaluation" in meta
    assert "estimation" not in meta  # el texto viaja solo en los deltas
    assert dict(events)["done"] == {"status": "completed"}


def test_two_phase_stream_keeps_extraction_separate(client, provider):
    provider.outcomes = [completion("### Requisitos funcionales\n- Pagos"), StreamScript(["## Estimación"])]
    events, _ = _events(client, {"transcription": T, "preprocessing": "two_phase"})
    names = [n for n, _ in events]
    assert names == ["start", "extraction", "delta", "metadata", "done"]
    extraction = dict(events)["extraction"]
    assert extraction == {"phase": "preprocessing", "text": "### Requisitos funcionales\n- Pagos", "cache": "miss"}
    deltas = "".join(d["text"] for n, d in events if n == "delta")
    assert "Requisitos funcionales" not in deltas
    meta = dict(events)["metadata"]
    assert meta["cache"]["phases"] == {"preprocessing": "miss", "estimation": "miss"}
    assert meta["extracted_requirements"].startswith("### Requisitos")
    # La extracción usa generación normal; la estimación, streaming.
    assert [c[2] for c in provider.calls] == ["complete", "stream"]


@pytest.mark.parametrize(
    "body",
    [
        {"transcription": "corta"},
        {"transcription": T, "thinking_budget": 1000},  # opción no soportada: no se ignora
        {"transcription": T, "num_examples": 99},
        {"transcription": T, "model": "llama-3"},  # proveedor no resoluble
        {"transcription": T, "model": "claude-haiku-4-5"},  # proveedor sin credenciales
    ],
)
def test_invalid_requests_are_rejected_before_opening_the_stream(client, provider, body):
    resp = client.post(URL, json=body)
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/json")
    assert provider.calls == []


def test_provider_error_after_start_is_a_sanitised_error_event(client, provider):
    provider.outcomes = [LLMAuthError("detalle interno sk-secret")] + [LLMAuthError()] * 3
    events, raw = _events(client, {"transcription": T})
    assert [n for n, _ in events] == ["start", "error"]
    error = dict(events)["error"]
    assert error == {"code": "provider_auth", "message": "LLM authentication failed", "status": 502,
                     "retryable": False, "partial": False}
    assert "sk-secret" not in raw


def test_error_after_content_is_marked_partial_and_not_cached(client, provider, resources):
    provider.outcomes = [StreamScript(["## Parcial"], error=LLMUnavailableError(), error_after=1)]
    events, _ = _events(client, {"transcription": T})
    assert [n for n, _ in events] == ["start", "delta", "error"]
    assert dict(events)["error"]["partial"] is True
    assert dict(events)["error"]["code"] == "stream_interrupted"
    assert resources.cache._redis.store == {}


def test_cache_hit_over_sse_respects_the_same_contract(client, provider):
    provider.outcomes = [StreamScript(MULTILINE, input_tokens=800, output_tokens=200)]
    first, _ = _events(client, {"transcription": T})
    second, _ = _events(client, {"transcription": T})

    assert len(provider.calls) == 1
    assert [n for n, _ in second][0] == "start" and [n for n, _ in second][-2:] == ["metadata", "done"]
    text = lambda evs: "".join(d["text"] for n, d in evs if n == "delta")  # noqa: E731
    assert text(second) == text(first).strip()  # el texto cacheado se normaliza sin espacios extremos
    m1, m2 = dict(first)["metadata"], dict(second)["metadata"]
    assert m2["cache"]["status"] == "hit"
    assert m2["cost"]["incurred_usd"] == 0.0
    assert m2["cost"]["original_generation_usd"] == m1["cost"]["original_generation_usd"]
    assert m2["usage"]["input_tokens"] == 800 and m2["usage"]["incurred_total_tokens"] == 0
    for key in ("model", "provider", "finish_reason"):
        assert m2[key] == m1[key]


def test_stream_result_is_reused_by_normal_endpoint_with_correct_metadata(client, provider):
    provider.outcomes = [StreamScript(["## Estimación"], model="gpt-4o-mini-2024-07-18")]
    streamed, _ = _events(client, {"transcription": T})
    normal = client.post("/api/v1/estimate", json={"transcription": T}).json()
    assert len(provider.calls) == 1
    assert normal["estimation"] == "## Estimación"
    assert normal["cache"]["status"] == "hit" and normal["estimated_cost_usd"] == 0.0
    assert normal["model"] == dict(streamed)["metadata"]["model"] == "gpt-4o-mini-2024-07-18"


def test_explicit_model_in_stream_respects_policy(client, provider):
    provider.outcomes = [StreamScript(["ok"], model="gpt-4o")]
    events, _ = _events(client, {"transcription": T, "model": "gpt-4o"})
    assert dict(events)["start"]["route"] == ["openai/gpt-4o"]
    assert provider.calls[0][0] == "gpt-4o"


async def test_client_disconnect_releases_resources_and_leaves_no_cache(resources, provider):
    provider.outcomes = [StreamScript(["uno ", "dos ", "tres"], delay=0.01)]
    options = GenerationOptions()
    route = resources.service.resolve_route(options)
    events = _sse_events(resources.service, T, options, route, pricing_source="t", request_id="r")
    assert (await anext(events)).startswith("event: start")
    assert (await anext(events)).startswith("event: delta")
    await events.aclose()  # desconexión
    assert provider.stream_closed == 1
    assert resources.cache._redis.store == {}


async def test_heartbeat_is_sent_while_waiting_and_source_is_closed():
    closed = asyncio.Event()

    async def slow():
        try:
            await asyncio.sleep(0.12)
            yield format_sse("delta", {"text": "x"})
        finally:
            closed.set()

    chunks = [c async for c in with_heartbeat(slow(), interval=0.05)]
    assert chunks.count(HEARTBEAT) >= 1 and chunks[-1].startswith("event: delta")
    assert closed.is_set()


def test_format_sse_roundtrip():
    out = format_sse("x", {"a": 1})
    assert out == 'event: x\ndata: {"a": 1}\n\n'
    decoded = list(iter_sse([out]))
    assert decoded[0].event == "x" and json.loads(decoded[0].data) == {"a": 1}
