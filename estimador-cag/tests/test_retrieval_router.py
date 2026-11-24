"""*Router* en cascada (Sesión 10): explícito → reglas → clasificador → respaldo, con un clasificador falso."""

import pytest

from app.generation.rag.retrieval.collections import ALL_COLLECTIONS, Collection
from app.generation.rag.retrieval.router import route
from tests._grounded import ScriptedGenerator


def classification(*targets: str, reason: str = "Porque sí.") -> dict:
    return {"targets": list(targets), "reason": reason}


async def test_explicit_collections_skip_the_classifier():
    generator = ScriptedGenerator()  # una llamada inesperada lanzaría AssertionError

    decision = await route("what is the weather", generate=generator, explicit=[Collection.TECHNICAL_DOC])

    assert (decision.level, decision.targets) == ("explicit", [Collection.TECHNICAL_DOC])
    assert generator.calls == []


async def test_explicit_wins_even_when_routing_is_disabled_and_is_deduplicated_and_capped():
    generator = ScriptedGenerator()

    decision = await route(
        "q",
        generate=generator,
        explicit=[Collection.BUDGET, Collection.BUDGET, Collection.TRANSCRIPT],
        enabled=False,
        max_targets=2,
    )

    assert (decision.level, decision.targets) == ("explicit", [Collection.BUDGET, Collection.TRANSCRIPT])


async def test_vocabulary_rules_route_without_calling_the_llm():
    generator = ScriptedGenerator()

    decision = await route("how much did the payments budget cost", generate=generator)

    assert (decision.level, decision.targets) == ("rules", [Collection.BUDGET])
    assert "budget" in decision.reason and generator.calls == []


async def test_rules_respect_the_target_cap():
    decision = await route("budget meeting documentation", generate=ScriptedGenerator(), max_targets=2)

    assert decision.level == "rules" and decision.targets == [Collection.BUDGET, Collection.TRANSCRIPT]


async def test_the_classifier_resolves_what_the_rules_cannot():
    generator = ScriptedGenerator(classification("transcript", "technical_doc", reason="Pregunta sobre decisiones y spec."))

    decision = await route("Why did we pick Kafka over RabbitMQ", generate=generator)

    assert decision.level == "classifier"
    assert decision.targets == [Collection.TRANSCRIPT, Collection.TECHNICAL_DOC]
    assert decision.reason == "Pregunta sobre decisiones y spec."
    assert len(generator.calls) == 1


async def test_the_classifier_uses_the_configured_model_and_a_closed_target_set():
    generator = ScriptedGenerator(classification("budget"))

    await route("Why did we pick Kafka over RabbitMQ", generate=generator, model="gpt-4o-mini")

    call = generator.calls[0]
    assert call["model"] == "gpt-4o-mini"
    system = call["messages"][0]["content"]
    assert all(name in system for name in ("budget", "transcript", "technical_doc"))


async def test_a_classifier_exception_degrades_to_the_fallback_over_all_collections():
    generator = ScriptedGenerator(RuntimeError("provider down: sk-secret"))

    decision = await route("Why did we pick Kafka over RabbitMQ", generate=generator)

    assert decision.level == "fallback" and decision.targets == list(ALL_COLLECTIONS)
    assert "sk-secret" not in decision.reason


@pytest.mark.parametrize(
    "bad_output",
    [
        "no es JSON",
        {"targets": [], "reason": "vacío"},
        {"targets": ["archive"], "reason": "colección inventada"},
        {"targets": ["budget"]},
    ],
)
async def test_an_invalid_classification_degrades_to_the_fallback(bad_output):
    # La generación estructurada reintenta una vez con corrección; ambas respuestas son inválidas.
    generator = ScriptedGenerator(bad_output, bad_output)

    decision = await route("Why did we pick Kafka over RabbitMQ", generate=generator)

    assert decision.level == "fallback" and decision.targets == list(ALL_COLLECTIONS)


async def test_disabled_routing_searches_everything_without_rules_or_classifier():
    generator = ScriptedGenerator()

    decision = await route("how much did the budget cost", generate=generator, enabled=False)

    assert decision.level == "fallback" and decision.targets == list(ALL_COLLECTIONS)
    assert generator.calls == []


async def test_the_classifier_targets_are_deduplicated_and_capped():
    generator = ScriptedGenerator(
        classification("budget", "budget", "transcript"), classification("budget", "transcript", "technical_doc")
    )

    deduplicated = await route("Why did we pick Kafka over RabbitMQ", generate=generator)
    capped = await route("Why did we pick Kafka over RabbitMQ", generate=generator, max_targets=2)

    assert deduplicated.targets == [Collection.BUDGET, Collection.TRANSCRIPT]
    assert capped.targets == [Collection.BUDGET, Collection.TRANSCRIPT]


async def test_more_than_three_targets_violate_the_closed_schema_and_degrade_to_the_fallback():
    bad = classification("budget", "budget", "transcript", "technical_doc")

    decision = await route("Why did we pick Kafka over RabbitMQ", generate=ScriptedGenerator(bad, bad))

    assert decision.level == "fallback"
