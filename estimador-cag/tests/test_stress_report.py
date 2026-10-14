# ruff: noqa: F811
"""Generador de REPORT.md: tablas por escenario × tamaño, tres curvas e instrucciones, todo desde el CSV."""

from evals.stress import report, run
from tests import test_sessions_api as base

llm = base.llm
_fresh_session_store = base._fresh_session_store


def measure(tmp_path):
    out = tmp_path / "results.csv"
    code = run.main(
        [
            "--fixtures-dir", str(tmp_path / "pdfs"), "--output", str(out), "--scenarios", "pivot,contradiction",
            "--attachment-sizes", "0,5", "--repeats", "2", "--max-turns", "3",
        ]
    )  # fmt: skip
    assert code == 0
    return out


def test_percentile_interpolates_and_handles_edges():
    assert report.percentile([], 0.5) is None
    assert report.percentile([7], 0.95) == 7
    assert report.percentile([10, 20, 30, 40], 0.5) == 25
    assert report.percentile([10, 20, 30, 40], 0.95) == 38.5


def test_report_has_every_section_and_comes_from_the_csv(llm, tmp_path):
    csv_path = measure(tmp_path)
    output = tmp_path / "REPORT.md"

    code = report.main(["--input", str(csv_path), "--output", str(output), "--analysis", str(tmp_path / "none.md")])

    text = output.read_text(encoding="utf-8")
    assert code == 0
    assert "24 filas" in text and "8 sesiones" in text  # 2 escenarios × 2 tamaños × 2 repeticiones × 3 turnos
    for section in (
        "## 1.",
        "Latencia vs `tokens_in`",
        "Coste acumulado por sesión vs turno",
        "Recall de memoria vs N",
        "## 5. Límites",
        "## 6. Reproducir",
    ):
        assert section in text
    assert "| pivot | 0 | 2/2 |" in text and "| contradiction | 5 | 2/2 |" in text
    assert "N=1" in text and "N=3" in text and "turno 3" in text
    assert "api-stress" in text and "--http http://host.docker.internal:8000" in text
    assert "Pendiente" in text  # sin analysis.md el reporte lo indica en vez de inventar prosa


def test_analysis_file_is_embedded_verbatim(llm, tmp_path):
    csv_path = measure(tmp_path)
    analysis = tmp_path / "analysis.md"
    analysis.write_text("El CAG degrada con el adjunto.", encoding="utf-8")
    output = tmp_path / "REPORT.md"

    report.main(["--input", str(csv_path), "--output", str(output), "--analysis", str(analysis)])

    assert "El CAG degrada con el adjunto." in output.read_text(encoding="utf-8")


def test_missing_input_is_a_usage_error(tmp_path):
    assert report.main(["--input", str(tmp_path / "no.csv"), "--output", str(tmp_path / "r.md")]) == 2
