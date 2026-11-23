"""Los `curl` de la sección «Recuperación avanzada y horas por tarea (sesión 10)» del README responden (Sesión 10).

Extrae cada `curl` de esa sección y lo ejecuta contra la aplicación con el recuperador, el LLM y Redis falsos: si un
ejemplo documentado deja de cumplir el contrato (campo renombrado, ruta cambiada, clave equivocada), esta prueba falla.
"""

import json
import re
import shlex
from pathlib import Path

import fakeredis
import pytest
from fakeredis import FakeAsyncRedis

from app.config import Settings
from app.dependencies import get_advanced_retriever, get_runtime_retrieval_config, get_task_hours_estimator
from app.foundation.llm.runtime_config import RuntimeRetrievalConfig
from app.generation.rag.task_hours import TaskHoursEstimator
from app.main import app
from tests._fakes import openai_settings
from tests._grounded import (
    ESTIMATE_KEY,
    RETRIEVAL_KEY,
    FakeRetriever,
    ScriptedGenerator,
    api_client,
    build_estimator,
)
from tests.test_advanced_search_api import FakeAdvancedRetriever
from tests.test_task_hours_api import DRAFT, HoursRetriever, hist

README = Path(__file__).resolve().parent.parent / "README.md"
SECTION = "### Recuperación avanzada y horas por tarea (sesión 10)"
KEYS = {"$RETRIEVAL_API_KEY": RETRIEVAL_KEY, "$ESTIMATE_API_KEY": ESTIMATE_KEY}


def documented_curls() -> list[dict]:
    """Cada `curl` de la sección: método, ruta, cabecera de clave y cuerpo JSON (si lo hay)."""
    text = README.read_text(encoding="utf-8")
    section = text[text.index(SECTION) :]
    section = section[: section.index("\n### ", 10)]
    commands = []
    for block in re.findall(r"```bash\n(.*?)```", section, re.S):
        for command in re.findall(r"^curl .*?(?=\n(?!  )|\Z)", block, re.S | re.M):
            tokens = shlex.split(command.replace("\\\n", " "))
            url = next(token for token in tokens if token.startswith("http"))
            headers = [tokens[i + 1] for i, token in enumerate(tokens) if token == "-H"]
            key = next((h.split(": ", 1)[1] for h in headers if h.startswith("X-API-Key")), None)
            method = tokens[tokens.index("-X") + 1] if "-X" in tokens else "GET"
            body = json.loads(tokens[tokens.index("-d") + 1]) if "-d" in tokens else None
            commands.append(
                {"method": method, "path": url.removeprefix("http://localhost:8000"), "key": KEYS.get(key, key), "body": body}
            )
    return commands


class DocsHoursRetriever(HoursRetriever):
    """El ejemplo documentado lleva descripción: el texto de búsqueda termina en ella, no en el nombre de la tarea."""

    async def search(self, query_text, **kwargs):
        task = next((name for name in self.by_task if f"Task: {name}" in query_text), None)
        return await super().search(f"Task: {task}" if task else query_text, **kwargs)


EXAMPLES = documented_curls()


@pytest.fixture
def client(monkeypatch, mocker):
    server = fakeredis.FakeServer()
    mocker.patch(
        "app.foundation.llm.runtime_config.Redis.from_url",
        side_effect=lambda url, **kw: FakeAsyncRedis(server=server, decode_responses=kw.get("decode_responses", False)),
    )
    runtime = RuntimeRetrievalConfig(
        Settings(llm_provider="openai", openai_api_key="sk-test", redis_url="redis://fake/0", _env_file=None)
    )
    estimator = build_estimator(ScriptedGenerator(), FakeRetriever(), runtime_retrieval=runtime)
    client = api_client(monkeypatch, estimator)
    hours_retriever = DocsHoursRetriever({"KYC onboarding": [hist(1, 10, 0.1), hist(2, 30, 0.4)]})
    app.dependency_overrides[get_advanced_retriever] = lambda: FakeAdvancedRetriever()
    app.dependency_overrides[get_runtime_retrieval_config] = lambda: runtime
    app.dependency_overrides[get_task_hours_estimator] = lambda: TaskHoursEstimator(openai_settings(), hours_retriever)
    # `structure` es la única etapa con LLM de los ejemplos: su orquestador lleva un generador con la estructura.
    client.holder["estimator"] = build_estimator(ScriptedGenerator(DRAFT), FakeRetriever(), runtime_retrieval=runtime)
    return client


def test_the_documented_examples_were_found():
    assert len(EXAMPLES) == 6
    assert {(e["method"], e["path"]) for e in EXAMPLES} == {
        ("POST", "/v1/retrieval/search"),
        ("POST", "/v1/retrieval/advanced-search"),
        ("PUT", "/api/v1/config/retrieval"),
        ("GET", "/api/v1/config/retrieval"),
        ("POST", "/v1/estimate/stages/structure"),
        ("POST", "/v1/estimate/tasks/hours"),
    }


@pytest.mark.parametrize("example", EXAMPLES, ids=[f"{e['method']} {e['path']}" for e in EXAMPLES])
def test_each_documented_curl_responds_200(client, example):
    headers = {"X-API-Key": example["key"]} if example["key"] else {}

    response = client.request(example["method"], example["path"], json=example["body"], headers=headers)

    assert response.status_code == 200, response.text


def test_the_documented_flow_matches_the_response_shapes(client):
    by_path = {(e["method"], e["path"]): e for e in EXAMPLES}

    def call(method, path):
        example = by_path[(method, path)]
        headers = {"X-API-Key": example["key"]} if example["key"] else {}
        return client.request(method, path, json=example["body"], headers=headers).json()

    assert set(call("POST", "/v1/retrieval/search")) == {"chunks", "low_confidence", "candidates_evaluated"}
    assert {"routing", "technique", "subqueries", "cardinality"} <= set(call("POST", "/v1/retrieval/advanced-search"))
    put = call("PUT", "/api/v1/config/retrieval")
    assert put["retrieval"]["search_mode"]["effective"] == "hybrid"
    assert put["retrieval"]["rerank"]["overridden"] is False  # `"rerank": null` restablece
    assert call("GET", "/api/v1/config/retrieval") == put
    structure = call("POST", "/v1/estimate/stages/structure")
    assert all(t["engineer_days"] is None for m in structure["modules"] for t in m["tasks"])
    hours = call("POST", "/v1/estimate/tasks/hours")["tasks"][0]
    assert hours["has_match"] is True and hours["estimated_hours"] == 14.0
