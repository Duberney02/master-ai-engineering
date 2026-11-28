"""Gate de alucinaciones (Sesión 11): ancla numérica, juez en una sola llamada, rebaja de confianza y etapa `verify`."""

import pytest

from app.generation.rag.quality.hallucination import chunk_hours, gate_line, numeric_anchor, run_gate
from app.generation.rag.schemas import Estimate, TaskItem
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
VERIFY = "/v1/estimate/stages/verify"


def task(days: float, chunk_ids=(1,), name="KYC") -> TaskItem:
    return TaskItem.model_validate(line_task(name, days, chunk_ids))


def payload(*tasks: dict, **overrides) -> dict:
    total = sum(t["engineer_days"] or 0 for t in tasks)
    return estimate_payload(
        modules=[{"name": "Pagos", "description": None, "tasks": list(tasks)}], total_engineer_days=total, **overrides
    )


def judge_reply(*supported: bool) -> dict:
    return {"lines": [{"index": i, "supported": ok, "reason": "no coincide" if not ok else "ok"} for i, ok in enumerate(supported)]}


# --- Ancla numérica (funciones puras) --------------------------------------------------------------------------


def test_chunk_hours_come_from_metadata_or_from_the_text():
    assert chunk_hours(make_chunk(1, estimated_hours=24)) == 24
    assert chunk_hours(make_chunk(2, content="KYC. Estimated hours: 40")) == 40
    assert chunk_hours(make_chunk(3, content="Estimated hours: 12,5")) == 12.5
    assert chunk_hours(make_chunk(4, content="sin cifra de horas")) is None


def test_the_anchor_is_the_cited_chunks_hours_in_8_hour_days():
    chunks = {1: make_chunk(1, estimated_hours=40), 2: make_chunk(2, estimated_hours=24)}

    assert numeric_anchor(task(1, (1,)), chunks) == 5
    assert numeric_anchor(task(1, (1, 2)), chunks) == 8
    assert numeric_anchor(task(1, (3,)), chunks) is None  # chunk fuera del contexto
    assert numeric_anchor(task(1, (1,)), {1: make_chunk(1, content="sin cifra")}) is None


def test_an_overestimating_line_is_degraded_with_the_deviation_in_the_reason():
    verdict = gate_line("Pagos", task(20), 5.0, tolerance=0.5)

    assert verdict.status == "degraded"
    assert "20 jornadas" in verdict.reason and "~5" in verdict.reason and "+300 %" in verdict.reason
    assert (verdict.claimed_days, verdict.anchor_days) == (20, 5.0)


def test_a_line_that_is_a_fraction_of_the_component_stays_grounded():
    assert gate_line("Pagos", task(3), 10.0, tolerance=0.5).status == "grounded"


def test_the_rule_is_asymmetric_and_the_tolerance_is_relative():
    assert gate_line("P", task(0.5), 10.0, tolerance=0.5).status == "grounded"  # muy por debajo: no se penaliza
    assert gate_line("P", task(7.5), 5.0, tolerance=0.5).status == "grounded"  # justo en el límite (+50 %)
    assert gate_line("P", task(7.6), 5.0, tolerance=0.5).status == "degraded"
    assert gate_line("P", task(7.6), 5.0, tolerance=1.0).status == "grounded"  # tolerancia mayor


def test_an_ungrounded_line_is_insufficient_and_a_missing_anchor_does_not_penalise():
    ungrounded = TaskItem.model_validate(line_task("SAP", chunk_ids=()))

    assert gate_line("P", ungrounded, None, tolerance=0.5).status == "insufficient"
    assert gate_line("P", task(99), None, tolerance=0.5).status == "grounded"


# --- Conductor con juez ----------------------------------------------------------------------------------------


async def test_the_judge_runs_once_for_the_whole_estimate():
    estimate = Estimate.model_validate(payload(line_task("A", 4, (1,)), line_task("B", 4, (2,)), line_task("C", chunk_ids=())))
    chunks = [make_chunk(1, estimated_hours=40), make_chunk(2, estimated_hours=40)]
    generator = ScriptedGenerator(judge_reply(True, False, True))

    report = await run_gate(estimate, chunks, generate=generator, tolerance=0.5)

    assert len(generator.calls) == 1 and report.judge_used is True
    assert [(v.task, v.status) for v in report.lines] == [("A", "grounded"), ("B", "degraded"), ("C", "insufficient")]
    assert "el juez no la respalda: no coincide" in report.lines[1].reason
    assert (report.totals.grounded, report.totals.degraded, report.totals.insufficient) == (1, 1, 1)


async def test_the_judge_only_sees_the_literal_evidence_of_grounded_lines():
    estimate = Estimate.model_validate(payload(line_task("A", 4, (1,)), line_task("C", chunk_ids=())))
    generator = ScriptedGenerator(judge_reply(True))

    await run_gate(estimate, [make_chunk(1)], generate=generator, tolerance=0.5)

    user = generator.user_messages()[0]
    assert "KYC onboarding. Estimated hours: 40" in user and 'task="A"' in user and 'task="C"' not in user


async def test_numeric_degradation_and_judge_verdict_combine():
    estimate = Estimate.model_validate(payload(line_task("A", 20, (1,))))

    report = await run_gate(
        estimate, [make_chunk(1, estimated_hours=40)], generate=ScriptedGenerator(judge_reply(False)), tolerance=0.5
    )

    assert report.lines[0].status == "degraded" and "desviación" in report.lines[0].reason and "juez" in report.lines[0].reason


async def test_without_the_judge_only_the_anchor_applies_and_no_llm_is_called():
    estimate = Estimate.model_validate(payload(line_task("A", 20, (1,))))
    generator = ScriptedGenerator()

    report = await run_gate(estimate, [make_chunk(1, estimated_hours=40)], generate=generator, tolerance=0.5, use_judge=False)

    assert generator.calls == [] and report.judge_used is False
    assert report.lines[0].status == "degraded" and report.lines[0].judge_supported is None


async def test_an_estimate_with_only_ungrounded_lines_does_not_call_the_judge():
    estimate = Estimate.model_validate(payload(line_task("A", chunk_ids=())))
    generator = ScriptedGenerator()

    report = await run_gate(estimate, [], generate=generator, tolerance=0.5)

    assert generator.calls == [] and report.totals.insufficient == 1


# --- Pipeline --------------------------------------------------------------------------------------------------


def over_estimate(days: float = 20) -> dict:
    return payload(line_task("KYC", days, (1,)), source_ids=(1,))


def pipeline_estimator(generator, **settings):
    chunks = [make_chunk(1, estimated_hours=40), make_chunk(2, 0.3)]
    return build_estimator(generator, FakeRetriever(chunks), **settings)


async def test_a_degraded_line_downgrades_a_high_confidence_estimate_to_low():
    generator = ScriptedGenerator(BRIEF, over_estimate(), judge_reply(True))

    estimate = await pipeline_estimator(generator, hallucination_gate_enabled=True).estimate_from_transcript(TRANSCRIPT)

    assert estimate.confidence == "low" and len(generator.calls) == 3


async def test_a_supported_estimate_keeps_its_confidence():
    generator = ScriptedGenerator(BRIEF, over_estimate(5), judge_reply(True))

    estimate = await pipeline_estimator(generator, hallucination_gate_enabled=True).estimate_from_transcript(TRANSCRIPT)

    assert estimate.confidence == "high"


async def test_the_judge_alone_can_degrade_a_line_within_the_anchor():
    generator = ScriptedGenerator(BRIEF, over_estimate(5), judge_reply(False))

    estimate = await pipeline_estimator(generator, hallucination_gate_enabled=True).estimate_from_transcript(TRANSCRIPT)

    assert estimate.confidence == "low"


async def test_a_medium_confidence_is_downgraded_too_but_low_stays_low():
    medium = ScriptedGenerator(BRIEF, {**over_estimate(), "confidence": "medium"}, judge_reply(True))
    low = ScriptedGenerator(BRIEF, {**over_estimate(), "confidence": "low"}, judge_reply(True))

    assert (await pipeline_estimator(medium, hallucination_gate_enabled=True).estimate_from_transcript(TRANSCRIPT)).confidence == "low"
    assert (await pipeline_estimator(low, hallucination_gate_enabled=True).estimate_from_transcript(TRANSCRIPT)).confidence == "low"


async def test_with_the_gate_disabled_nothing_extra_runs():
    generator = ScriptedGenerator(BRIEF, over_estimate())

    estimate = await pipeline_estimator(generator).estimate_from_transcript(TRANSCRIPT)

    assert estimate.confidence == "high" and len(generator.calls) == 2


async def test_a_failing_judge_degrades_the_gate_to_the_numeric_anchor():
    generator = ScriptedGenerator(BRIEF, over_estimate(), RuntimeError("judge down"), RuntimeError("judge down"))

    estimate = await pipeline_estimator(generator, hallucination_gate_enabled=True).estimate_from_transcript(TRANSCRIPT)

    assert estimate.confidence == "low"  # la sobreestimación numérica basta sin el juez


async def test_the_judge_model_is_configurable():
    generator = ScriptedGenerator(BRIEF, over_estimate(5), judge_reply(True))

    await pipeline_estimator(
        generator, hallucination_gate_enabled=True, hallucination_judge_model="gpt-4o"
    ).estimate_from_transcript(TRANSCRIPT)

    assert generator.calls[2]["model"] == "gpt-4o" and "model" not in generator.calls[0]


# --- Etapa verify ----------------------------------------------------------------------------------------------


def verify_body(estimate: dict, *chunks, **extra) -> dict:
    return {"estimate": estimate, "kept_chunks": [c.model_dump() for c in chunks], **extra}


def test_verify_with_the_judge_returns_the_per_line_report(monkeypatch):
    generator = ScriptedGenerator(judge_reply(True))
    client = api_client(monkeypatch, build_estimator(generator))

    response = client.post(VERIFY, json=verify_body(over_estimate(5), make_chunk(1, estimated_hours=40)), headers=HEADERS)

    body = response.json()
    assert response.status_code == 200 and body["judge_used"] is True and len(generator.calls) == 1
    assert body["totals"] == {"grounded": 1, "degraded": 0, "insufficient": 0}
    assert body["lines"][0]["anchor_days"] == 5 and body["lines"][0]["status"] == "grounded"


def test_verify_without_the_judge_applies_only_the_numeric_anchor_and_never_calls_the_llm(monkeypatch):
    generator = ScriptedGenerator()
    client = api_client(monkeypatch, build_estimator(generator))

    response = client.post(
        VERIFY, json=verify_body(over_estimate(20), make_chunk(1, estimated_hours=40), use_judge=False), headers=HEADERS
    )

    body = response.json()
    assert response.status_code == 200 and generator.calls == []
    assert body["judge_used"] is False and body["lines"][0]["status"] == "degraded"


def test_a_failing_verification_is_a_sanitized_502(monkeypatch):
    secret = "sk-provider-secret-detail"
    client = api_client(monkeypatch, build_estimator(ScriptedGenerator(RuntimeError(secret), RuntimeError(secret))))

    response = client.post(VERIFY, json=verify_body(over_estimate(5), make_chunk(1)), headers=HEADERS)

    assert response.status_code == 502 and secret not in response.text
    assert response.json() == {"detail": "No se pudo verificar la estimación."}


def test_verify_needs_the_estimate_key_and_a_valid_body(monkeypatch):
    client = api_client(monkeypatch)

    assert client.post(VERIFY, json=verify_body(over_estimate(), make_chunk(1))).status_code == 401
    assert client.post(VERIFY, json={"estimate": {}}, headers=HEADERS).status_code == 422


def test_verify_is_limited_to_15_per_minute(monkeypatch):
    client = api_client(monkeypatch, build_estimator(ScriptedGenerator()))
    body = verify_body(over_estimate(5), make_chunk(1, estimated_hours=40), use_judge=False)

    statuses = [client.post(VERIFY, json=body, headers=HEADERS).status_code for _ in range(16)]

    assert statuses[:15] == [200] * 15 and statuses[15] == 429


@pytest.mark.parametrize("tolerance,expected", [(0.5, "degraded"), (5.0, "grounded")])
def test_verify_uses_the_effective_numeric_tolerance(monkeypatch, tolerance, expected):
    client = api_client(monkeypatch, build_estimator(ScriptedGenerator(), hallucination_numeric_tolerance=tolerance))

    response = client.post(
        VERIFY, json=verify_body(over_estimate(20), make_chunk(1, estimated_hours=40), use_judge=False), headers=HEADERS
    )

    assert response.json()["lines"][0]["status"] == expected
