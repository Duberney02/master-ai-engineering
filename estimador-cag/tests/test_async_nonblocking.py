"""El bucle asíncrono no se bloquea: ni llamadas síncronas de red ni esperas en serie."""

import ast
import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

from tests._fakes import (
    FakeProvider,
    FakeRedis,
    StreamScript,
    completion,
    make_app,
    make_resources,
    openai_settings,
)

APP_DIR = Path(__file__).resolve().parent.parent / "app"

# Clientes/funciones síncronas de red o de espera que no deben aparecer en el backend.
FORBIDDEN_CALLS = {
    ("time", "sleep"),
    ("requests", "get"),
    ("requests", "post"),
    ("openai", "OpenAI"),
    ("anthropic", "Anthropic"),
    ("redis", "Redis"),
    ("redis", "StrictRedis"),
    ("httpx", "Client"),
}
FORBIDDEN_IMPORTS = {"requests", "urllib.request"}


def test_backend_has_no_synchronous_network_clients():
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [f"{path.name}: import {a.name}" for a in node.names if a.name in FORBIDDEN_IMPORTS]
            elif isinstance(node, ast.ImportFrom):
                if node.module in FORBIDDEN_IMPORTS:
                    offenders.append(f"{path.name}: from {node.module}")
                for alias in node.names:
                    if (node.module, alias.name) in FORBIDDEN_CALLS:
                        offenders.append(f"{path.name}: from {node.module} import {alias.name}")
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if (node.value.id, node.attr) in FORBIDDEN_CALLS:
                    offenders.append(f"{path.name}: {node.value.id}.{node.attr}")
    assert offenders == []


async def test_concurrent_distinct_requests_overlap_with_slow_provider_and_redis():
    redis = FakeRedis()
    redis.delay = 0.05  # Redis lento pero asíncrono
    provider = FakeProvider("openai", [completion(f"r{i}") for i in range(4)], delay=0.3)
    service = make_resources(openai_settings(cache_enabled=True), {"openai": provider}, redis).service

    start = time.monotonic()
    await asyncio.gather(*(service.generate(f"Transcripción distinta número {i} con longitud") for i in range(4)))
    assert time.monotonic() - start < 0.9  # en serie serían ≥ 1.4 s


async def test_streaming_does_not_block_other_requests():
    provider = FakeProvider("openai", [StreamScript(["a"] * 5, delay=0.06), completion("rápido")])
    service = make_resources(openai_settings(), {"openai": provider}).service

    async def consume_stream():
        async for _ in service.stream("Transcripción que se transmite despacio al cliente"):
            pass

    stream_task = asyncio.create_task(consume_stream())
    await asyncio.sleep(0.01)
    start = time.monotonic()
    await service.generate("Otra transcripción distinta que debe responder rápido")
    assert time.monotonic() - start < 0.2
    await stream_task


def test_lifespan_builds_once_and_closes_resources():
    provider = FakeProvider("openai", [])
    redis = FakeRedis()
    resources = make_resources(openai_settings(cache_enabled=True), {"openai": provider}, redis)
    with TestClient(make_app(resources)) as client:
        health = client.get("/health").json()
        assert health["cache"] == {"enabled": True, "reachable": True}
    assert provider.closed and redis.closed
