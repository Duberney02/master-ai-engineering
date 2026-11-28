"""`scripts/eval_generation_s11.py` y `eval_ragas_s11.py`: umbrales del gate, código de salida y modo monitor.

Todo con MÉTRICAS FALSAS (un puntuador inyectado) y el orquestador real sobre dobles guionizados: nada llama a RAGAS ni a
un proveedor. La puntuación real con RAGAS exige claves y no corre en `pytest`.
"""

import json
import sys
from pathlib import Path

import pytest

from tests._grounded import (
    BRIEF,
    FakeRetriever,
    ScriptedGenerator,
    build_estimator,
    estimate_payload,
    line_task,
    make_chunk,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import eval_generation_s11 as gate  # noqa: E402
import eval_ragas_s11 as collect  # noqa: E402

BASELINE = {"faithfulness": 0.90, "answer_relevancy": 0.85, "context_precision": 0.80, "context_recall": 0.75}


def scores(**overrides) -> dict[str, float | None]:
    return {**BASELINE, **overrides}


class FakeScorer:
    """Devuelve las mismas puntuaciones para todas las muestras y recuerda con qué métricas se le llamó."""

    def __init__(self, **overrides) -> None:
        self.row = scores(**overrides)
        self.calls: list[tuple[int, tuple[str, ...]]] = []

    def __call__(self, samples, metrics):
        self.calls.append((len(samples), tuple(metrics)))
        return [{m: self.row.get(m) for m in metrics} for _ in samples]


def write_baseline(tmp_path: Path, metrics: dict | None = None) -> Path:
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"metrics": metrics or BASELINE}), encoding="utf-8")
    return path


def pipeline_estimator(golden_count: int = 6, *, dangling: bool = False):
    """Orquestador real: por consulta, una reformulación y una generación guionizadas."""
    chunks = [make_chunk(1), make_chunk(2, 0.3)]
    outcomes = []
    for _ in range(golden_count):
        outcomes += [BRIEF, estimate_payload(source_ids=(1,))]
        if dangling:
            outcomes[-1] = estimate_payload(
                source_ids=(1,),
                modules=[{"name": "Pagos", "description": None, "tasks": [line_task(chunk_ids=(999,))]}],
            )
    return build_estimator(ScriptedGenerator(*outcomes), FakeRetriever(chunks))


# --- Umbrales (funciones puras) --------------------------------------------------------------------------------


def test_a_drop_larger_than_the_tolerance_is_a_regression():
    regressions = gate.find_regressions(scores(faithfulness=0.82), BASELINE)

    assert [r.metric for r in regressions] == ["faithfulness"]
    assert regressions[0].drop == 0.08 and "cae 0.080" in regressions[0].describe()


def test_a_drop_equal_to_the_tolerance_or_an_improvement_is_not():
    assert gate.find_regressions(scores(faithfulness=0.85), BASELINE) == []  # exactamente 0,05
    assert gate.find_regressions(scores(faithfulness=0.99, context_recall=0.9), BASELINE) == []


def test_an_uncomputable_metric_fails_the_gate():
    regressions = gate.find_regressions(scores(context_recall=None), BASELINE)

    assert [r.metric for r in regressions] == ["context_recall"] and "no se pudo calcular" in regressions[0].describe()


def test_every_metric_is_checked_independently():
    regressions = gate.find_regressions(scores(faithfulness=0.5, answer_relevancy=0.5, context_precision=0.81), BASELINE)

    assert {r.metric for r in regressions} == {"faithfulness", "answer_relevancy"}


def test_a_dangling_citation_fails_even_with_perfect_metrics():
    verdict = gate.gate_verdict(scores(), BASELINE, dangling_citations=1)

    assert verdict.passed is False and verdict.regressions == []
    assert verdict.failures() == ["citas colgantes: 1 (debe ser 0)"]


def test_the_tolerance_is_configurable():
    assert gate.gate_verdict(scores(faithfulness=0.82), BASELINE, 0, tolerance=0.1).passed is True
    assert gate.gate_verdict(scores(faithfulness=0.82), BASELINE, 0, tolerance=0.05).passed is False


def test_mean_scores_ignore_missing_values():
    rows = [{"faithfulness": 1.0, "answer_relevancy": None}, {"faithfulness": 0.5, "answer_relevancy": None}]

    assert collect.mean_scores(rows, ("faithfulness", "answer_relevancy")) == {"faithfulness": 0.75, "answer_relevancy": None}


# --- --gate ----------------------------------------------------------------------------------------------------


def test_the_gate_passes_when_nothing_regresses(tmp_path, capsys):
    code = gate.main(
        ["--gate", "--no-judge", "--baseline", str(write_baseline(tmp_path))],
        estimator=pipeline_estimator(),
        scorer=FakeScorer(),
    )

    out = capsys.readouterr().out
    assert code == 0 and "PASS" in out and "FAIL" not in out


def test_a_faithfulness_drop_of_0_08_prints_fail_and_exits_non_zero(tmp_path, capsys):
    code = gate.main(
        ["--gate", "--no-judge", "--baseline", str(write_baseline(tmp_path))],
        estimator=pipeline_estimator(),
        scorer=FakeScorer(faithfulness=0.82),
    )

    out = capsys.readouterr().out
    assert code == 1 and "FAIL" in out and "faithfulness" in out and "0.080" in out


def test_a_dangling_citation_in_the_pipeline_fails_the_gate(tmp_path, capsys):
    code = gate.main(
        ["--gate", "--no-judge", "--baseline", str(write_baseline(tmp_path))],
        estimator=pipeline_estimator(dangling=True),
        scorer=FakeScorer(),
    )

    out = capsys.readouterr().out
    assert code == 1 and "FAIL" in out and "citas colgantes: 6" in out


def test_the_gate_scores_the_four_metrics_over_the_whole_golden_set(tmp_path):
    scorer = FakeScorer()

    gate.main(["--gate", "--no-judge", "--baseline", str(write_baseline(tmp_path))], estimator=pipeline_estimator(), scorer=scorer)

    assert scorer.calls == [(6, gate.METRICS)]


def test_the_gate_samples_carry_the_reference_and_the_retrieved_contexts(tmp_path):
    captured: list[dict] = []

    def spy(samples, metrics):
        captured.extend(samples)
        return [scores() for _ in samples]

    gate.main(["--gate", "--no-judge", "--baseline", str(write_baseline(tmp_path))], estimator=pipeline_estimator(), scorer=spy)

    first = captured[0]
    assert first["reference"] and first["user_input"] and first["retrieved_contexts"]
    assert "Onboarding KYC" in first["response"] and "Evidencia" in first["response"]


def test_without_a_baseline_the_gate_explains_how_to_create_it(tmp_path, capsys):
    code = gate.main(["--gate", "--baseline", str(tmp_path / "missing.json")], estimator=pipeline_estimator(), scorer=FakeScorer())

    assert code == 2 and "ragas_baseline_s11" not in capsys.readouterr().out  # el aviso va a stderr


# --- --monitor -------------------------------------------------------------------------------------------------


def test_the_monitor_scores_only_the_two_reference_free_metrics_and_exits_zero(capsys):
    captured: list[dict] = []
    scorer = FakeScorer(faithfulness=0.1, answer_relevancy=0.1)

    def spy(samples, metrics):
        captured.extend(samples)
        return scorer(samples, metrics)

    code = gate.main(["--monitor", "--sample", "2", "--no-judge"], estimator=pipeline_estimator(2), scorer=spy)

    out = capsys.readouterr().out
    assert code == 0  # aunque las métricas sean pésimas: el monitor no bloquea
    assert scorer.calls == [(2, ("faithfulness", "answer_relevancy"))]
    assert "faithfulness=0.100" in out and "answer_relevancy=0.100" in out and "context_recall" not in out
    assert all(sample["reference"] is None for sample in captured)  # sin ground_truth


def test_the_monitor_does_not_need_a_baseline(capsys):
    code = gate.main(
        ["--monitor", "--sample", "1", "--no-judge", "--baseline", "/nonexistent.json"],
        estimator=pipeline_estimator(1),
        scorer=FakeScorer(),
    )

    assert code == 0


def test_a_mode_is_required():
    with pytest.raises(SystemExit):
        gate.main([])


# --- Recolección y línea base ----------------------------------------------------------------------------------


def test_collect_only_writes_samples_and_never_calls_the_scorer(tmp_path):
    def forbidden(samples, metrics):
        raise AssertionError("--collect-only no puntúa")

    out = tmp_path / "samples.json"

    code = collect.main(
        ["--collect-only", "--no-judge", "--limit", "2", "--samples-out", str(out)],
        estimator=pipeline_estimator(2),
        scorer=forbidden,
    )

    saved = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0 and [s["id"] for s in saved["samples"]] == ["G1", "G2"]
    assert {"dangling_citations", "degraded_lines", "confidence"} <= set(saved["checks"][0])


def test_the_baseline_payload_and_report_cover_the_four_metrics(tmp_path):
    collected = collect.Collected(
        samples=[{"id": "G1"}, {"id": "G2"}],
        checks=[{"dangling_citations": [], "degraded_lines": 0}, {"dangling_citations": [], "degraded_lines": 1}],
    )
    rows = [scores(faithfulness=1.0), scores(faithfulness=0.8)]

    payload = collect.baseline_payload(collected.samples, rows, collected, judge_model="fake")
    collect.write_baseline(payload, tmp_path / "b.json", tmp_path / "b.md")

    assert payload["metrics"]["faithfulness"] == 0.9 and payload["checks"] == {"dangling_citations": 0, "degraded_lines": 1}
    report = (tmp_path / "b.md").read_text(encoding="utf-8")
    assert all(metric in report for metric in collect.METRICS) and "| G1 |" in report and "**media**" in report
    # Lo escrito es exactamente lo que el gate lee como línea base.
    assert gate.load_baseline(tmp_path / "b.json") == payload["metrics"]


def test_write_baseline_flag_versions_the_files(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, "BASELINE_PATH", tmp_path / "base.json")
    monkeypatch.setattr(collect, "REPORT_PATH", tmp_path / "base.md")

    code = collect.main(
        ["--write-baseline", "--no-judge", "--limit", "1", "--samples-out", str(tmp_path / "s.json")],
        estimator=pipeline_estimator(1),
        scorer=FakeScorer(),
    )

    assert code == 0 and (tmp_path / "base.md").exists()
    assert gate.load_baseline(tmp_path / "base.json") == FakeScorer().row  # el gate lee lo que se versionó


# --- Golden set y puntuador ------------------------------------------------------------------------------------


def test_the_golden_set_is_well_formed_and_anchored_in_the_corpus():
    queries = collect.load_golden()
    budgets = {b["budget_id"] for b in json.loads((ROOT / "data" / "budgets_sample.json").read_text(encoding="utf-8"))}

    assert len(queries) >= 5 and len({q["id"] for q in queries}) == len(queries)
    for query in queries:
        assert len(query["transcript"]) >= 100  # mínimo de `EstimateRequest.transcript`
        assert query["ground_truth"].strip() and set(query["relevant_budget_ids"]) <= budgets


def test_the_scorer_module_does_not_import_ragas_until_it_scores():
    import score_ragas_s11 as scorer

    assert "ragas" not in sys.modules
    with pytest.raises(ValueError, match="desconocidas"):
        scorer.score_samples([], ["bleu"])


def test_the_scorer_refuses_to_run_with_the_dummy_key(monkeypatch, tmp_path, capsys):
    import score_ragas_s11 as scorer

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")
    samples = tmp_path / "s.json"
    samples.write_text("[]", encoding="utf-8")

    assert scorer.main([str(samples)]) == 2
    assert "OPENAI_API_KEY real" in capsys.readouterr().err
