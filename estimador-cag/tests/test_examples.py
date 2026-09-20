import json
import re

import pytest

from app.context.examples import (
    ESTIMATION_EXAMPLES,
    ESTIMATION_EXAMPLES_CATALOG,
    MAX_EXAMPLES,
    EstimationExample,
    format_examples,
    select_examples,
)


def test_has_at_least_two_examples():
    assert len(ESTIMATION_EXAMPLES) >= 2


def test_each_example_has_required_keys():
    for i, ex in enumerate(ESTIMATION_EXAMPLES):
        assert "meeting_summary" in ex, f"Example {i} missing meeting_summary"
        assert "estimation" in ex, f"Example {i} missing estimation"


def test_examples_have_substantive_content():
    for i, ex in enumerate(ESTIMATION_EXAMPLES):
        assert len(ex["meeting_summary"]) > 80, f"Example {i} meeting_summary too short"
        assert len(ex["estimation"]) > 200, f"Example {i} estimation too short"
        assert "##" in ex["estimation"], f"Example {i} estimation missing markdown headers"
        text = ex["estimation"].lower()
        assert "hora" in text or "hour" in text, f"Example {i} estimation missing hour references"


# --- catálogo ampliado y variado -------------------------------------------


def test_catalog_has_five_varied_examples():
    assert MAX_EXAMPLES == len(ESTIMATION_EXAMPLES_CATALOG) == 5
    assert len({ex.title for ex in ESTIMATION_EXAMPLES_CATALOG}) == MAX_EXAMPLES
    totals = sorted(ex.total_hours for ex in ESTIMATION_EXAMPLES_CATALOG)
    assert totals[0] < 150 and totals[-1] > 500  # de proyecto pequeño a grande


@pytest.mark.parametrize("ex", ESTIMATION_EXAMPLES_CATALOG, ids=lambda e: e.title[:25])
def test_example_totals_and_breakdown_are_coherent(ex):
    assert ex.total_hours == sum(h for _, _, h in ex.tareas)
    assert ex.rango[0] <= ex.total_hours <= ex.rango[1]
    assert all(h > 0 for _, _, h in ex.tareas)
    assert ex.supuestos and ex.requisitos and ex.riesgos and ex.preguntas
    md = ex.estimation_markdown
    assert f"**Total estimado:** {ex.total_hours} horas" in md
    rows = re.findall(r"^\|\s*(\d+)\s*\|[^|]+\|[^|]+\|\s*(\d+)\s*\|$", md, re.MULTILINE)
    assert [int(n) for n, _ in rows] == list(range(1, len(ex.tareas) + 1))
    assert sum(int(h) for _, h in rows) == ex.total_hours


def test_incoherent_range_is_rejected_at_construction():
    with pytest.raises(ValueError, match="rango"):
        EstimationExample(
            title="X",
            meeting_summary="s",
            supuestos=("a",),
            requisitos=("b",),
            tareas=(("Backend", "t", 10),),
            rango=(20, 30),
            equipo="e",
            duracion="d",
            riesgos=("r",),
            preguntas=("p",),
        )


def test_original_examples_keep_their_markdown_verbatim():
    first = ESTIMATION_EXAMPLES[0]["estimation"]
    assert first.startswith("## Estimación: Plataforma de Gestión de Inventario — Comercial Andina")
    assert "| 19 | PM | Gestión de proyecto, demos, documentación técnica | 20 |" in first
    assert "**Total estimado:** 292 horas" in first


# --- selección --------------------------------------------------------------


def test_select_examples_zero_negative_and_cap():
    assert select_examples(0) == []
    assert select_examples(-3) == []
    assert len(select_examples(3)) == 3
    assert len(select_examples(99)) == MAX_EXAMPLES


def test_select_examples_is_a_stable_prefix():
    assert select_examples(2) == ESTIMATION_EXAMPLES_CATALOG[:2]


# --- formatos ---------------------------------------------------------------


def test_markdown_format_contains_tables_and_all_selected():
    out = format_examples(select_examples(3), "markdown")
    assert out.count("### Historical Example") == 3
    assert out.count("| # | Área | Tarea | Horas |") == 3


def test_json_format_is_valid_and_consistent_with_the_data():
    out = format_examples(select_examples(4), "json")
    assert out.startswith("```json") and out.endswith("```")
    payload = json.loads(out.removeprefix("```json\n").removesuffix("\n```"))
    assert len(payload) == 4
    for item, ex in zip(payload, ESTIMATION_EXAMPLES_CATALOG):
        assert item["proyecto"] == ex.title
        tareas = item["desglose_de_tareas"]
        assert sum(t["horas"] for t in tareas) == item["resumen"]["total_horas"] == ex.total_hours
        assert item["resumen"]["rango_recomendado_horas"] == {"min": ex.rango[0], "max": ex.rango[1]}
        assert [t["n"] for t in tareas] == list(range(1, len(tareas) + 1))


def test_narrative_format_mentions_totals_and_has_no_markup():
    ex = ESTIMATION_EXAMPLES_CATALOG[0]
    out = format_examples([ex], "narrative")
    assert f"{ex.total_hours} horas" in out
    assert ex.title in out and ex.equipo in out
    assert "|" not in out and "###" not in out


def test_formats_share_the_same_numbers():
    ex = ESTIMATION_EXAMPLES_CATALOG[2]
    for fmt in ("markdown", "json", "narrative"):
        assert str(ex.total_hours) in format_examples([ex], fmt)


def test_empty_selection_renders_empty_string_in_every_format():
    for fmt in ("markdown", "json", "narrative"):
        assert format_examples([], fmt) == ""


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        format_examples(select_examples(1), "yaml")  # type: ignore[arg-type]
