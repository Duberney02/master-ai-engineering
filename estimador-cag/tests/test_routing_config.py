"""Selección de modelos (primario, secundario, explícito, lista permitida) y validación."""

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.dependencies import build_policy
from app.llm.errors import ModelSelectionError
from app.llm.routing import ModelRef, ModelResolutionError, parse_model_ref
from tests._fakes import both_settings, openai_settings

OPENAI_MINI = ModelRef("openai", "gpt-4o-mini")
HAIKU = ModelRef("anthropic", "claude-haiku-4-5")


@pytest.mark.parametrize(
    "value, expected",
    [
        ("gpt-4o", ModelRef("openai", "gpt-4o")),
        ("o3-mini", ModelRef("openai", "o3-mini")),
        ("claude-haiku-4-5", HAIKU),
        ("anthropic/claude-haiku-4-5", HAIKU),
        ("openai/my-finetune", ModelRef("openai", "my-finetune")),
    ],
)
def test_parse_model_ref(value, expected):
    assert parse_model_ref(value) == expected


def test_unknown_provider_cannot_be_inferred():
    with pytest.raises(ModelResolutionError):
        parse_model_ref("llama-3")


def test_default_route_is_primary_then_fallback():
    policy = build_policy(both_settings(llm_fallback_model="claude-haiku-4-5"))
    assert policy.route_for(None).candidates == (OPENAI_MINI, HAIKU)


def test_explicit_model_is_respected_exactly_by_default():
    policy = build_policy(both_settings(llm_fallback_model="claude-haiku-4-5"))
    assert policy.route_for("gpt-4o").candidates == (ModelRef("openai", "gpt-4o"),)


def test_explicit_model_with_allow_fallback_adds_the_secondary():
    policy = build_policy(both_settings(llm_fallback_model="claude-haiku-4-5"))
    assert policy.route_for("gpt-4o", allow_fallback=True).candidates == (
        ModelRef("openai", "gpt-4o"), HAIKU,
    )
    # Pedir explícitamente el secundario no lo duplica.
    assert policy.route_for("claude-haiku-4-5", allow_fallback=True).candidates == (HAIKU,)


def test_allowlist_is_enforced_on_explicit_models_with_normalised_names():
    policy = build_policy(openai_settings(allowed_models="gpt-4o-mini,openai/gpt-4o"))
    assert policy.route_for("openai/gpt-4o-mini").candidates == (OPENAI_MINI,)
    assert policy.route_for("gpt-4o").candidates == (ModelRef("openai", "gpt-4o"),)
    with pytest.raises(ModelSelectionError, match="not allowed"):
        policy.route_for("gpt-4.1")


def test_model_of_unconfigured_provider_is_rejected():
    policy = build_policy(openai_settings())
    with pytest.raises(ModelSelectionError, match="not configured"):
        policy.route_for("claude-haiku-4-5")


def test_unresolvable_model_is_rejected():
    with pytest.raises(ModelSelectionError):
        build_policy(openai_settings()).route_for("llama-3")


# --------------------------------------------------------------------------- configuración


def test_fallback_requires_the_key_of_its_own_provider():
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY is required by LLM_FALLBACK_MODEL"):
        openai_settings(llm_fallback_model="claude-haiku-4-5")


def test_fallback_must_differ_from_primary():
    with pytest.raises(ValidationError, match="must differ"):
        openai_settings(llm_fallback_model="openai/gpt-4o-mini")


def test_allowed_models_need_resolvable_provider_and_key():
    with pytest.raises(ValidationError, match="cannot determine"):
        openai_settings(allowed_models="llama-3")
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY is not set"):
        openai_settings(allowed_models="gpt-4o,claude-haiku-4-5")


def test_llm_model_prefix_must_match_provider():
    with pytest.raises(ValidationError, match="LLM_PROVIDER"):
        Settings(llm_provider="openai", openai_api_key="k", anthropic_api_key="k",
                 llm_model="anthropic/claude-haiku-4-5", _env_file=None)


def test_prefixed_primary_model_is_accepted():
    s = Settings(llm_provider="anthropic", anthropic_api_key="k",
                 llm_model="anthropic/claude-sonnet-4-5", _env_file=None)
    assert s.primary_model() == ModelRef("anthropic", "claude-sonnet-4-5")


@pytest.mark.parametrize(
    "field, value",
    [("llm_max_retries", 6), ("llm_max_retries", -1), ("llm_timeout_seconds", 0),
     ("cache_ttl_seconds", 0), ("redis_timeout_seconds", 10), ("cache_prefix", "bad prefix")],
)
def test_bounded_settings(field, value):
    with pytest.raises(ValidationError):
        openai_settings(**{field: value})


def test_invalid_pricing_overrides_fail_at_startup():
    with pytest.raises(ValidationError, match="LLM_PRICING_OVERRIDES"):
        openai_settings(llm_pricing_overrides='{"openai/x": 3}')


def test_secrets_are_not_in_repr():
    assert "sk-test" not in repr(openai_settings())


def test_log_format_auto():
    assert openai_settings(app_env="production").resolved_log_format() == "json"
    assert openai_settings(app_env="development").resolved_log_format() == "console"
