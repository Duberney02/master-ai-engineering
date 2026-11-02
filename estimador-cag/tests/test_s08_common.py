"""Utilidades de los scripts de la Sesión 08: tabla de texto, recall, ★ de `ef_search`, literal vector y cronómetro."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import s08_common  # noqa: E402
from s08_common import (  # noqa: E402
    Stopwatch,
    format_table,
    latency_summary,
    recall_at_k,
    recommendation_labels,
    truncate,
    uses_index,
    vector_literal,
)

from tests._fakes import openai_settings  # noqa: E402


def test_recommendation_labels_marks_the_smallest_value_within_tolerance_of_the_best():
    recalls = [0.76, 0.9, 0.996, 1.0, 1.0]

    assert recommendation_labels(recalls) == ["", "", "★", "", ""]  # 0.996 ≥ 1.0 − 0.005


def test_recommendation_labels_prefers_the_best_when_nothing_is_close():
    assert recommendation_labels([0.5, 0.7, 0.9]) == ["", "", "★"]
    assert recommendation_labels([0.8]) == ["★"]
    assert recommendation_labels([]) == []


def test_recommendation_labels_tolerance_is_inclusive():
    assert recommendation_labels([0.995, 1.0]) == ["★", ""]
    assert recommendation_labels([0.99, 1.0]) == ["", "★"]


def test_recall_at_k_is_the_overlap_over_k():
    truth = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    assert recall_at_k([1, 2, 3, 4, 5], truth) == 1.0
    assert recall_at_k([5, 4, 3, 2, 1], truth) == 1.0  # el orden no cuenta
    assert recall_at_k([1, 2, 99, 98, 97], truth) == pytest.approx(0.4)
    assert recall_at_k([6, 7, 8, 9, 10], truth) == 0.0  # solo cuenta el top-5 real
    assert recall_at_k([1, 2, 3], [1, 2, 3, 4, 5], k=5) == pytest.approx(0.6)


def test_format_table_aligns_columns_and_right_aligns_numbers():
    table = format_table(["ef", "ms", "plan"], [[10, 2.5, "Index"], [200, 10.25, "Seq Scan"]])

    lines = table.splitlines()
    assert lines[0] == " ef     ms  plan    "
    assert lines[1] == "---  -----  --------"
    assert lines[2] == " 10    2.5  Index   "
    assert lines[3] == "200  10.25  Seq Scan"
    assert len({len(line) for line in lines}) == 1  # todas las líneas miden lo mismo


def test_format_table_without_rows_prints_only_the_header():
    assert format_table(["a", "bb"], []).splitlines() == ["a  bb", "-  --"]


def test_truncate_flattens_whitespace_and_adds_an_ellipsis():
    assert truncate("uno\n dos   tres", 20) == "uno dos tres"
    assert truncate("a" * 10, 5) == "aaaa…"
    assert len(truncate("a" * 100, 60)) == 60


def test_vector_literal_is_a_pgvector_literal():
    assert vector_literal([0.5, -1.0, 0.25]) == "[0.5,-1,0.25]"


def test_latency_summary_reports_mean_and_deviation():
    assert latency_summary([2.0, 4.0]) == "3.00 ± 1.41 ms"
    assert latency_summary([5.0]) == "5.00 ± 0.00 ms"
    assert latency_summary([]) == "n/d"


def test_stopwatch_measures_elapsed_milliseconds(mocker):
    mocker.patch.object(s08_common.time, "perf_counter", side_effect=[10.0, 10.25])

    with Stopwatch() as watch:
        pass

    assert watch.ms == pytest.approx(250.0)


def test_uses_index_looks_for_the_index_scan_node():
    plan = "Limit\n  ->  Index Scan using chunks_embedding_halfvec_idx on chunks"

    assert uses_index(plan, "chunks_embedding_halfvec_idx")
    assert not uses_index(plan, "chunks_embedding_idx")
    assert not uses_index("Seq Scan on chunks", "chunks_embedding_halfvec_idx")


def test_require_embedder_exits_with_a_clear_message_without_the_key(mocker):
    settings = openai_settings(database_url="postgresql+asyncpg://x/y").model_copy(update={"openai_api_key": None})
    mocker.patch.object(s08_common, "get_settings", return_value=settings)

    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        s08_common.require_embedder()


def test_require_embedder_exits_without_a_database(mocker):
    mocker.patch.object(s08_common, "get_settings", return_value=openai_settings())

    with pytest.raises(SystemExit, match="DATABASE_URL"):
        s08_common.require_embedder()
