"""Aumentación del contexto (Sesión 11): compresión extractiva y reordenación de bordes, conmutables."""

from app.foundation.llm.runtime_config import RetrievalToggles
from app.generation.rag.quality.augmentation import augment_chunks, compress_chunk, compress_chunks, reorder_edges
from tests._fakes import openai_settings
from tests._grounded import (
    BRIEF,
    ESTIMATE_KEY,
    TRANSCRIPT,
    FakeRetriever,
    ScriptedGenerator,
    api_client,
    build_estimator,
    estimate_payload,
    make_chunk,
)

HEADERS = {"X-API-Key": ESTIMATE_KEY}
VERBOSE = "Project overview with plenty of filler words.\nComponent KYC onboarding. Estimated hours: 40\nMore filler text here.\nSee BUD-77 for the precedent."


def ids(chunks) -> list[int]:
    return [chunk.id for chunk in chunks]


def toggles(**kw) -> RetrievalToggles:
    base = RetrievalToggles.from_settings(openai_settings(augmentation_enabled=True))
    from dataclasses import replace

    return replace(base, **kw)


# --- Compresión ------------------------------------------------------------------------------------------------


def test_compression_keeps_only_lines_with_figures_or_identifiers():
    compressed = compress_chunk(make_chunk(1, content=VERBOSE))

    assert compressed.content == "Component KYC onboarding. Estimated hours: 40\nSee BUD-77 for the precedent."
    assert "filler" not in compressed.content


def test_compression_preserves_ids_and_metadata():
    chunks = [make_chunk(i, content=VERBOSE, document_id=500 + i, budget_id=f"B{i}") for i in (3, 1, 2)]

    compressed = compress_chunks(chunks)

    assert ids(compressed) == ids(chunks) == [3, 1, 2]
    assert [(c.document_id, c.budget_id, c.sector, c.distance) for c in compressed] == [
        (c.document_id, c.budget_id, c.sector, c.distance) for c in chunks
    ]


def test_a_chunk_without_figures_is_left_intact_rather_than_emptied():
    chunk = make_chunk(1, content="Only prose here.\nNothing quantitative at all.")

    assert compress_chunk(chunk) == chunk


# --- Reordenación de bordes ------------------------------------------------------------------------------------


def test_the_two_most_relevant_chunks_end_up_at_the_extremes():
    ranked = [make_chunk(i, distance=i / 10) for i in range(1, 6)]  # 1 es el más relevante

    reordered = reorder_edges(ranked)

    assert ids(reordered) == [1, 3, 5, 4, 2]
    assert reordered[0].id == 1 and reordered[-1].id == 2  # los dos mejores, en los bordes
    assert reordered[len(reordered) // 2].id == 5  # el peor, en el centro


def test_reordering_handles_short_lists():
    assert reorder_edges([]) == []
    assert ids(reorder_edges([make_chunk(1)])) == [1]
    assert ids(reorder_edges([make_chunk(1), make_chunk(2)])) == [1, 2]


def test_augment_applies_each_step_independently():
    chunks = [make_chunk(i, content=VERBOSE) for i in range(1, 5)]

    only_reorder = augment_chunks(chunks, compress=False, reorder=True)
    only_compress = augment_chunks(chunks, compress=True, reorder=False)

    assert ids(only_reorder) == [1, 3, 4, 2] and only_reorder[0].content == VERBOSE
    assert ids(only_compress) == [1, 2, 3, 4] and "filler" not in only_compress[0].content
    assert augment_chunks(chunks, compress=False, reorder=False) == chunks


# --- Integración en `assemble` ---------------------------------------------------------------------------------


def test_assemble_is_unchanged_without_augmentation():
    estimator = build_estimator()
    chunks = [make_chunk(i, content=VERBOSE) for i in (1, 2, 3)]

    result = estimator.assemble(chunks, toggles=toggles(augmentation_enabled=False))

    assert ids(result.kept_chunks) == [1, 2, 3] and "filler" in result.context_block


def test_assemble_augments_after_truncation_and_before_building_the_block():
    estimator = build_estimator()
    chunks = [make_chunk(i, content=VERBOSE) for i in (1, 2, 3, 4)]

    result = estimator.assemble(chunks, toggles=toggles())

    assert ids(result.kept_chunks) == [1, 3, 4, 2]
    assert "filler" not in result.context_block
    order = [int(part.split('"')[0]) for part in result.context_block.split('<source id="')[1:]]
    assert order == [1, 3, 4, 2] and result.dropped_count == 0
    assert result.token_count < estimator.assemble(chunks, toggles=toggles(augmentation_enabled=False)).token_count


def test_the_sub_toggles_apply_only_with_the_master_switch_on():
    estimator = build_estimator()
    chunks = [make_chunk(i, content=VERBOSE) for i in (1, 2, 3)]

    result = estimator.assemble(chunks, toggles=toggles(augmentation_enabled=False, augmentation_compress=True))

    assert "filler" in result.context_block
    reorder_only = estimator.assemble(chunks, toggles=toggles(augmentation_compress=False))
    assert "filler" in reorder_only.context_block and ids(reorder_only.kept_chunks) == [1, 3, 2]


def test_dropped_count_counts_the_truncation_not_the_augmentation():
    estimator = build_estimator()
    chunks = [make_chunk(i, content="word " * 400) for i in range(1, 6)]

    result = estimator.assemble(chunks, max_context_tokens=1000, toggles=toggles())

    assert result.dropped_count == len(chunks) - len(result.kept_chunks) > 0


async def test_the_pipeline_sends_the_augmented_context_to_the_generator():
    chunks = [make_chunk(i, content=VERBOSE) for i in (1, 2, 3)]
    generator = ScriptedGenerator(BRIEF, estimate_payload(source_ids=(1,)))
    estimator = build_estimator(generator, FakeRetriever(chunks), augmentation_enabled=True)

    await estimator.estimate_from_transcript(TRANSCRIPT)

    user = generator.user_messages()[1]
    assert "filler" not in user and "Estimated hours: 40" in user
    assert user.index('<source id="1"') < user.index('<source id="3"') < user.index('<source id="2"')


def test_the_assemble_stage_honours_the_effective_toggles(monkeypatch):
    chunks = [make_chunk(i, content=VERBOSE) for i in (1, 2, 3)]
    client = api_client(monkeypatch, build_estimator(augmentation_enabled=True))

    response = client.post(
        "/v1/estimate/stages/assemble", json={"chunks": [c.model_dump() for c in chunks]}, headers=HEADERS
    )

    body = response.json()
    assert response.status_code == 200 and "filler" not in body["context_block"]
    assert [c["id"] for c in body["kept_chunks"]] == [1, 3, 2]
