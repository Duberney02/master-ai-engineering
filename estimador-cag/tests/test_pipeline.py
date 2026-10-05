"""`EstimationPipeline` con todas sus dependencias sustituidas: orden de etapas y cachés."""

import json

import pytest
from fastapi import HTTPException

from app.schemas import EstimationRequest, EstimationResult
from app.services.cache import CachedEstimation, make_result_key
from app.services.guardrails import GuardrailViolation
from app.services.llm_wrapper import Completion
from app.services.pipeline import EstimationPipeline
from tests._fakes import openai_settings

REQUEST = EstimationRequest(
    description="Aplicación móvil para que los vecinos de un municipio reporten incidencias.",
    project_type="mobile_app", detail_level="medium", output_format="phases_table",
)
RESULT = {
    "summary": "Proyecto mediano.", "confidence_pct": 70, "total_duration_weeks": 10,
    "total_cost_eur": 20000,
    "phases": [{"name": "Diseño", "duration_weeks": 2, "cost_eur": 4000},
               {"name": "Desarrollo", "duration_weeks": 8, "cost_eur": 16000}],
}
GOOD = json.dumps(RESULT)
ENTRY = CachedEstimation(result=EstimationResult.model_validate(RESULT), model="m", provider="openai")


class Recorder:
    def __init__(self):
        self.events: list[str] = []


class FakeGuardrails:
    def __init__(self, rec, violation=None):
        self.rec, self.violation = rec, violation

    async def check(self, request):
        self.rec.events.append("guardrails")
        if self.violation:
            raise GuardrailViolation(self.violation)


class FakeExact:
    def __init__(self, rec, stored=None):
        self.rec, self.stored, self.sets = rec, stored, []

    async def get(self, key):
        self.rec.events.append("exact_get")
        return self.stored

    async def set(self, key, value):
        self.rec.events.append("exact_set")
        self.sets.append((key, value))


class FakeSemantic:
    def __init__(self, rec, hit=None):
        self.rec, self.hit, self.stored = rec, hit, []

    async def lookup(self, request, prompt_version):
        self.rec.events.append("semantic_lookup")
        return self.hit

    async def store(self, request, prompt_version, entry):
        self.rec.events.append("semantic_store")
        self.stored.append((prompt_version, entry))


class FakeGenerate:
    def __init__(self, rec, *texts):
        self.rec, self.texts, self.calls = rec, list(texts), []

    async def __call__(self, system, user):
        self.rec.events.append("generate")
        self.calls.append((system, user))
        return Completion(text=self.texts.pop(0), model="gpt-4o-mini", provider="openai",
                          finish_reason="stop", input_tokens=100, output_tokens=50,
                          estimated_cost_usd=0.001, request_cost_usd=0.001)


def _pipeline(rec, *texts, exact=None, semantic=None, violation=None, **settings):
    exact = exact or FakeExact(rec)
    semantic = semantic or FakeSemantic(rec)
    generate = FakeGenerate(rec, *texts)
    pipeline = EstimationPipeline(
        openai_settings(**settings), guardrails=FakeGuardrails(rec, violation),
        exact_cache=exact, semantic_cache=semantic, generate=generate,
    )
    return pipeline, exact, semantic, generate


async def test_stages_run_in_order_and_result_is_stored_in_both_caches():
    rec = Recorder()
    pipeline, exact, semantic, _ = _pipeline(rec, GOOD)

    outcome = await pipeline.run(REQUEST, "v3")

    assert rec.events == [
        "guardrails", "exact_get", "semantic_lookup", "generate", "exact_set", "semantic_store"
    ]
    assert outcome.cached is False and outcome.prompt_version == "v3"
    assert outcome.result.total_cost_eur == 20000
    key, value = exact.sets[0]
    assert key == make_result_key(REQUEST, "v3", "openai", "gpt-4o-mini")
    assert CachedEstimation.model_validate(value).result == outcome.result
    assert semantic.stored[0][0] == "v3"


async def test_guardrail_violation_stops_before_any_cache_or_generation():
    rec = Recorder()
    pipeline, *_ = _pipeline(rec, GOOD, violation="pii_email")

    with pytest.raises(GuardrailViolation):
        await pipeline.run(REQUEST, "v3")

    assert rec.events == ["guardrails"]


async def test_unknown_version_is_422_before_guardrails():
    rec = Recorder()
    pipeline, *_ = _pipeline(rec, GOOD)

    with pytest.raises(HTTPException) as exc:
        await pipeline.run(REQUEST, "v9")

    assert exc.value.status_code == 422 and rec.events == []


async def test_exact_hit_skips_semantic_render_and_generation():
    rec = Recorder()
    pipeline, *_ = _pipeline(rec, GOOD, exact=FakeExact(rec, ENTRY.model_dump(mode="json")))

    outcome = await pipeline.run(REQUEST, "v3")

    assert rec.events == ["guardrails", "exact_get"]
    assert outcome.cached is True and outcome.result == ENTRY.result
    assert (outcome.model, outcome.input_tokens, outcome.request_cost_usd) == ("m", 0, 0.0)


async def test_semantic_hit_is_promoted_to_the_exact_cache():
    rec = Recorder()
    pipeline, exact, _, generate = _pipeline(rec, GOOD, semantic=FakeSemantic(rec, ENTRY))

    outcome = await pipeline.run(REQUEST, "v3")

    assert rec.events == ["guardrails", "exact_get", "semantic_lookup", "exact_set"]
    assert outcome.cached is True and generate.calls == []
    assert len(exact.sets) == 1


async def test_cached_result_that_breaks_business_rules_is_a_miss():
    rec = Recorder()
    broken = ENTRY.model_dump(mode="json")
    broken["result"]["total_cost_eur"] = 1
    pipeline, *_ = _pipeline(rec, GOOD, exact=FakeExact(rec, broken))

    outcome = await pipeline.run(REQUEST, "v3")

    assert outcome.cached is False and "generate" in rec.events


async def test_garbage_in_exact_cache_is_a_miss():
    rec = Recorder()
    pipeline, *_ = _pipeline(rec, GOOD, exact=FakeExact(rec, {"nope": 1}))

    assert (await pipeline.run(REQUEST, "v3")).cached is False


async def test_correction_attempt_includes_error_and_previous_answer_and_sums_usage():
    rec = Recorder()
    bad = json.dumps(RESULT | {"total_cost_eur": 25000})
    pipeline, _, _, generate = _pipeline(rec, bad, GOOD)

    outcome = await pipeline.run(REQUEST, "v3")

    assert outcome.attempts == 2 and rec.events.count("generate") == 2
    first_user, second_user = generate.calls[0][1], generate.calls[1][1]
    assert generate.calls[0][0] == generate.calls[1][0]  # mismo prompt de sistema
    assert second_user.startswith(first_user)
    assert "25000" in second_user and "Respuesta anterior" in second_user
    assert (outcome.input_tokens, outcome.output_tokens) == (200, 100)
    assert outcome.request_cost_usd == 0.002


async def test_invalid_responses_are_not_stored_and_exhaust_into_502():
    rec = Recorder()
    pipeline, exact, semantic, _ = _pipeline(rec, "x", "y", validation_max_attempts=2)

    with pytest.raises(HTTPException) as exc:
        await pipeline.run(REQUEST, "v3")

    assert exc.value.status_code == 502 and rec.events.count("generate") == 2
    assert exact.sets == [] and semantic.stored == []


async def test_single_attempt_setting_disables_correction():
    rec = Recorder()
    bad = json.dumps(RESULT | {"total_cost_eur": 25000})
    pipeline, *_ = _pipeline(rec, bad, GOOD, validation_max_attempts=1)

    with pytest.raises(HTTPException):
        await pipeline.run(REQUEST, "v3")


async def test_out_of_scope_result_is_normalized_before_storing():
    rec = Recorder()
    low = json.dumps(RESULT | {"confidence_pct": 10, "summary": "Out of scope: faltan datos."})
    pipeline, exact, _, _ = _pipeline(rec, low)

    outcome = await pipeline.run(REQUEST, "v3")

    assert outcome.result.out_of_scope and outcome.result.total_cost_eur == 0
    stored = CachedEstimation.model_validate(exact.sets[0][1])
    assert [p.name for p in stored.result.phases] == ["No estimable"]


async def test_input_checked_skips_guardrails():
    rec = Recorder()
    pipeline, *_ = _pipeline(rec, GOOD, violation="pii_email")

    outcome = await pipeline.run(REQUEST, "v3", input_checked=True)

    assert "guardrails" not in rec.events and outcome.cached is False
