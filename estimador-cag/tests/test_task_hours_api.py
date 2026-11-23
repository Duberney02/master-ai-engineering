"""`POST /v1/estimate/stages/structure` y `POST /v1/estimate/tasks/hours` (Sesión 10)."""

import pytest

from app.dependencies import get_task_hours_estimator
from app.generation.rag.errors import EmbedderUnavailableError, RetrievalError
from app.generation.rag.schemas import MAX_TASKS_PER_REQUEST, RetrievalResult, RetrievedChunk
from app.generation.rag.task_hours import TaskHoursEstimator
from app.main import app
from tests._fakes import openai_settings
from tests._grounded import (
    BRIEF,
    ESTIMATE_KEY,
    RETRIEVAL_KEY,
    SECRET,
    ScriptedGenerator,
    api_client,
    build_estimator,
)

HEADERS = {"X-API-Key": ESTIMATE_KEY}
STRUCTURE = "/v1/estimate/stages/structure"
HOURS = "/v1/estimate/tasks/hours"

DRAFT = {
    "modules": [
        {
            "name": "Authentication & Access",
            "description": "Identity and sessions",
            "tasks": [
                {"name": "OAuth2 login", "description": "Authorization-code flow with PKCE"},
                {"name": "Role-based access", "description": None},
            ],
        },
        {"name": "Payments & Billing", "description": None, "tasks": [{"name": "Stripe checkout", "description": None}]},
    ],
    "assumptions": ["Single tenant"],
}


# --- Estructura sin horas ----------------------------------------------------------------------------------------


def structure_client(monkeypatch, generator=None):
    generator = generator or ScriptedGenerator(DRAFT)
    client = api_client(monkeypatch, build_estimator(generator))
    client.generator = generator
    return client


def test_every_task_of_the_structure_has_null_hours(monkeypatch):
    client = structure_client(monkeypatch)

    response = client.post(STRUCTURE, json={"query": BRIEF}, headers=HEADERS)

    body = response.json()
    assert response.status_code == 200
    assert [m["name"] for m in body["modules"]] == ["Authentication & Access", "Payments & Billing"]
    tasks = [task for module in body["modules"] for task in module["tasks"]]
    assert [t["name"] for t in tasks] == ["OAuth2 login", "Role-based access", "Stripe checkout"]
    assert all("engineer_days" in t and t["engineer_days"] is None for t in tasks)  # la clave existe y es nula
    assert body["assumptions"] == ["Single tenant"]
    assert "sources" not in body  # sin recuperación ni citas


def test_hours_the_model_volunteers_are_discarded(monkeypatch):
    draft = {
        "modules": [
            {"name": "Core", "tasks": [{"name": "Domain model", "description": None, "engineer_days": 12, "hours": 96}]}
        ]
    }
    client = structure_client(monkeypatch, ScriptedGenerator(draft))

    body = client.post(STRUCTURE, json={"query": BRIEF}, headers=HEADERS).json()

    assert body["modules"][0]["tasks"][0] == {"name": "Domain model", "description": None, "engineer_days": None}


def test_the_structure_prompt_carries_the_brief_and_forbids_hours(monkeypatch):
    client = structure_client(monkeypatch)

    client.post(STRUCTURE, json={"query": BRIEF}, headers=HEADERS)

    system, user = client.generator.calls[0]["messages"][0]["content"], client.generator.calls[0]["messages"][-1]["content"]
    assert "NO incluyas horas" in system
    assert BRIEF["function"] in user and "stripe, sap" in user


def test_the_structure_stage_never_retrieves(monkeypatch):
    from tests._grounded import FakeRetriever

    retriever = FakeRetriever()
    client = api_client(monkeypatch, build_estimator(ScriptedGenerator(DRAFT), retriever))

    client.post(STRUCTURE, json={"query": BRIEF}, headers=HEADERS)

    assert retriever.calls == []


@pytest.mark.parametrize("failure", [RuntimeError(SECRET), "no es JSON", {"modules": []}])
def test_a_structure_failure_is_a_sanitized_502(monkeypatch, failure):
    client = structure_client(monkeypatch, ScriptedGenerator(failure, failure))

    response = client.post(STRUCTURE, json={"query": BRIEF}, headers=HEADERS)

    assert response.status_code == 502
    assert response.json() == {"detail": "No se pudo generar la estructura."}
    assert SECRET not in response.text


@pytest.mark.parametrize("body", [{}, {"query": {}}, {"query": {"function": ""}}])
def test_an_invalid_structure_request_is_422(monkeypatch, body):
    client = structure_client(monkeypatch)

    assert client.post(STRUCTURE, json=body, headers=HEADERS).status_code == 422
    assert client.generator.calls == []


def test_the_structure_stage_needs_the_estimate_key(monkeypatch):
    client = structure_client(monkeypatch)

    assert client.post(STRUCTURE, json={"query": BRIEF}).status_code == 401
    assert client.post(STRUCTURE, json={"query": BRIEF}, headers={"X-API-Key": RETRIEVAL_KEY}).status_code == 401


# --- Horas por tarea ---------------------------------------------------------------------------------------------


def hist(chunk_id: int, hours: float | None, distance: float) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        content="t",
        chunk_type="historical_task",
        distance=distance,
        budget_id=f"BUD-{chunk_id}",
        estimated_hours=hours,
    )


class HoursRetriever:
    def __init__(self, by_task=None, error: Exception | None = None) -> None:
        self.by_task, self.error, self.calls = by_task or {}, error, []

    async def search(self, query_text, *, top_k, distance_threshold, filters, **extra):
        self.calls.append({"query_text": query_text, "top_k": top_k, "distance_threshold": distance_threshold, **extra})
        if self.error:
            raise self.error
        for task, chunks in self.by_task.items():
            if query_text.endswith(f"Task: {task}"):
                return RetrievalResult(chunks=chunks, low_confidence=False, candidates_evaluated=9)
        return RetrievalResult(chunks=[], low_confidence=True, candidates_evaluated=9)


def hours_client(monkeypatch, retriever=None, **keys):
    retriever = retriever or HoursRetriever({"KYC onboarding": [hist(1, 10, 0.1), hist(2, 30, 0.4)]})
    client = api_client(monkeypatch, **keys)
    app.dependency_overrides[get_task_hours_estimator] = lambda: TaskHoursEstimator(openai_settings(), retriever)
    client.retriever = retriever
    return client


def hours_body(*tasks: str, module: str = "Compliance") -> dict:
    return {"modules": [{"name": module, "tasks": [{"name": task, "description": None} for task in tasks]}]}


def test_the_weighted_consensus_leans_towards_the_closer_neighbour(monkeypatch):
    client = hours_client(monkeypatch)

    response = client.post(HOURS, json=hours_body("KYC onboarding"), headers=HEADERS)

    task = response.json()["tasks"][0]
    assert response.status_code == 200
    assert task["estimated_hours"] == 14.0 and abs(task["estimated_hours"] - 10) < abs(task["estimated_hours"] - 30)
    assert task["has_match"] is True and 0 < task["reliability"] < 1 and task["dispersion"] == 0.5
    assert [(n["source_id"], n["budget_id"], n["estimated_hours"], n["distance"]) for n in task["neighbors"]] == [
        (1, "BUD-1", 10.0, 0.1),
        (2, "BUD-2", 30.0, 0.4),
    ]
    assert (task["module"], task["task"]) == ("Compliance", "KYC onboarding")


def test_a_task_without_neighbours_under_the_threshold_has_no_match_and_null_hours(monkeypatch):
    client = hours_client(monkeypatch)

    response = client.post(HOURS, json=hours_body("KYC onboarding", "Quantum gardening"), headers=HEADERS)

    unmatched = response.json()["tasks"][1]
    assert unmatched == {
        "module": "Compliance",
        "task": "Quantum gardening",
        "estimated_hours": None,
        "reliability": None,
        "has_match": False,
        "dispersion": None,
        "neighbors": [],
    }


def test_the_structure_response_can_be_sent_back_as_is(monkeypatch):
    structure = structure_client(monkeypatch).post(STRUCTURE, json={"query": BRIEF}, headers=HEADERS).json()
    client = hours_client(monkeypatch, HoursRetriever())

    response = client.post(HOURS, json={"modules": structure["modules"]}, headers=HEADERS)

    assert response.status_code == 200
    assert [t["task"] for t in response.json()["tasks"]] == ["OAuth2 login", "Role-based access", "Stripe checkout"]


def test_the_search_uses_the_configured_k_and_threshold(monkeypatch):
    client = hours_client(monkeypatch)

    client.post(HOURS, json=hours_body("KYC onboarding"), headers=HEADERS)

    call = client.retriever.calls[0]
    assert (call["top_k"], call["distance_threshold"]) == (5, 0.45)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"modules": []},
        {"modules": [{"name": "Empty", "tasks": []}]},
        {"modules": [{"name": "", "tasks": [{"name": "x"}]}]},
        {"modules": [{"name": "M", "tasks": [{"name": ""}]}]},
        {"modules": [{"name": "M", "tasks": [{"name": f"t{i}"} for i in range(51)]}]},
        {"modules": [{"name": f"M{m}", "tasks": [{"name": f"t{t}"} for t in range(50)]} for m in range(4)]},
    ],
)
def test_invalid_task_payloads_are_422_and_never_search(monkeypatch, body):
    client = hours_client(monkeypatch)

    assert client.post(HOURS, json=body, headers=HEADERS).status_code == 422
    assert client.retriever.calls == []


def test_the_task_cap_is_enforced_across_modules(monkeypatch):
    client = hours_client(monkeypatch)
    modules = [{"name": f"M{m}", "tasks": [{"name": f"t{m}-{t}"} for t in range(30)]} for m in range(6)]  # 180 tareas

    assert MAX_TASKS_PER_REQUEST == 150
    assert client.post(HOURS, json={"modules": modules}, headers=HEADERS).status_code == 422


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-API-Key": RETRIEVAL_KEY}])
def test_a_missing_or_wrong_key_is_401(monkeypatch, headers):
    client = hours_client(monkeypatch)

    assert client.post(HOURS, json=hours_body("KYC onboarding"), headers=headers).status_code == 401
    assert client.retriever.calls == []


def test_the_rate_limit_is_30_per_minute_with_retry_after(monkeypatch):
    client = hours_client(monkeypatch)

    statuses = [client.post(HOURS, json=hours_body("KYC onboarding"), headers=HEADERS).status_code for _ in range(30)]
    over = client.post(HOURS, json=hours_body("KYC onboarding"), headers=HEADERS)

    assert set(statuses) == {200} and over.status_code == 429 and over.headers["Retry-After"] == "60"


@pytest.mark.parametrize("error", [RetrievalError(SECRET), EmbedderUnavailableError(SECRET), RuntimeError(SECRET)])
def test_a_pipeline_failure_is_a_sanitized_502(monkeypatch, error):
    client = hours_client(monkeypatch, HoursRetriever(error=error))

    response = client.post(HOURS, json=hours_body("KYC onboarding"), headers=HEADERS)

    assert response.status_code == 502
    assert response.json() == {"detail": "No se pudieron estimar las horas por tarea."}
    assert SECRET not in response.text
