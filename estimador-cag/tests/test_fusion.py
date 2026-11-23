"""Fusión de rankings (Sesión 10): RRF (consenso por posición) y *round-robin* (cobertura por tema)."""

import pytest

from app.generation.rag.retrieval.fusion import reciprocal_rank_fusion, round_robin_merge


def test_rrf_scores_each_ranking_with_one_over_k_plus_position():
    fused = dict(reciprocal_rank_fusion([[10, 20], [20, 30]], k=60))

    assert fused[10] == pytest.approx(1 / 60)
    assert fused[20] == pytest.approx(1 / 61 + 1 / 60)  # aparece en ambas ramas
    assert fused[30] == pytest.approx(1 / 61)


def test_a_candidate_in_both_branches_beats_one_that_wins_a_single_branch():
    fused = reciprocal_rank_fusion([[1, 2, 3], [9, 3, 8]], k=60)

    assert [chunk_id for chunk_id, _ in fused][0] == 3  # 3.º y 2.º puesto supera a un 1.º puesto aislado


def test_a_candidate_only_in_the_lexical_branch_is_included():
    fused = reciprocal_rank_fusion([[1, 2], [99]], k=60)

    assert 99 in dict(fused)


def test_a_smaller_k_lets_a_single_first_place_dominate():
    rankings = [[1, 2, 3], [9, 3, 8]]

    assert reciprocal_rank_fusion(rankings, k=1)[0][0] == 1  # con k=1 un 1.º puesto aislado (1/1) gana al consenso
    assert reciprocal_rank_fusion(rankings, k=60)[0][0] == 3  # con k=60 gana el candidato presente en ambas ramas


def test_ties_break_by_ascending_id_and_the_output_is_deterministic():
    fused = reciprocal_rank_fusion([[5], [3]], k=60)

    assert [chunk_id for chunk_id, _ in fused] == [3, 5]


def test_an_empty_branch_adds_nothing_and_duplicates_count_once():
    assert reciprocal_rank_fusion([[], []], k=60) == []
    fused = dict(reciprocal_rank_fusion([[7, 7, 7]], k=60))
    assert fused == {7: pytest.approx(1 / 60)}


@pytest.mark.parametrize("k", [0, -5])
def test_a_non_positive_k_is_rejected(k):
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([[1]], k=k)


def test_round_robin_gives_every_list_a_slot_before_any_second_place():
    merged = round_robin_merge([["a1", "a2", "a3"], ["b1", "b2"], ["c1"]])

    assert merged == ["a1", "b1", "c1", "a2", "b2", "a3"]


def test_round_robin_drops_duplicates_by_key_keeping_the_first():
    merged = round_robin_merge([[("budget", 1), ("budget", 2)], [("transcript", 1), ("budget", 1)]], key=lambda item: item)

    assert merged == [("budget", 1), ("transcript", 1), ("budget", 2)]


def test_round_robin_keys_can_separate_equal_ids_across_collections():
    class Chunk:
        def __init__(self, collection, id_):
            self.collection, self.id = collection, id_

    first, second = Chunk("budget", 1), Chunk("transcript", 1)
    merged = round_robin_merge([[first], [second]], key=lambda chunk: (chunk.collection, chunk.id))

    assert merged == [first, second]
