"""Orquestador de la estimación fundamentada: un test por escenario del spec `grounded-estimation`."""

import pytest
from structlog.testing import capture_logs

from app.generation.rag.errors import GenerationError, MalformedEstimateError, ReformulationError, RetrievalError
from app.generation.rag.estimator import SOFT_FAIL_EXPLANATION
from app.generation.rag.idempotency import IdempotencyStore
from app.generation.rag.retriever import RetrievalFilters
from tests._grounded import (
    BRIEF,
    TRANSCRIPT,
    FakeRetriever,
    ScriptedGenerator,
    build_estimator,
    estimate_payload,
    failing_retriever,
    incoherent_insufficient,
    make_chunk,
)


async def test_grounded_estimate_runs_every_stage_in_order():
    generator = ScriptedGenerator(BRIEF, estimate_payload(source_ids=(1, 2)))
    retriever = FakeRetriever([make_chunk(1), make_chunk(2, 0.3)])

    with capture_logs() as logs:
        estimate = await build_estimator(generator, retriever, generation_model="gpt-4o").estimate_from_transcript(
            TRANSCRIPT
        )

    assert estimate.confidence == "high" and estimate.total_engineer_days == 12
    assert estimate.modules[0].tasks and estimate.assumptions and estimate.reasoning
    assert {source.source_id for source in estimate.sources} <= {1, 2}
    # Recuperación con el texto canónico, los ajustes y el filtro de sector (sector conocido del corpus).
    search = retriever.calls[0]
    assert search["query_text"].startswith("B2B payments marketplace") and "for finance" in search["query_text"]
    assert (search["top_k"], search["distance_threshold"]) == (10, 0.6)
    assert search["filters"] == RetrievalFilters(sectors=["finance"])
    # Generación con el bloque de fuentes y el modelo configurado.
    generation = generator.calls[1]
    assert generation["model"] == "gpt-4o"
    user = generation["messages"][-1]["content"]
    assert '<source id="1"' in user and '<source id="2"' in user and "Function: B2B payments marketplace" in user
    assert "Solo puedes citar ids" in generation["messages"][0]["content"]
    stages = [(log["event"], log["stage"]) for log in logs if log["event"].startswith("rag_stage_")]
    assert [stage for event, stage in stages if event == "rag_stage_completed"] == [
        "reformulation",
        "retrieval",
        "augmentation",
        "generation",
    ]


async def test_unknown_sector_does_not_filter_retrieval():
    retriever = FakeRetriever()
    generator = ScriptedGenerator({**BRIEF, "sector": "fintech"}, estimate_payload())

    await build_estimator(generator, retriever).estimate_from_transcript(TRANSCRIPT)

    assert retriever.calls[0]["filters"] == RetrievalFilters(sectors=None)


async def test_soft_fail_returns_insufficient_without_calling_the_generator():
    generator = ScriptedGenerator(BRIEF)  # solo la reformulación

    estimate = await build_estimator(generator, FakeRetriever([])).estimate_from_transcript(TRANSCRIPT)

    assert estimate.confidence == "insufficient" and estimate.modules == []
    assert estimate.total_engineer_days is None and estimate.duration_weeks is None
    assert estimate.insufficient_context_explanation == SOFT_FAIL_EXPLANATION
    assert len(generator.calls) == 1


async def test_generation_failure_is_a_generation_error():
    generator = ScriptedGenerator(BRIEF, RuntimeError("provider down"))

    with pytest.raises(GenerationError):
        await build_estimator(generator).estimate_from_transcript(TRANSCRIPT)


async def test_invalid_generation_output_after_correction_is_a_generation_error():
    generator = ScriptedGenerator(BRIEF, "no es json", '{"confidence": "high"}')

    with pytest.raises(GenerationError):
        await build_estimator(generator).estimate_from_transcript(TRANSCRIPT)


async def test_reformulation_and_retrieval_failures_propagate_as_rag_errors():
    with pytest.raises(ReformulationError):
        await build_estimator(ScriptedGenerator(RuntimeError(), RuntimeError())).estimate_from_transcript(TRANSCRIPT)
    with pytest.raises(RetrievalError):
        await build_estimator(ScriptedGenerator(BRIEF), failing_retriever()).estimate_from_transcript(TRANSCRIPT)


async def test_repaired_citation_keeps_the_generated_confidence():
    generator = ScriptedGenerator(BRIEF, estimate_payload(source_ids=(1, 999)), estimate_payload(source_ids=(1,)))

    estimate = await build_estimator(generator).estimate_from_transcript(TRANSCRIPT)

    assert estimate.confidence == "high"
    assert 999 not in {source.source_id for source in estimate.sources}
    retry = generator.user_messages()[2]
    assert "<correction>" in retry and "[999]" in retry


async def test_unrepaired_citation_downgrades_to_low():
    generator = ScriptedGenerator(BRIEF, estimate_payload(source_ids=(999,)), estimate_payload(source_ids=(998,)))

    estimate = await build_estimator(generator).estimate_from_transcript(TRANSCRIPT)

    assert estimate.confidence == "low" and len(generator.calls) == 3


async def test_incoherent_insufficient_is_repaired_once():
    repaired = estimate_payload(
        source_ids=(),
        confidence="insufficient",
        total_engineer_days=None,
        duration_weeks=None,
        modules=[],
        insufficient_context_explanation="Faltan precedentes de pagos.",
    )
    generator = ScriptedGenerator(BRIEF, incoherent_insufficient(), repaired)

    estimate = await build_estimator(generator).estimate_from_transcript(TRANSCRIPT)

    assert estimate.confidence == "insufficient" and estimate.modules == []
    assert "insufficient_context_explanation" in generator.user_messages()[2]


async def test_irreparable_incoherence_is_a_malformed_estimate():
    generator = ScriptedGenerator(BRIEF, incoherent_insufficient(), incoherent_insufficient())

    with pytest.raises(MalformedEstimateError):
        await build_estimator(generator).estimate_from_transcript(TRANSCRIPT)


async def test_context_is_truncated_to_the_token_budget_with_whole_chunks():
    chunks = [make_chunk(i, content=f"chunk {i} " + "token " * 300) for i in range(1, 6)]
    generator = ScriptedGenerator(BRIEF, estimate_payload(source_ids=(1,)))

    await build_estimator(generator, FakeRetriever(chunks), max_context_tokens=700).estimate_from_transcript(
        TRANSCRIPT
    )

    user = generator.user_messages()[1]
    assert '<source id="1"' in user and '<source id="2"' in user and '<source id="3"' not in user


async def test_idempotency_returns_the_stored_estimate_without_calling_the_llm():
    generator = ScriptedGenerator(BRIEF, estimate_payload())
    estimator = build_estimator(generator, store=IdempotencyStore(ttl=60))

    first = await estimator.estimate_from_transcript(TRANSCRIPT, idempotency_key="req-1")
    with capture_logs() as logs:
        second = await estimator.estimate_from_transcript(TRANSCRIPT, idempotency_key="req-1")

    assert first == second and len(generator.calls) == 2
    assert any(log["event"] == "idempotency_hit" for log in logs)


async def test_insufficient_estimates_are_also_stored():
    generator = ScriptedGenerator(BRIEF)
    estimator = build_estimator(generator, FakeRetriever([]))

    await estimator.estimate_from_transcript(TRANSCRIPT, idempotency_key="empty")
    again = await estimator.estimate_from_transcript(TRANSCRIPT, idempotency_key="empty")

    assert again.confidence == "insufficient" and len(generator.calls) == 1


async def test_without_key_nothing_is_stored():
    store = IdempotencyStore(ttl=60)
    generator = ScriptedGenerator(BRIEF, estimate_payload(), BRIEF, estimate_payload())

    estimator = build_estimator(generator, store=store)
    await estimator.estimate_from_transcript(TRANSCRIPT)
    await estimator.estimate_from_transcript(TRANSCRIPT)

    assert len(generator.calls) == 4
