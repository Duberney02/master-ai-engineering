"""CLI `scripts/compare_chunkers.py`: filtros, estadísticas, top-k, coste, informe Markdown y dimensiones."""

import importlib.util
from pathlib import Path

import pytest

from tests._rag_fakes import FakeEmbedder

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "compare_chunkers.py"


@pytest.fixture
def cli(mocker):
    spec = importlib.util.spec_from_file_location("compare_chunkers", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    created: list[FakeEmbedder] = []

    def make_embedder(*, dimensions=None, **_):
        embedder = FakeEmbedder(dimensions=dimensions or 32)
        created.append(embedder)
        return embedder

    mocker.patch.object(module, "OpenAIEmbedder", make_embedder)
    module.created = created
    return module


def test_default_run_uses_free_strategies_and_needs_no_key(cli, capsys):
    code = cli.main(["--show-stats", "--limit-budgets", "3"])

    out = capsys.readouterr().out
    assert code == 0
    assert "| structural |" in out and "| hierarchical |" in out
    assert "propositional" not in out and "contextual_retrieval" not in out
    assert "huérfanos" in out and "obesos" in out


def test_strategy_filter(cli, capsys):
    cli.main(["--strategies", "recursive,fixed_size", "--show-stats"])

    out = capsys.readouterr().out
    assert "| recursive |" in out and "| fixed_size |" in out and "| structural |" not in out


def test_cost_columns_only_with_show_cost(cli, capsys):
    cli.main(["--strategies", "structural", "--show-stats"])
    assert "coste USD" not in capsys.readouterr().out

    cli.main(["--strategies", "structural", "--show-cost"])
    assert "coste USD" in capsys.readouterr().out


def test_top_k_for_selected_queries(cli, capsys):
    code = cli.main(["--strategies", "structural", "--queries", "1,2", "--show-top-k", "2"])

    out = capsys.readouterr().out
    assert code == 0
    assert out.count("### ") == 2 and "OAuth authentication for fintech mobile app" in out
    assert out.count("- **structural**") == 2


def test_extra_query_text_and_markdown_report(cli, capsys, tmp_path):
    report = tmp_path / "informe.md"

    code = cli.main(["--strategies", "structural", "--query", "custom question", "--show-top-k", "1", "--output", str(report)])

    text = report.read_text(encoding="utf-8")
    assert code == 0 and "### custom question" in text
    assert text.startswith("# Comparación de estrategias de chunking")


def test_dimensions_are_compared_with_the_same_chunking(cli, capsys):
    cli.main(["--strategies", "structural", "--queries", "1", "--show-top-k", "1", "--dimensions", "8,16"])

    out = capsys.readouterr().out
    assert "(dimensión 8)" in out and "(dimensión 16)" in out
    assert sorted(e.dimensions for e in cli.created if e.chunk_calls) == [8, 16]


def test_resolve_parents_names_the_parent_of_each_child(cli, capsys):
    cli.main(["--strategies", "hierarchical", "--queries", "1", "--show-top-k", "5", "--resolve-parents"])

    assert "padre de " in capsys.readouterr().out


def test_unknown_strategy_exits_with_two(cli, capsys):
    assert cli.main(["--strategies", "magic"]) == 2
    assert "magic" in capsys.readouterr().err


def test_paid_strategy_without_key_exits_with_two(cli, capsys, mocker):
    mocker.patch.object(cli, "get_settings", return_value=__import__("tests._fakes", fromlist=["x"]).openai_settings())

    assert cli.main(["--strategies", "contextual_retrieval"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
