"""*Decay* temporal (Sesión 10): funciones puras de peso y reordenación por recencia."""

from datetime import date, timedelta

import pytest

from app.generation.rag.retrieval.temporal import apply_temporal_decay, decay_weight
from app.generation.rag.schemas import RetrievedChunk

TODAY = date(2026, 6, 1)
HALF_LIFE = 900


def chunk(chunk_id: int, document_date: date | None) -> RetrievedChunk:
    return RetrievedChunk(id=chunk_id, content="x", chunk_type="budget_component", distance=0.1, document_date=document_date)


def test_a_chunk_exactly_one_half_life_old_keeps_half_its_score():
    assert decay_weight(HALF_LIFE, HALF_LIFE) == pytest.approx(0.5)
    assert decay_weight(2 * HALF_LIFE, HALF_LIFE) == pytest.approx(0.25)


def test_the_weight_decreases_monotonically_with_age():
    weights = [decay_weight(age, HALF_LIFE) for age in (0, 30, 365, 900, 3650)]

    assert weights == sorted(weights, reverse=True) and weights[0] == 1.0


@pytest.mark.parametrize("age", [0, -10, -9999])
def test_a_fresh_or_future_dated_chunk_is_not_penalized(age):
    assert decay_weight(age, HALF_LIFE) == 1.0


@pytest.mark.parametrize("half_life", [0, -5])
def test_a_non_positive_half_life_disables_the_decay(half_life):
    assert decay_weight(5000, half_life) == 1.0


def test_two_equally_relevant_finalists_are_untied_by_recency():
    recent = chunk(1, TODAY - timedelta(days=30))
    old = chunk(2, TODAY - timedelta(days=5 * 365))

    result = apply_temporal_decay([(old, 0.8), (recent, 0.8)], half_life_days=HALF_LIFE, reference_date=TODAY)

    assert [c.id for c, _ in result] == [1, 2]
    assert result[0][1] > result[1][1]


def test_a_much_more_relevant_old_chunk_can_still_win():
    recent = chunk(1, TODAY - timedelta(days=30))
    old = chunk(2, TODAY - timedelta(days=900))  # pierde la mitad

    result = apply_temporal_decay([(recent, 0.3), (old, 0.9)], half_life_days=HALF_LIFE, reference_date=TODAY)

    assert [c.id for c, _ in result] == [2, 1]  # 0.45 > 0.29


def test_chunks_without_a_date_keep_their_score():
    undated, dated = chunk(1, None), chunk(2, TODAY - timedelta(days=HALF_LIFE))

    result = dict((c.id, score) for c, score in apply_temporal_decay(
        [(undated, 0.6), (dated, 0.6)], half_life_days=HALF_LIFE, reference_date=TODAY
    ))

    assert result[1] == 0.6 and result[2] == pytest.approx(0.3)


def test_the_reference_date_is_injected_not_read_from_the_clock():
    old = chunk(1, date(2020, 1, 1))

    in_2021 = apply_temporal_decay([(old, 1.0)], half_life_days=HALF_LIFE, reference_date=date(2021, 1, 1))
    in_2026 = apply_temporal_decay([(old, 1.0)], half_life_days=HALF_LIFE, reference_date=date(2026, 1, 1))

    assert in_2021[0][1] > in_2026[0][1]


def test_an_empty_list_is_returned_empty():
    assert apply_temporal_decay([], half_life_days=HALF_LIFE, reference_date=TODAY) == []


def test_the_sort_is_stable_for_equal_final_scores():
    first, second = chunk(1, None), chunk(2, None)

    result = apply_temporal_decay([(first, 0.5), (second, 0.5)], half_life_days=HALF_LIFE, reference_date=TODAY)

    assert [c.id for c, _ in result] == [1, 2]
