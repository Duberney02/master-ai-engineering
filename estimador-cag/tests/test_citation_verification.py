"""Citas por línea (Sesión 11): contrato de la tarea, informe `grounded`/`dangling`/`insufficient`, reintento y rebaja."""

import pytest
from pydantic import ValidationError

from app.foundation.prompts.loader import render_rag_template
from app.generation.rag.context_assembler import wrap_chunk
from app.generation.rag.schemas import Estimate, TaskItem
from app.generation.rag.validation import build_citation_report, fabricated_source_ids
from tests._grounded import (
    BRIEF,
    ESTIMATE_KEY,
    TRANSCRIPT,
    FakeRetriever,
    ScriptedGenerator,
    api_client,
    build_estimator,
    estimate_payload,
    line_task,
    make_chunk,
)

HEADERS = {"X-API-Key": ESTIMATE_KEY}
STAGES = "/v1/estimate/stages"


def payload_with(*tasks: dict, total: float | None = None, **overrides) -> dict:
    days = sum(t["engineer_days"] or 0 for t in tasks)
    return estimate_payload(
        modules=[{"name": "Pagos", "description": None, "tasks": list(tasks)}],
        total_engineer_days=days if total is None else total,
        **overrides,
    )


# --- Contrato de la tarea --------------------------------------------------------------------------------------


def test_a_grounded_line_with_sources_validates():
    task = TaskItem.model_validate(line_task(chunk_ids=(1, 2)))

    assert task.grounded and [s.chunk_id for s in task.sources] == [1, 2]
    assert task.sources[0].document_id == 101 and task.sources[0].evidence


def test_a_line_without_data_comes_back_ungrounded_without_sources_or_days():
    task = TaskItem.model_validate(line_task("Integración SAP", chunk_ids=()))

    assert (task.grounded, task.sources, task.engineer_days) == (False, [], None)


@pytest.mark.parametrize(
    "task",
    [
        line_task(chunk_ids=(1,), sources=[]),  # grounded=true sin fuentes
        line_task(chunk_ids=(1,), engineer_days=None),  # grounded=true sin horas
        line_task(chunk_ids=(), sources=[{"chunk_id": 1, "document_id": 1, "evidence": "x"}]),  # sin datos pero con fuentes
        line_task(chunk_ids=(), engineer_days=3),  # sin datos pero con horas
        line_task(chunk_ids=(1,), sources=[{"chunk_id": 1, "document_id": 1, "evidence": ""}]),  # evidencia vacía
        {k: v for k, v in line_task().items() if k != "grounded"},  # `grounded` es obligatorio
    ],
)
def test_integrity_violations_are_rejected(task):
    with pytest.raises(ValidationError):
        TaskItem.model_validate(task)


async def test_a_grounded_line_without_sources_triggers_the_correction_turn():
    bad = payload_with(line_task(chunk_ids=(1,), sources=[]))
    generator = ScriptedGenerator(BRIEF, bad, estimate_payload())

    estimate = await build_estimator(generator).estimate_from_transcript(TRANSCRIPT)

    assert estimate.modules[0].tasks[0].sources and len(generator.calls) == 3
    assert "grounded=true but cites no source" in generator.user_messages()[2]


def test_an_ungrounded_line_does_not_count_towards_the_total():
    estimate = Estimate.model_validate(
        payload_with(line_task("A", 12, (1,)), line_task("B", chunk_ids=()), total=12)
    )

    assert estimate.total_engineer_days == 12


# --- Prompt: document_id y atribución por línea ----------------------------------------------------------------


def test_every_source_exposes_id_and_document_id():
    wrapped = wrap_chunk(make_chunk(7, document_id=42))
    unknown = wrap_chunk(make_chunk(8, document_id=None))

    assert wrapped.startswith('<source id="7" document_id="42" ')
    assert 'document_id="unknown"' in unknown


def test_the_generation_prompt_requires_per_line_attribution():
    system = render_rag_template("generation", "system", {})

    assert "grounded" in system and "chunk_id" in system and "evidence" in system
    assert '"grounded": boolean' in system and "LITERAL" in system


# --- Informe de citas ------------------------------------------------------------------------------------------


def test_the_report_marks_grounded_dangling_and_insufficient_lines():
    estimate = Estimate.model_validate(
        payload_with(
            line_task("OK", 5, (1,)),
            line_task("Colgante", 5, (1, 999)),
            line_task("Sin datos", chunk_ids=()),
            total=10,
            source_ids=(1, 2),
        )
    )

    report = build_citation_report(estimate, {1, 2})

    assert [(v.task, v.status) for v in report.lines] == [
        ("OK", "grounded"),
        ("Colgante", "dangling"),
        ("Sin datos", "insufficient"),
    ]
    assert (report.totals.grounded, report.totals.dangling, report.totals.insufficient) == (1, 1, 1)
    assert report.lines[1].dangling_ids == [999]
    assert report.dangling_citations == [999] and report.verified_citations == [1, 2]


def test_the_report_also_checks_global_citations():
    estimate = Estimate.model_validate(estimate_payload(source_ids=(1, 77)))

    report = build_citation_report(estimate, {1})

    assert report.dangling_citations == [77] and report.verified_citations == [1]
    assert fabricated_source_ids(estimate, {1}) == [77]


def test_a_dangling_line_citation_alone_counts_as_fabricated():
    estimate = Estimate.model_validate(payload_with(line_task("X", 5, (1, 999)), source_ids=(1,)))

    assert fabricated_source_ids(estimate, {1}) == [999]


# --- Pipeline: reintento y rebaja -----------------------------------------------------------------------------


async def test_a_dangling_line_citation_is_retried_once_and_repaired():
    dangling = payload_with(line_task("KYC", 12, (999,)), source_ids=(1,))
    generator = ScriptedGenerator(BRIEF, dangling, estimate_payload(source_ids=(1,)))

    estimate = await build_estimator(generator).estimate_from_transcript(TRANSCRIPT)

    assert estimate.confidence == "high" and len(generator.calls) == 3
    assert "999" in generator.user_messages()[2]


async def test_persistent_dangling_line_citations_downgrade_the_confidence():
    dangling = payload_with(line_task("KYC", 12, (999,)), source_ids=(1,))
    generator = ScriptedGenerator(BRIEF, dangling, dangling)

    estimate = await build_estimator(generator).estimate_from_transcript(TRANSCRIPT)

    assert estimate.confidence == "low" and len(generator.calls) == 3


# --- Etapa generate --------------------------------------------------------------------------------------------


def test_the_generate_stage_returns_the_per_line_report_without_retrying(monkeypatch):
    chunks = [make_chunk(1), make_chunk(2, 0.3)]
    dangling = payload_with(line_task("OK", 5, (1,)), line_task("Colgante", 7, (999,)), source_ids=(1,))
    generator = ScriptedGenerator(dangling)
    client = api_client(monkeypatch, build_estimator(generator, FakeRetriever(chunks)))

    response = client.post(
        f"{STAGES}/generate",
        json={"context_block": "ctx", "query": BRIEF, "kept_chunks": [c.model_dump() for c in chunks]},
        headers=HEADERS,
    )

    body = response.json()
    assert response.status_code == 200 and len(generator.calls) == 1  # sin reintentos
    assert body["fabricated_source_ids"] == [999]
    report = body["citation_report"]
    assert [(v["task"], v["status"]) for v in report["lines"]] == [("OK", "grounded"), ("Colgante", "dangling")]
    assert report["dangling_citations"] == [999] and report["totals"]["dangling"] == 1
