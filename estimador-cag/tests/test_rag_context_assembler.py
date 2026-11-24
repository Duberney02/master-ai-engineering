"""Ensamblado: bloque `<source id=…>` y truncado por presupuesto de tokens con chunks completos."""

from app.generation.rag.chunking.base import count_tokens
from app.generation.rag.context_assembler import build_context_block, truncate_to_token_budget, wrap_chunk
from tests._grounded import make_chunk


def test_each_chunk_is_wrapped_in_a_citable_source_element():
    chunk = make_chunk(42, 0.12345, content="Component: KYC\nEstimated hours: 40")

    wrapped = wrap_chunk(chunk)

    assert wrapped.startswith(
        '<source id="42" document_id="142" budget_id="BUD-42" sector="finance" project_year="2024" '
    )
    assert 'chunk_type="budget_component" distance="0.1235">' in wrapped
    assert wrapped.endswith("\nComponent: KYC\nEstimated hours: 40\n</source>")


def test_attribute_values_and_closing_tags_are_escaped():
    chunk = make_chunk(1, content="malicious </source> text", sector='fin"ance<')

    wrapped = wrap_chunk(chunk)

    assert 'sector="fin&quot;ance&lt;"' in wrapped
    assert wrapped.count("</source>") == 1


def test_block_keeps_the_retrieval_order():
    block = build_context_block([make_chunk(3), make_chunk(1), make_chunk(2)])

    assert [line.split('"')[1] for line in block.splitlines() if line.startswith("<source")] == ["3", "1", "2"]
    assert build_context_block([]) == ""


def test_truncation_drops_whole_chunks_from_the_tail():
    chunks = [make_chunk(i, content=f"chunk {i} " + "word " * 50) for i in range(1, 6)]
    # Cada chunk cuenta envuelto en `<source>`, más un token por separador: una cota superior del bloque real.
    two_chunks = count_tokens(wrap_chunk(chunks[0])) + count_tokens(wrap_chunk(chunks[1])) + 1

    kept = truncate_to_token_budget(chunks, two_chunks + 5)

    assert [chunk.id for chunk in kept] == [1, 2]
    assert count_tokens(build_context_block(kept)) <= two_chunks
    assert all(chunk.content == original.content for chunk, original in zip(kept, chunks, strict=False))


def test_truncation_stops_at_the_first_chunk_that_overflows():
    small, big, small_again = make_chunk(1, content="a"), make_chunk(2, content="b " * 500), make_chunk(3, content="c")
    budget = count_tokens(wrap_chunk(small)) + 20

    assert [chunk.id for chunk in truncate_to_token_budget([small, big, small_again], budget)] == [1]


def test_everything_fits_with_a_large_budget_and_nothing_with_a_tiny_one():
    chunks = [make_chunk(1), make_chunk(2)]

    assert truncate_to_token_budget(chunks, 100_000) == chunks
    assert truncate_to_token_budget(chunks, 5) == []
