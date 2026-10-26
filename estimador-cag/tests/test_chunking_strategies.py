"""Las ocho estrategias de chunking: interfaz común, forma de los chunks y coste reportado."""

import json

import pytest
import structlog

from app.generation.rag.chunking.base import Chunker, count_tokens
from app.generation.rag.chunking.registry import ALL_STRATEGIES, FREE_STRATEGIES, PAID_STRATEGIES
from app.generation.rag.chunking.strategies import (
    ContextualRetrievalChunker,
    FixedSizeChunker,
    HierarchicalChunker,
    PropositionalChunker,
    RecursiveChunker,
    SemanticChunker,
    SentenceWindowChunker,
)
from app.generation.rag.chunking.strategies.recursive import recursive_split
from app.generation.rag.chunking.structural import JSONStructuralChunker
from tests._fakes import openai_settings
from tests._rag_fakes import FakeAnthropicClient, FakeEmbedder, FakeOpenAIClient, make_budget


@pytest.fixture
def budgets():
    return [make_budget("B-1", ["First sentence about OAuth. Second about tokens. Third about limits.", "Short one."])]


async def test_structural_makes_one_chunk_per_component(budgets):
    chunks = await JSONStructuralChunker().chunk(budgets)

    assert [c.chunk_id for c in chunks] == ["B-1::C-1", "B-1::C-2"]
    assert chunks[0].metadata["component_id"] == "C-1"
    assert chunks[0].text.startswith("[Project: Mobile banking API]")
    assert chunks[0].token_count == count_tokens(chunks[0].text)


async def test_fixed_size_slides_a_window_with_overlap():
    long_text = " ".join(f"word{i}" for i in range(400))
    budget = make_budget("B-1", [long_text])

    chunks = await FixedSizeChunker(size=100, overlap=20).chunk([budget])

    assert len(chunks) > 3
    assert all(c.token_count <= 100 for c in chunks)
    assert [c.metadata["part"] for c in chunks] == list(range(len(chunks)))
    assert chunks[0].chunk_id == "B-1::C-1::p0"


def test_fixed_size_rejects_an_overlap_not_smaller_than_the_window():
    with pytest.raises(ValueError):
        FixedSizeChunker(size=10, overlap=10)


def test_recursive_split_prefers_coarse_separators_and_respects_size():
    text = "\n\n".join(f"Paragraph {i}. " + "word " * 40 for i in range(6))

    pieces = recursive_split(text, size=120, overlap=20)

    assert len(pieces) > 1
    assert all(count_tokens(p) <= 120 for p in pieces)
    assert "Paragraph 0" in pieces[0] and "Paragraph 5" in pieces[-1]


def test_recursive_split_falls_back_to_tokens_without_separators():
    pieces = recursive_split("x" * 3000, size=50, overlap=10)

    assert len(pieces) > 1 and all(count_tokens(p) <= 50 for p in pieces)


async def test_recursive_chunker_emits_budget_level_chunks(budgets):
    chunks = await RecursiveChunker(size=60, overlap=10).chunk(budgets)

    assert chunks and all(c.chunk_id.startswith("B-1::r") for c in chunks)
    assert "component_id" not in chunks[0].metadata


async def test_sentence_window_indexes_sentences_and_keeps_the_window_in_metadata(budgets):
    chunks = await SentenceWindowChunker(window_size=1).chunk(budgets)

    first = [c for c in chunks if c.chunk_id.startswith("B-1::C-1::")]
    assert [c.text for c in first] == ["First sentence about OAuth.", "Second about tokens.", "Third about limits."]
    assert first[0].metadata["window_text"] == "First sentence about OAuth. Second about tokens."
    assert first[1].metadata["window_text"].count(".") == 3


async def test_hierarchical_links_each_child_to_its_parent(budgets):
    chunks = await HierarchicalChunker().chunk(budgets)

    parent = next(c for c in chunks if c.metadata["level"] == "parent")
    children = [c for c in chunks if c.metadata["level"] == "child"]
    assert parent.chunk_id == "B-1::parent"
    assert len(children) == 2 and all(c.metadata["parent_chunk_id"] == parent.chunk_id for c in children)
    assert parent.token_count > max(c.token_count for c in children)


async def test_semantic_cuts_at_the_largest_embedding_jump():
    embedder = FakeEmbedder()
    budget = make_budget("B-1", ["alpha alpha alpha. alpha alpha beta. gamma gamma gamma. gamma gamma delta."])
    chunker = SemanticChunker(embedder, breakpoint_percentile=90, buffer_size=0)

    chunks = await chunker.chunk([budget])

    assert len(chunks) >= 2
    assert chunker.last_extra_api_calls == 1
    assert chunker.last_extra_cost_usd > 0
    assert len(embedder.text_calls) == 1


async def test_propositional_turns_each_proposition_into_a_chunk_and_reports_cost(budgets):
    client = FakeOpenAIClient(propositions=["OAuth issues tokens.", "Tokens expire."])
    chunker = PropositionalChunker(client, "gpt-4o-mini", openai_settings())

    chunks = await chunker.chunk(budgets)

    assert [c.text for c in chunks if c.chunk_id.startswith("B-1::C-1")] == ["OAuth issues tokens.", "Tokens expire."]
    assert chunker.last_extra_api_calls == 2
    # 2 llamadas × (1000 × 0,15 + 100 × 0,60) / 1e6
    assert chunker.last_extra_cost_usd == pytest.approx(2 * (1000 * 0.15 + 100 * 0.60) / 1_000_000)
    assert client.calls[0]["model"] == "gpt-4o-mini"


async def test_propositional_uses_the_configured_model(budgets):
    client = FakeOpenAIClient(propositions=["Fact."])

    await PropositionalChunker(client, "gpt-4o", openai_settings()).chunk(budgets)

    assert {call["model"] for call in client.calls} == {"gpt-4o"}


async def test_propositional_failure_keeps_the_whole_component_and_costs_nothing(budgets):
    client = FakeOpenAIClient(error=RuntimeError("boom sk-secret"))
    chunker = PropositionalChunker(client, "gpt-4o-mini", openai_settings())

    chunks = await chunker.chunk(budgets)

    assert len(chunks) == 2 and chunks[0].text.startswith("[Project:")
    assert chunker.last_extra_cost_usd == 0.0


async def test_contextual_prepends_context_and_caches_the_parent_document(budgets):
    client = FakeAnthropicClient()
    chunker = ContextualRetrievalChunker(client, "claude-sonnet-4-5", openai_settings())

    chunks = await chunker.chunk(budgets)

    assert chunks[0].text.startswith("Situates the component in the budget.\n\n[Project:")
    assert chunks[0].metadata["generated_context"] == "Situates the component in the budget."
    assert all(c["system"][0]["cache_control"] == {"type": "ephemeral"} for c in client.calls)
    assert chunker.last_extra_api_calls == 2
    # Primera llamada escribe caché (2000 × 3 × 1,25), la segunda la lee (2000 × 3 × 0,1).
    expected = (2 * (100 * 3.0 + 50 * 15.0) + 2000 * 3.0 * 1.25 + 2000 * 3.0 * 0.10) / 1_000_000
    assert chunker.last_extra_cost_usd == pytest.approx(expected)


async def test_contextual_failure_keeps_the_chunk_without_context(budgets):
    chunker = ContextualRetrievalChunker(
        FakeAnthropicClient(error=RuntimeError("x")), "claude-sonnet-4-5", openai_settings()
    )

    chunks = await chunker.chunk(budgets)

    assert chunks[0].text.startswith("[Project:") and chunks[0].metadata["generated_context"] == ""


async def test_every_strategy_emits_the_same_chunking_done_event(budgets):
    chunkers: list[Chunker] = [
        JSONStructuralChunker(),
        FixedSizeChunker(),
        RecursiveChunker(),
        SentenceWindowChunker(),
        HierarchicalChunker(),
        SemanticChunker(FakeEmbedder()),
        PropositionalChunker(FakeOpenAIClient(propositions=["A fact."]), "gpt-4o-mini", openai_settings()),
        ContextualRetrievalChunker(FakeAnthropicClient(), "claude-sonnet-4-5", openai_settings()),
    ]
    with structlog.testing.capture_logs() as logs:
        for chunker in chunkers:
            await chunker.chunk(budgets)

    events = [e for e in logs if e["event"] == "chunking_done"]
    assert [e["strategy"] for e in events] == [c.strategy_name for c in chunkers]
    expected_keys = {
        "event",
        "log_level",
        "strategy",
        "n_chunks",
        "n_input_documents",
        "extra_api_calls",
        "extra_cost_usd",
        "latency_ms",
    }
    assert all(set(e) == expected_keys for e in events)
    assert all(e["n_input_documents"] == 1 for e in events)


def test_registry_lists_free_and_paid_strategies_without_overlap():
    assert set(FREE_STRATEGIES).isdisjoint(PAID_STRATEGIES)
    assert ALL_STRATEGIES == (*FREE_STRATEGIES, *PAID_STRATEGIES)
    assert set(PAID_STRATEGIES) == {"semantic", "propositional", "contextual_retrieval"}


def test_the_chunking_log_fields_are_in_the_safe_list():
    from app.logging_config import SAFE_FIELDS

    assert {
        "strategy",
        "n_chunks",
        "n_input_documents",
        "extra_api_calls",
        "extra_cost_usd",
        "latency_ms",
    } <= SAFE_FIELDS


def test_test_queries_and_stress_corpus_are_valid():
    from pathlib import Path

    from app.generation.rag.schemas import Budget

    data = Path(__file__).resolve().parent.parent / "data"
    queries = json.loads((data / "test_queries.json").read_text(encoding="utf-8"))
    cases = [
        Budget.model_validate(b) for b in json.loads((data / "budgets_stress_cases.json").read_text(encoding="utf-8"))
    ]
    assert len(queries) >= 6 and all(isinstance(q, str) and q for q in queries)
    assert len(cases) == 3


async def test_stress_corpus_produces_obese_and_orphan_chunks():
    from pathlib import Path

    from app.generation.rag.analysis.comparison import OBESE_MIN_TOKENS, ORPHAN_MAX_TOKENS
    from app.generation.rag.schemas import Budget

    data = Path(__file__).resolve().parent.parent / "data"
    budgets = [
        Budget.model_validate(b)
        for b in json.loads((data / "budgets_stress_cases.json").read_text(encoding="utf-8"))
    ]

    structural = await JSONStructuralChunker().chunk(budgets)
    sentences = await SentenceWindowChunker().chunk(budgets)

    assert any(c.token_count > OBESE_MIN_TOKENS for c in structural)
    assert any(c.token_count < ORPHAN_MAX_TOKENS for c in sentences)
