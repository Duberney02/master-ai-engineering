import json

import pytest

from app.schemas import EstimationResult
from app.services.validation import (
    ResultValidationError,
    apply_out_of_scope_filter,
    validate_text,
)


def _payload(**overrides) -> dict:
    base = {
        "summary": "Proyecto mediano con integración de pagos.",
        "confidence_pct": 70,
        "phases": [
            {"name": "Diseño", "description": "UX", "duration_weeks": 2, "cost_eur": 4000},
            {"name": "Desarrollo", "description": "API", "duration_weeks": 8, "cost_eur": 16000},
        ],
        "total_duration_weeks": 10,
        "total_cost_eur": 20000,
    }
    return {**base, **overrides}


def test_valid_text_is_parsed():
    result = validate_text(json.dumps(_payload()))
    assert result.total_cost_eur == 20000 and not result.out_of_scope


def test_json_inside_code_fence_and_prose_is_accepted():
    text = "Aquí tienes:\n```json\n" + json.dumps(_payload()) + "\n```"
    assert validate_text(text).confidence_pct == 70


@pytest.mark.parametrize("text", ["sin json", "{no es json}", "[1, 2]"])
def test_non_json_is_rejected(text):
    with pytest.raises(ResultValidationError):
        validate_text(text)


@pytest.mark.parametrize(
    "overrides",
    [
        {"confidence_pct": 120},
        {"phases": []},
        {"phases": [{"name": "X", "duration_weeks": 1, "cost_eur": -5}], "total_cost_eur": -5},
        {"summary": ""},
    ],
)
def test_schema_violations_are_rejected(overrides):
    with pytest.raises(ResultValidationError, match="esquema"):
        validate_text(json.dumps(_payload(**overrides)))


def test_cost_sum_mismatch_is_reported_with_both_numbers():
    with pytest.raises(ResultValidationError, match=r"20000.*25000|\(20000\).*\(25000\)"):
        validate_text(json.dumps(_payload(total_cost_eur=25000)))


def test_cost_sum_tolerates_one_cent():
    assert validate_text(json.dumps(_payload(total_cost_eur=20000.005)))


def test_low_confidence_requires_out_of_scope_prefix():
    with pytest.raises(ResultValidationError, match="Out of scope:"):
        validate_text(json.dumps(_payload(confidence_pct=20)))
    ok = validate_text(json.dumps(_payload(confidence_pct=20, summary="Out of scope: sin datos.")))
    assert ok.out_of_scope


def test_confidence_30_is_in_scope():
    assert not validate_text(json.dumps(_payload(confidence_pct=30))).out_of_scope


def test_out_of_scope_filter_builds_zero_cost_one_week_placeholder():
    result = EstimationResult.model_validate(
        _payload(confidence_pct=10, summary="Out of scope: faltan requisitos.")
    )

    filtered = apply_out_of_scope_filter(result)

    assert filtered.summary == "Out of scope: faltan requisitos."
    assert [(p.name, p.cost_eur, p.duration_weeks) for p in filtered.phases] == [
        ("No estimable", 0, 1)
    ]
    assert filtered.total_cost_eur == 0 and filtered.total_duration_weeks == 1
    assert filtered.out_of_scope
    assert validate_text(filtered.model_dump_json())  # sigue siendo un resultado válido


def test_filter_leaves_in_scope_results_untouched():
    result = EstimationResult.model_validate(_payload())
    assert apply_out_of_scope_filter(result) is result


def test_out_of_scope_is_serialized():
    assert EstimationResult.model_validate(_payload()).model_dump()["out_of_scope"] is False
