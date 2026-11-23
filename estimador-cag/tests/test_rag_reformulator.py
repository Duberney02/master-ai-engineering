"""Reformulación: transcripción → brief estructurado + texto de búsqueda canónico (generador falso)."""

import pytest

from app.foundation.prompts.loader import UnknownPromptVersionError, render_rag_template
from app.generation.rag.errors import ReformulationError
from app.generation.rag.query_reformulator import compose_search_text, reformulate_query
from app.generation.rag.schemas import EstimationQuery
from tests._grounded import BRIEF, TRANSCRIPT, ScriptedGenerator


async def test_structured_brief_is_extracted_with_the_template():
    generator = ScriptedGenerator(BRIEF)

    query = await reformulate_query(TRANSCRIPT, generate=generator, model="gpt-4o-mini")

    assert query == EstimationQuery(**BRIEF)
    call = generator.calls[0]
    assert call["model"] == "gpt-4o-mini" and call["max_tokens"] == 1000
    system, user = call["messages"][0]["content"], call["messages"][1]["content"]
    assert "brief estructurado" in system and "## Contrato de salida (JSON)" in system
    assert f"<transcript>\n{TRANSCRIPT}\n</transcript>" in user


async def test_without_model_the_primary_model_is_used():
    generator = ScriptedGenerator(BRIEF)

    await reformulate_query(TRANSCRIPT, generate=generator)

    assert "model" not in generator.calls[0]


async def test_invalid_json_is_corrected_in_the_same_conversation():
    generator = ScriptedGenerator("no es json", BRIEF)

    query = await reformulate_query(TRANSCRIPT, generate=generator)

    assert query.sector == "finance" and len(generator.calls) == 2
    assert generator.calls[1]["messages"][-2]["role"] == "assistant"


async def test_falls_back_to_a_one_sentence_rewrite():
    generator = ScriptedGenerator("roto", "sigue roto", '  "B2B payments marketplace for German banks"  ')

    query = await reformulate_query(TRANSCRIPT, generate=generator)

    assert query == EstimationQuery(function="B2B payments marketplace for German banks")
    assert "UNA consulta de búsqueda" in generator.calls[-1]["messages"][0]["content"]


async def test_provider_failure_also_falls_back():
    generator = ScriptedGenerator(RuntimeError("provider down"), "payments marketplace")

    query = await reformulate_query(TRANSCRIPT, generate=generator)

    assert query.function == "payments marketplace"


@pytest.mark.parametrize("fallback", [RuntimeError("down"), "   "])
async def test_reformulation_error_when_the_fallback_fails(fallback):
    generator = ScriptedGenerator(RuntimeError("down"), fallback)

    with pytest.raises(ReformulationError):
        await reformulate_query(TRANSCRIPT, generate=generator)


def test_search_text_joins_the_grounded_fields():
    assert compose_search_text(EstimationQuery(**BRIEF)) == (
        "B2B payments marketplace with KYC onboarding with stripe, sap for finance in DE PSD2-compliant"
    )
    assert compose_search_text(EstimationQuery(function="Inventory app")) == "Inventory app"


def test_unknown_rag_prompts_are_rejected():
    with pytest.raises(UnknownPromptVersionError):
        render_rag_template("reformulation", "system", {}, version="v99")
    with pytest.raises(UnknownPromptVersionError):
        render_rag_template("../auxiliary", "system", {})
