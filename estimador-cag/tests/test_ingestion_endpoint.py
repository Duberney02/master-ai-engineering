"""Endpoints de ingesta de extremo a extremo con SQLite en memoria (repositorio de trabajos real).

`get_session` y `SessionLocal` apuntan a un motor SQLite compartido, de modo que se ejercitan el router, el
orquestador en segundo plano y `JobsRepository` reales sin PostgreSQL (la prueba contra PostgreSQL está en
`test_ingestion_postgres.py`).
"""

import textwrap

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.dependencies import get_catalog, get_filesystem_loader, get_parser_registry
from app.foundation.persistence.database import get_session
from app.foundation.persistence.models import Base
from app.ingestion.catalog.loader import load_catalog
from app.ingestion.loaders.filesystem import FileSystemLoader
from app.ingestion.parsers.registry import default_registry
from app.main import app
from tests._fakes import openai_settings

CATALOG = """
version: "1.0.0"
sources:
  - name: tiny_json
    location: budgets
    format: json
    quality: {completeness: 4, consistency: 4, actuality: 5, reliability: 4}
    sensitivity: {has_pii: false, pii_flags: []}
    decision: include
  - name: missing_json
    location: nowhere
    format: json
    quality: {completeness: 4, consistency: 4, actuality: 5, reliability: 4}
    sensitivity: {has_pii: false, pii_flags: []}
    decision: include
  - name: review_txt
    location: transcripts
    format: txt
    quality: {completeness: 3, consistency: 2, actuality: 4, reliability: 3}
    sensitivity: {has_pii: true, pii_flags: ["PERSON"]}
    decision: review
    decision_reason: "formato heredado pendiente de revisión"
  - name: excluded_xlsx
    location: rate_card.xlsx
    format: xlsx
    quality: {completeness: 4, consistency: 5, actuality: 1, reliability: 4}
    sensitivity: {has_pii: false, pii_flags: []}
    decision: exclude
    decision_reason: "actuality=1 — obsoleta"
"""


@pytest.fixture
async def ingestion_client(tmp_path, monkeypatch):
    (tmp_path / "catalog.yaml").write_text(textwrap.dedent(CATALOG), encoding="utf-8")
    budgets = tmp_path / "budgets"
    budgets.mkdir()
    for number in (1, 2):
        (budgets / f"BUDGET-2024-000{number}.json").write_text(
            f'{{"budget_id":"BUDGET-2024-000{number}","currency":"EUR","total_amount":100,"signed_at":"2024-01-01"}}',
            encoding="utf-8",
        )
    (budgets / "notas.txt").write_text("se ignora: no es JSON", encoding="utf-8")

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with sessions() as session:
            yield session

    catalog = load_catalog(tmp_path / "catalog.yaml")
    app.dependency_overrides[get_catalog] = lambda: catalog
    app.dependency_overrides[get_filesystem_loader] = lambda: FileSystemLoader(data_root=tmp_path)
    app.dependency_overrides[get_parser_registry] = default_registry
    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr("app.api.ingestion.SessionLocal", sessions)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
    await engine.dispose()


async def _run(client, source_name):
    return await client.post("/api/v1/ingestion/runs", json={"source_name": source_name})


async def test_post_run_returns_202_with_a_pending_job(ingestion_client):
    response = await _run(ingestion_client, "tiny_json")

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "pending" and body["source_name"] == "tiny_json" and body["job_id"]


async def test_get_job_reflects_the_completed_run(ingestion_client):
    job_id = (await _run(ingestion_client, "tiny_json")).json()["job_id"]

    response = await ingestion_client.get(f"/api/v1/ingestion/jobs/{job_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed" and body["documents_count"] == 2
    assert body["error_message"] is None and body["finished_at"] is not None and body["started_at"]


async def test_failed_run_is_persisted_with_its_error(ingestion_client):
    job_id = (await _run(ingestion_client, "missing_json")).json()["job_id"]

    body = (await ingestion_client.get(f"/api/v1/ingestion/jobs/{job_id}")).json()

    assert body["status"] == "failed" and "nowhere" in body["error_message"]
    assert body["documents_count"] == 0 and body["finished_at"] is not None


async def test_unknown_source_is_404(ingestion_client):
    response = await _run(ingestion_client, "does_not_exist")

    assert response.status_code == 404
    assert response.json()["detail"]["reason"] == "unknown_source"


@pytest.mark.parametrize("name, decision", [("review_txt", "review"), ("excluded_xlsx", "exclude")])
async def test_review_and_excluded_sources_are_400(ingestion_client, name, decision):
    response = await _run(ingestion_client, name)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["reason"] == "source_not_included" and detail["decision"] == decision
    assert detail["decision_reason"]


async def test_no_job_is_created_for_rejected_sources(ingestion_client):
    await _run(ingestion_client, "excluded_xlsx")
    await _run(ingestion_client, "does_not_exist")

    from app.foundation.persistence.repositories.jobs import list_jobs

    async for session in app.dependency_overrides[get_session]():
        assert await list_jobs(session) == []


async def test_get_unknown_job_is_404(ingestion_client):
    response = await ingestion_client.get("/api/v1/ingestion/jobs/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404


async def test_invalid_body_is_422(ingestion_client):
    empty = await ingestion_client.post("/api/v1/ingestion/runs", json={"source_name": ""})
    extra = await ingestion_client.post("/api/v1/ingestion/runs", json={"source_name": "tiny_json", "x": 1})

    assert empty.status_code == extra.status_code == 422


async def test_only_the_two_documented_endpoints_are_exposed():
    paths = app.openapi()["paths"]
    routes = {(m.upper(), path) for path, item in paths.items() if path.startswith("/api/v1/ingestion") for m in item}

    assert routes == {("POST", "/api/v1/ingestion/runs"), ("GET", "/api/v1/ingestion/jobs/{job_id}")}


async def test_endpoints_answer_503_without_database_configured(mocker):
    mocker.patch("app.foundation.persistence.database.get_settings", return_value=openai_settings(database_url=None))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/ingestion/jobs/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 503
