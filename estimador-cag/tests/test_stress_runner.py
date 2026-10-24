# ruff: noqa: F811
"""Runner del stress test en proceso con el LLM simulado: matriz, CSV por turno, errores y reutilización."""

import csv
import json

import pytest

from app.dependencies import get_session_store
from evals.stress import run
from evals.stress.scenarios import build_scenario
from tests import test_sessions_api as base

llm = base.llm
_fresh_session_store = base._fresh_session_store


def run_main(tmp_path, *extra):
    out = tmp_path / "results.csv"
    args = ["--fixtures-dir", str(tmp_path / "pdfs"), "--output", str(out), *extra]
    return run.main(args), out


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_matrix_writes_one_row_per_turn(llm, tmp_path):
    code, out = run_main(
        tmp_path,
        "--scenarios",
        "growing,pivot,contradiction",
        "--attachment-sizes",
        "0,5",
        "--repeats",
        "2",
        "--max-turns",
        "3",
    )

    rows = read_rows(out)
    assert code == 0 and len(rows) == 3 * 2 * 2 * 3  # escenarios × tamaños × repeticiones × turnos
    assert list(rows[0]) == list(run.COLUMNS)
    sessions = {(r["scenario"], r["attachment_kb"], r["repeat"]): r["session_id"] for r in rows}
    assert len(sessions) == 12 and len(set(sessions.values())) == 12  # una sesión por combinación
    assert len(get_session_store()) == 12


def test_rows_carry_the_turn_observation_metrics_and_grouping(llm, tmp_path):
    code, out = run_main(tmp_path, "--scenarios", "growing", "--attachment-sizes", "0", "--max-turns", "3")

    rows = read_rows(out)
    assert code == 0 and [r["turn_index"] for r in rows] == ["1", "2", "3"]
    first, third = rows[0], rows[2]
    assert first["server_turn_index"] == "1" and third["server_turn_index"] == "3"
    assert first["http_status"] == "200" and first["error"] == "" and first["model"] == "gpt-4o-mini"
    assert int(first["tokens_in"]) == 200 and int(first["tokens_out"]) == 100
    assert first["cache_hit_kind"] == "none" and first["last_resolved_tier"]
    assert int(third["messages_in_window"]) == 6 and int(first["attachments_total_chars"]) == 0
    assert first["latency_budget_score"] == "1.0" and first["cost_budget_score"] in {"0.0", "1.0"}
    assert first["is_checkpoint"] == "True" and rows[1]["is_checkpoint"] == "False"
    # El turno 1 no tiene hechos anteriores que evaluar; el 3 evalúa Atlas y Stripe.
    assert first["facts_evaluated"] == "0" and first["memory_recall"] == ""
    assert third["facts_evaluated"] == "2"
    assert set(json.loads(third["memory_details"])) == {"Atlas", "Stripe"}


def test_attachment_goes_in_turn_one_only_and_is_measured(llm, tmp_path):
    code, out = run_main(tmp_path, "--scenarios", "pivot", "--attachment-sizes", "5", "--max-turns", "3")

    rows = read_rows(out)
    assert code == 0
    assert int(rows[0]["attachments_total_chars"]) > 3000 and rows[0]["attachment_bytes"] != ""
    assert rows[1]["attachments_total_chars"] == "0" and rows[1]["attachment_bytes"] == ""
    first_call = llm.estimation_calls[0][-1]["content"]
    assert "--- attachment: adjunto_5kb.pdf ---" in first_call and "Veridian" in first_call
    assert first_call.count("--- attachment:") == 1
    # El hecho del adjunto se rastrea desde el turno 2 (el 1 no tiene snapshot posterior).
    assert rows[0]["attachment_fact_retained"] == "" and rows[1]["attachment_fact_retained"] in {"0", "1"}


def test_same_short_transcript_for_every_attachment_size(llm, tmp_path):
    run_main(tmp_path, "--scenarios", "growing", "--attachment-sizes", "0,5", "--max-turns", "1")

    transcript = build_scenario("growing").turns[0].transcript
    users = [c[-1]["content"] for c in llm.estimation_calls]
    assert len(users) == 2 and all(transcript in user for user in users)


def test_failed_turn_gets_its_row_and_the_session_continues(llm, tmp_path):
    llm.estimations += ["no es json"] * 3  # agota la validación del turno 1: 502
    code, out = run_main(tmp_path, "--scenarios", "growing", "--attachment-sizes", "0", "--max-turns", "3")

    rows = read_rows(out)
    assert code == 1 and len(rows) == 3
    assert rows[0]["http_status"] == "502" and rows[0]["error"] != "" and rows[0]["tokens_in"] == ""
    assert rows[1]["http_status"] == "200" and rows[1]["error"] == ""
    # El índice del servidor no consume el turno fallido.
    assert rows[1]["turn_index"] == "2" and rows[1]["server_turn_index"] == "1"


def test_budgets_are_applied_per_turn(llm, tmp_path):
    code, out = run_main(
        tmp_path,
        "--scenarios",
        "growing",
        "--attachment-sizes",
        "0",
        "--max-turns",
        "1",
        "--latency-budget-ms",
        "0",
        "--cost-budget-usd",
        "1",
    )

    (row,) = read_rows(out)
    assert code == 0 and row["latency_budget_ms"] == "0.0" and row["cost_budget_usd"] == "1.0"
    # Con presupuesto de 1 USD un coste conocido cumple; si el modelo no tiene tarifa, el coste es desconocido y falla.
    assert row["cost_budget_score"] == ("0.0" if row["cost_usd"] == "" else "1.0")
    assert row["latency_budget_score"] == ("1.0" if int(row["latency_ms"]) == 0 else "0.0")


@pytest.mark.parametrize(
    "args",
    [
        ["--scenarios", "otro"],
        ["--attachment-sizes", "a,b"],
        ["--attachment-sizes", "-5"],
        ["--repeats", "0"],
        ["--max-turns", "7"],
        ["--latency-budget-ms", "-1"],
    ],
)
def test_invalid_usage_exits_with_two(llm, tmp_path, args):
    code, out = run_main(tmp_path, *args)

    assert code == 2 and not out.exists()
