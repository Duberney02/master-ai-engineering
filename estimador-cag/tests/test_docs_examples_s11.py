"""Los `curl` de la sección «Calidad de la generación (sesión 11)» del README responden (Sesión 11).

Extrae cada `curl` de esa sección y lo ejecuta contra la aplicación con el LLM, el recuperador y Redis falsos (y, para la
expansión del corpus, la base efímera `api-db`): si un ejemplo documentado deja de cumplir el contrato (campo renombrado,
ruta cambiada, clave equivocada), esta prueba falla.
"""

import json
import os
import re
import shlex
from pathlib import Path

import fakeredis
import pytest
from fakeredis import FakeAsyncRedis

from app.config import Settings
from app.dependencies import get_runtime_retrieval_config, get_task_hours_estimator
from app.foundation.llm.runtime_config import RuntimeRetrievalConfig
from app.generation.rag.schemas import RetrievalResult
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
    estimate_payload,
)
from tests.test_corpus_expansion import api, engine  # noqa: F401  (fixtures de la base efímera)
from tests.test_task_hours_api import hist

README = Path(__file__).resolve().parent.parent / "README.md"
SECTION = "### Calidad de la generación (sesión 11)"
KEYS = {"$RETRIEVAL_API_KEY": RETRIEVAL_KEY, "$ESTIMATE_API_KEY": ESTIMATE_KEY}
INDEX = "/embeddings/index"


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


EXAMPLES = documented_curls()
APP_EXAMPLES = [e for e in EXAMPLES if not e["path"].startswith(INDEX)]
INDEX_EXAMPLES = [e for e in EXAMPLES if e["path"].startswith(INDEX)]


class ContradictoryRetriever:
    """Los precedentes de la tarea documentada: 40 h y 90 h a la misma distancia."""

    async def search(self, query_text, **kwargs):
        return RetrievalResult(chunks=[hist(1, 40, 0.1), hist(2, 90, 0.1)], low_confidence=False, candidates_evaluated=2)


@pytest.fixture
def client(monkeypatch, mocker):
    server = fakeredis.FakeServer()
    mocker.patch(
        "app.foundation.llm.runtime_config.Redis.from_url",
        side_effect=lambda url, **kw: FakeAsyncRedis(server=server, decode_responses=kw.get("decode_responses", False)),
    )
    settings = Settings(llm_provider="openai", openai_api_key="sk-test", redis_url="redis://fake/0", _env_file=None)
    runtime = RuntimeRetrievalConfig(settings)
    estimator = build_estimator(ScriptedGenerator(estimate_payload(source_ids=(1,))), FakeRetriever(), runtime_retrieval=runtime)
    client = api_client(monkeypatch, estimator)
    app.dependency_overrides[get_runtime_retrieval_config] = lambda: runtime
    app.dependency_overrides[get_task_hours_estimator] = lambda: TaskHoursEstimator(
        openai_settings(synthesis_enabled=True),
        ContradictoryRetriever(),
        generate=ScriptedGenerator({"reason": "Alcance distinto entre precedentes."}),
    )
    return client


def headers_of(example: dict) -> dict:
    return {"X-API-Key": example["key"]} if example["key"] else {}


def test_the_documented_examples_were_found():
    assert len(EXAMPLES) == 7
    assert {(e["method"], e["path"]) for e in EXAMPLES} == {
        ("PUT", "/api/v1/config/retrieval"),
        ("POST", "/v1/estimate/stages/generate"),
        ("POST", "/v1/estimate/stages/verify"),
        ("POST", "/v1/estimate/tasks/hours"),
        ("POST", "/embeddings/index/runs"),
        ("GET", "/embeddings/index/jobs/<job_id>"),
        ("GET", "/embeddings/index/stats"),
    }


@pytest.mark.parametrize("example", APP_EXAMPLES, ids=[f"{e['method']} {e['path']}" for e in APP_EXAMPLES])
def test_each_documented_curl_responds_200(client, example):
    response = client.request(example["method"], example["path"], json=example["body"], headers=headers_of(example))

    assert response.status_code == 200, response.text


def test_the_documented_flow_matches_the_response_shapes(client):
    by_path = {(e["method"], e["path"]): e for e in EXAMPLES}

    def call(method, path):
        example = by_path[(method, path)]
        return client.request(method, path, json=example["body"], headers=headers_of(example)).json()

    put = call("PUT", "/api/v1/config/retrieval")
    assert put["retrieval"]["hallucination_gate_enabled"]["effective"] is True
    assert put["retrieval"]["augmentation_enabled"]["overridden"] and put["retrieval"]["synthesis_enabled"]["effective"]

    generated = call("POST", "/v1/estimate/stages/generate")
    assert generated["fabricated_source_ids"] == [] and generated["coherent"] is True
    assert generated["citation_report"]["totals"] == {"grounded": 1, "dangling": 0, "insufficient": 0}

    verified = call("POST", "/v1/estimate/stages/verify")
    assert verified["judge_used"] is False and verified["totals"]["degraded"] == 1  # 20 jornadas frente a un ancla de 5
    assert verified["lines"][0]["anchor_days"] == 5

    task = call("POST", "/v1/estimate/tasks/hours")["tasks"][0]
    assert task["estimated_hours"] == 65.0 and (task["hours_range"]["low"], task["hours_range"]["high"]) == (40, 90)


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL no definida")
async def test_the_documented_expansion_examples_respond(api):  # noqa: F811
    by_path = {(e["method"], e["path"]): e for e in INDEX_EXAMPLES}

    runs = by_path[("POST", f"{INDEX}/runs")]
    started = await api.post(runs["path"], json=runs["body"])
    assert started.status_code == 202 and started.json()["documents_total"] == 1

    job = by_path[("GET", f"{INDEX}/jobs/<job_id>")]
    status = await api.get(job["path"].replace("<job_id>", started.json()["job_id"]))
    assert status.status_code == 200 and status.json()["status"] == "completed"
    assert status.json()["documents_processed"] == 1

    stats = await api.get(by_path[("GET", f"{INDEX}/stats")]["path"])
    budget = next(item for item in stats.json()["collections"] if item["collection"] == "budget")
    assert stats.status_code == 200 and budget["documents"] == 1 and budget["hnsw_index"] is True
