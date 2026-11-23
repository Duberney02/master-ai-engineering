"""Transformación de consulta (Sesión 10): elección de técnica por heurística, generación y degradación a `direct`."""

import pytest

from app.generation.rag.retrieval.query_transform import DECOMPOSE, DIRECT, EXPAND, choose_technique, transform_query
from tests._grounded import ScriptedGenerator

SHORT = "oauth refresh tokens"
EXPANDABLE = "How do we handle refresh token rotation for mobile clients"
MULTI_TOPIC = "Mobile banking app with OAuth2 authentication, PSD2 open banking compliance and a transaction ledger"


def subqueries(*pairs: tuple[str, str]) -> dict:
    return {"subqueries": [{"topic": topic, "query": query} for topic, query in pairs]}


@pytest.mark.parametrize(
    ("query", "technique"),
    [
        (SHORT, DIRECT),
        ("stripe connect", DIRECT),
        (EXPANDABLE, EXPAND),
        (MULTI_TOPIC, DECOMPOSE),  # conectores: comas y «and»
        ("Stripe payouts. SAP integration for invoices.", DECOMPOSE),  # dos frases
        (" ".join(["word"] * 30), DECOMPOSE),  # larga
    ],
)
def test_the_technique_follows_the_shape_of_the_query(query, technique):
    assert choose_technique(query) == technique


async def test_a_short_query_passes_through_untouched_without_calling_the_llm():
    generator = ScriptedGenerator()

    plan = await transform_query(SHORT, generate=generator)

    assert plan.technique == DIRECT and [(s.topic, s.query) for s in plan.subqueries] == [("original", SHORT)]
    assert generator.calls == []


async def test_expansion_generates_variants_of_the_same_intent():
    generator = ScriptedGenerator(subqueries(("rotation", "refresh token rotation mobile"), ("sessions", "mobile session renewal")))

    plan = await transform_query(EXPANDABLE, generate=generator, model="gpt-4o-mini")

    assert plan.technique == EXPAND and len(plan.subqueries) == 2
    call = generator.calls[0]
    assert call["model"] == "gpt-4o-mini" and "MISMA intención" in call["messages"][0]["content"]


async def test_decomposition_generates_one_subquery_per_topic():
    generator = ScriptedGenerator(
        subqueries(("auth", "OAuth2 authentication"), ("compliance", "PSD2 open banking"), ("ledger", "transaction ledger"))
    )

    plan = await transform_query(MULTI_TOPIC, generate=generator)

    assert plan.technique == DECOMPOSE
    assert [s.topic for s in plan.subqueries] == ["auth", "compliance", "ledger"]
    assert "UNA por tema" in generator.calls[0]["messages"][0]["content"]


async def test_the_prompt_carries_the_cap_and_the_schema_enforces_four_subqueries():
    generator = ScriptedGenerator(subqueries(*[(f"t{i}", f"q{i}") for i in range(6)]), subqueries(*[(f"t{i}", f"q{i}") for i in range(6)]))

    plan = await transform_query(MULTI_TOPIC, generate=generator, max_subqueries=4)

    # Más de 4 incumple el esquema (máx. 4): tras el reintento correctivo la transformación degrada a `direct`.
    assert plan.technique == DIRECT and len(plan.subqueries) == 1
    assert "4" in generator.calls[0]["messages"][0]["content"]


async def test_a_lower_configured_cap_truncates_the_subqueries():
    generator = ScriptedGenerator(subqueries(("a", "qa"), ("b", "qb"), ("c", "qc")))

    plan = await transform_query(MULTI_TOPIC, generate=generator, max_subqueries=2)

    assert plan.technique == DECOMPOSE and [s.topic for s in plan.subqueries] == ["a", "b"]


@pytest.mark.parametrize("failure", [RuntimeError("provider down"), "no es JSON", {"subqueries": []}])
async def test_an_llm_failure_degrades_to_a_single_direct_query(failure):
    generator = ScriptedGenerator(failure, failure)

    plan = await transform_query(MULTI_TOPIC, generate=generator)

    assert plan.technique == DIRECT
    assert [(s.topic, s.query) for s in plan.subqueries] == [("original", MULTI_TOPIC)]


async def test_a_disabled_transformation_never_calls_the_llm():
    generator = ScriptedGenerator()

    plan = await transform_query(MULTI_TOPIC, generate=generator, enabled=False)

    assert plan.technique == DIRECT and generator.calls == []
