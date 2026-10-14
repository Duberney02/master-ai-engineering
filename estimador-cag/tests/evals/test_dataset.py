"""Dataset de referencia: cobertura, versionado y validación estricta."""

import json
from collections import Counter

import pytest

from evals.dataset import CATEGORIES, DEFAULT_DATASET, load_dataset

CASE = {
    "id": "caso-01",
    "category": "saas",
    "title": "Caso de prueba",
    "project_type": "web_saas",
    "transcript": "Queremos una plataforma para gestionar reservas con pago online.",
    "expectations": {"requirements": ["reservas"], "cost_eur": [1000, 5000]},
}


def write(tmp_path, cases, version="9"):
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps({"version": version, "cases": cases}), encoding="utf-8")
    return path


def test_reference_dataset_has_16_cases_two_per_category():
    dataset = load_dataset()

    assert dataset.version == "1" and DEFAULT_DATASET.name == "reference_v1.json"
    assert len(dataset.cases) == 16
    assert Counter(c.category for c in dataset.cases) == {category: 2 for category in CATEGORIES}
    assert len(CATEGORIES) == 8


def test_case_identifiers_are_unique_and_stable():
    ids = [c.id for c in load_dataset().cases]

    assert len(set(ids)) == 16 and "adversarial-01" in ids and "regulatory-01" in ids


def test_cases_with_figures_define_expected_content_and_ranges():
    figures = {"saas", "mobile", "internal_tool", "data_pipeline", "regulatory", "tight_deadline"}
    for case in load_dataset().cases:
        if case.category not in figures:
            continue
        e = case.expectations
        assert e.requirements or e.technologies, case.id
        assert e.cost_eur and e.duration_weeks and e.phases, case.id


def test_vague_cases_expect_out_of_scope_and_one_adversarial_case_expects_rejection():
    cases = {c.id: c for c in load_dataset().cases}

    assert all(c.expectations.expect_out_of_scope for c in cases.values() if c.category == "vague")
    assert cases["adversarial-01"].expectations.expect_rejection == "prompt_injection"
    assert cases["adversarial-02"].expectations.cost_eur[0] >= 100_000


def test_the_injection_case_really_triggers_the_guardrail():
    from app.services.guardrails import detect_prompt_injection

    case = next(c for c in load_dataset().cases if c.id == "adversarial-01")

    assert detect_prompt_injection(case.transcript)


def test_no_other_case_trips_the_input_guardrails():
    from app.services.guardrails import detect_pii, detect_prompt_injection

    for case in load_dataset().cases:
        if case.id != "adversarial-01":
            assert not detect_prompt_injection(case.transcript) and detect_pii(case.transcript) is None, case.id


def test_valid_custom_dataset_loads(tmp_path):
    dataset = load_dataset(write(tmp_path, [CASE]))

    assert dataset.version == "9" and dataset.cases[0].id == "caso-01"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"surprise": 1}, "surprise"),
        ({"transcript": "corta"}, "transcript"),
        ({"category": "otra"}, "category"),
        ({"id": "Con Espacios"}, "id"),
        ({"expectations": {"cost_eur": [5000, 1000]}}, "rango"),
        ({"expectations": {}}, "ninguna expectativa"),
        ({"expectations": {"expect_out_of_scope": True, "expect_rejection": "prompt_injection"}}, "excluyentes"),
        ({"expectations": {"requirements": ["x"], "nope": 1}}, "nope"),
    ],
)
def test_invalid_cases_fail_to_load_with_an_explicit_error(tmp_path, change, message):
    with pytest.raises(ValueError, match=message):
        load_dataset(write(tmp_path, [{**CASE, **change}]))


def test_duplicate_identifiers_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="duplicados"):
        load_dataset(write(tmp_path, [CASE, CASE]))


def test_unreadable_or_malformed_files_raise_value_error(tmp_path):
    with pytest.raises(ValueError, match="No se pudo leer"):
        load_dataset(tmp_path / "no-existe.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{no es json", encoding="utf-8")
    with pytest.raises(ValueError, match="No se pudo leer"):
        load_dataset(bad)
