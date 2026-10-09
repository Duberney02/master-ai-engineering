"""Orquestador Actor–Critic–Boss: decisiones, límite de iteraciones, feedback, único turno final y traza."""

import json

import pytest
from fastapi import HTTPException

from app.schemas import EstimationRequest
from app.services.acb import ActorCriticBoss
from app.services.critic import CriticService
from app.services.session_estimation import SessionEstimationService
from app.services.sessions import ConversationHistory, Session
from tests._acb import ScriptedGenerator, accept, estimation, needs_iteration, reject
from tests._fakes import openai_settings

TRANSCRIPT = "Reunión con el cliente: queremos un portal para gestionar pedidos y facturas."


def request() -> EstimationRequest:
    return EstimationRequest(
        description=TRANSCRIPT, project_type="web_saas", detail_level="medium", output_format="phases_table"
    )


def build(generate: ScriptedGenerator, max_iterations=3, **settings):
    cfg = openai_settings(moderation_enabled=False, boss_max_iterations=max_iterations, **settings)
    service = SessionEstimationService(cfg, generate=generate)
    return ActorCriticBoss(service, CriticService(cfg, generate=generate), max_iterations)


def session() -> Session:
    return Session(session_id="s-1", history=ConversationHistory(6))


async def run(generate, max_iterations=3, tier=None, sess=None, **settings):
    sess = sess or session()
    acb = build(generate, max_iterations, **settings)
    return sess, await acb.run(sess, request(), "v4", tier)


async def test_accepted_on_the_first_draft():
    generate = ScriptedGenerator()
    generate.critic = [accept(0.92)]

    sess, outcome = await run(generate)

    trace = outcome.trace
    assert trace.total_iterations == 1 and trace.final_decision == "accepted" and trace.reservations == []
    only = trace.iterations[0]
    assert (only.iteration, only.critic_verdict.value, only.critic_confidence, only.boss_decision.value) == (
        1,
        "accept",
        0.92,
        "accept",
    )
    assert only.defects.model_dump() == {"critical": 0, "major": 0, "minor": 0, "categories": []}
    assert len(generate.estimator_calls) == 1 and len(generate.critic_calls) == 1
    assert len(sess.history) == 1 and outcome.session_outcome.turn_count == 1


async def test_regenerates_with_the_feedback_and_accepts_the_second_draft():
    generate = ScriptedGenerator()
    generate.critic = [needs_iteration("Coste de desarrollo irreal.", "Subir el coste a 30000."), accept(0.85)]
    generate.estimations = [estimation("Primer borrador.", cost=20000), estimation("Segundo borrador.", cost=30000)]

    sess, outcome = await run(generate)

    assert outcome.session_outcome.outcome.result.summary == "Segundo borrador."
    assert outcome.session_outcome.outcome.result.total_cost_eur == 30000
    assert [i.boss_decision.value for i in outcome.trace.iterations] == ["regenerate", "accept"]
    assert outcome.trace.total_iterations == 2 and outcome.trace.final_decision == "accepted"
    # El segundo prompt incluye la respuesta previa del actor y los defectos con su corrección sugerida.
    second = generate.estimator_calls[1][0]
    assert json.loads(second[-2]["content"])["summary"] == "Primer borrador." and second[-2]["role"] == "assistant"
    assert second[-1]["role"] == "user"
    assert "Coste de desarrollo irreal." in second[-1]["content"] and "Subir el coste a 30000." in second[-1]["content"]
    assert "unrealistic_estimate" in second[-1]["content"] and "[major]" in second[-1]["content"]


async def test_only_the_final_result_is_stored_as_a_single_turn():
    generate = ScriptedGenerator()
    generate.critic = [needs_iteration(), needs_iteration(), accept()]
    generate.estimations = [estimation("Borrador 1."), estimation("Borrador 2."), estimation("Final.")]

    sess, outcome = await run(generate)

    assert len(sess.history) == 1 and len(generate.estimator_calls) == 3
    user, assistant = sess.history.turns[0]
    assert TRANSCRIPT in user and json.loads(assistant)["summary"] == "Final."
    stored = json.dumps(sess.history.turns)
    assert "Borrador 1." not in stored and "Borrador 2." not in stored and "revisor independiente" not in stored
    assert "Corrección sugerida" not in stored


async def test_iteration_limit_returns_the_last_draft_with_reservations():
    generate = ScriptedGenerator()
    generate.critic = [needs_iteration(f"Defecto {n}.") for n in range(1, 10)]
    generate.estimations = [estimation(f"Borrador {n}.") for n in range(1, 10)]

    sess, outcome = await run(generate, max_iterations=3)

    trace = outcome.trace
    assert len(generate.estimator_calls) == 3 and len(generate.critic_calls) == 3
    assert [i.boss_decision.value for i in trace.iterations] == ["regenerate", "regenerate", "return_with_reservations"]
    assert trace.total_iterations == 3 and trace.final_decision == "returned_with_reservations"
    assert outcome.session_outcome.outcome.result.summary == "Borrador 3."
    assert trace.reservations == ["[major] total_cost_eur: Defecto 3."]
    assert len(sess.history) == 1


async def test_max_iterations_is_configurable_down_to_one():
    generate = ScriptedGenerator()
    generate.critic = [needs_iteration()]

    _, outcome = await run(generate, max_iterations=1)

    assert len(generate.estimator_calls) == 1
    assert outcome.trace.iterations[0].boss_decision.value == "return_with_reservations"
    assert outcome.trace.final_decision == "returned_with_reservations"


async def test_default_max_iterations_comes_from_the_settings():
    generate = ScriptedGenerator()
    cfg = openai_settings(moderation_enabled=False, boss_max_iterations=2)
    service = SessionEstimationService(cfg, generate=generate)

    assert ActorCriticBoss(service, CriticService(cfg, generate=generate)).max_iterations == 2


async def test_reject_returns_the_draft_with_the_explanation_even_with_iterations_left():
    generate = ScriptedGenerator()
    generate.critic = [reject("La transcripción no describe un proyecto.")]

    _, outcome = await run(generate, max_iterations=3)

    assert len(generate.estimator_calls) == 1
    assert outcome.trace.final_decision == "returned_with_reservations"
    assert outcome.trace.iterations[0].critic_verdict.value == "reject"
    assert outcome.trace.reservations == ["La transcripción no describe un proyecto."]


async def test_defect_summary_counts_severities_and_categories():
    generate = ScriptedGenerator()
    payload = needs_iteration()
    payload["issues"] += [
        {
            "category": "math_error",
            "severity": "critical",
            "affected_field": "total_cost_eur",
            "description": "Suma mal.",
            "suggested_fix": "Sumar bien.",
        },
        {
            "category": "math_error",
            "severity": "minor",
            "affected_field": "phases[0]",
            "description": "Redondeo.",
            "suggested_fix": "Redondear.",
        },
    ]
    generate.critic = [payload]

    _, outcome = await run(generate, max_iterations=1)

    defects = outcome.trace.iterations[0].defects
    assert (defects.critical, defects.major, defects.minor) == (1, 1, 1)
    assert defects.categories == ["unrealistic_estimate", "math_error"]


async def test_critic_failure_returns_the_draft_with_reservations_instead_of_failing():
    generate = ScriptedGenerator()
    generate.critic = ["no es json", "tampoco"]

    sess, outcome = await run(generate)

    only = outcome.trace.iterations[0]
    assert only.critic_error and only.critic_verdict is None and only.critic_confidence is None
    assert only.boss_decision.value == "return_with_reservations"
    assert outcome.trace.final_decision == "returned_with_reservations" and outcome.trace.reservations
    assert len(sess.history) == 1


async def test_provider_failure_in_the_critic_is_handled_too():
    generate = ScriptedGenerator()
    generate.critic = [HTTPException(502, "boom")]

    _, outcome = await run(generate)

    assert outcome.trace.iterations[0].critic_error


async def test_actor_failure_propagates_and_leaves_the_session_untouched():
    generate = ScriptedGenerator()
    broken = estimation() | {"total_cost_eur": 1}
    generate.estimations = [broken, broken, broken]
    sess = session()

    with pytest.raises(HTTPException) as error:
        await run(generate, sess=sess)

    assert error.value.status_code == 502
    assert len(sess.history) == 0 and sess.metadata.is_empty() and sess.audience is None


async def test_actor_failure_after_a_regeneration_request_leaves_the_session_untouched():
    generate = ScriptedGenerator()
    broken = estimation() | {"total_cost_eur": 1}
    generate.critic = [needs_iteration()]
    generate.estimations = [estimation(), broken, broken, broken]
    sess = session()

    with pytest.raises(HTTPException):
        await run(generate, sess=sess)

    assert len(sess.history) == 0 and sess.audience is None


async def test_tier_is_passed_to_the_prompt_and_the_critic_and_recorded_in_the_session():
    from app.services.audience import Audience

    generate = ScriptedGenerator()

    sess, outcome = await run(generate, tier=Audience.EXECUTIVE)

    assert "la leerá la dirección" in generate.estimator_calls[0][0][0]["content"]
    assert "Audiencia: executive" in generate.critic_calls[0][0][1]["content"]
    assert (sess.audience, sess.audience_rule) == ("executive", "explicit")
    assert outcome.session_outcome.audience_rule == "explicit"


async def test_metrics_add_up_every_actor_and_critic_call():
    generate = ScriptedGenerator()
    generate.critic = [needs_iteration(), accept()]

    _, outcome = await run(generate)

    metrics = outcome.session_outcome.outcome
    calls = len(generate.calls)  # 2 borradores + 2 revisiones + metadatos
    assert calls == 5
    assert metrics.input_tokens == 100 * calls and metrics.output_tokens == 50 * calls
    assert metrics.estimated_cost_usd == pytest.approx(0.001 * calls)


async def test_sessions_with_guardrail_violations_never_reach_the_llm():
    from app.services.guardrails import GuardrailViolation

    generate = ScriptedGenerator()
    acb = build(generate)
    bad = EstimationRequest(
        description="Mi correo es persona@example.com y quiero una web para vender zapatos.",
        project_type="web_saas",
        detail_level="medium",
        output_format="phases_table",
    )

    with pytest.raises(GuardrailViolation):
        await acb.run(session(), bad, "v4")

    assert generate.calls == []
