import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


def _openai(**kw) -> Settings:
    return Settings(llm_provider="openai", openai_api_key="sk-test", _env_file=None, **kw)


def _anthropic(**kw) -> Settings:
    return Settings(llm_provider="anthropic", anthropic_api_key="sk-ant-test", _env_file=None, **kw)


def test_openai_requires_key():
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(llm_provider="openai", openai_api_key=None, _env_file=None)


def test_anthropic_requires_key():
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        Settings(llm_provider="anthropic", anthropic_api_key=None, _env_file=None)


def test_openai_valid():
    s = _openai()
    assert s.llm_provider == "openai"
    assert s.openai_api_key == "sk-test"


def test_anthropic_valid():
    s = _anthropic()
    assert s.llm_provider == "anthropic"


def test_effective_model_openai_default():
    s = _openai()
    assert s.effective_model() == "gpt-4o-mini"


def test_effective_model_anthropic_substitutes_openai_default():
    # When provider is anthropic but model was left at the OpenAI default,
    # effective_model() must return the Anthropic default instead.
    s = _anthropic(llm_model="gpt-4o-mini")
    assert s.effective_model() == "claude-haiku-4-5"


def test_effective_model_anthropic_explicit_override():
    s = _anthropic(llm_model="claude-opus-4-8")
    assert s.effective_model() == "claude-opus-4-8"


def test_get_settings_is_cached(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-test")
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


@pytest.mark.parametrize(
    "options",
    [
        {"fallback_provider": "anthropic"},
        {"fallback_model": "claude"},
        {"fallback_provider": "anthropic", "fallback_model": "claude", "anthropic_api_key": None},
        {"llm_timeout": 0},
        {"llm_retries": -1},
        {"cache_ttl": 0},
        {"model_prices": {"model": {"input": -1, "output": 2}}},
        {"model_prices": {"model": {"input": float("inf"), "output": 2}}},
    ],
)
def test_invalid_resilience_settings(options):
    with pytest.raises(ValidationError):
        _openai(**options)


def test_guardrail_and_semantic_cache_defaults():
    s = _openai()
    assert s.moderation_enabled and s.moderation_fail_open
    assert s.semantic_cache_mode == "active"
    assert s.semantic_cache_threshold == 0.92
    assert s.semantic_cache_ttl == 86400
    assert s.embedding_model == "text-embedding-3-small" and s.embedding_dimensions == 1536
    assert s.validation_max_attempts == 3


@pytest.mark.parametrize(
    "overrides",
    [
        {"semantic_cache_mode": "maybe"},
        {"semantic_cache_threshold": 1.5},
        {"semantic_cache_ttl": 0},
        {"validation_max_attempts": 0},
        {"embedding_dimensions": 0},
    ],
)
def test_invalid_semantic_cache_and_validation_settings(overrides):
    with pytest.raises(ValidationError):
        _openai(**overrides)


def test_task_models_default_to_the_effective_model():
    settings = _openai(llm_model="gpt-4o")

    assert all(settings.model_for(task) == "gpt-4o" for task in ("estimator", "metadata", "summary", "critic"))


def test_each_task_can_use_its_own_model():
    settings = _openai(estimator_model="gpt-4o", summary_model="gpt-4o-mini", critic_model="gpt-6-sol")

    assert settings.model_for("estimator") == "gpt-4o"
    assert settings.model_for("summary") == "gpt-4o-mini"
    assert settings.model_for("critic") == "gpt-6-sol"
    assert settings.model_for("metadata") == settings.effective_model()


def test_task_models_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("CRITIC_MODEL", "gpt-6-sol")

    assert Settings(llm_provider="openai", openai_api_key="sk", _env_file=None).model_for("critic") == "gpt-6-sol"


def test_anchor_detection_mode_defaults_to_heuristic_and_rejects_unknown_values():
    assert _openai().anchor_detection_mode == "heuristic"
    assert _openai(anchor_detection_mode="llm").anchor_detection_mode == "llm"
    with pytest.raises(ValidationError):
        _openai(anchor_detection_mode="magic")
    with pytest.raises(ValidationError):
        _openai(summary_model="")


def test_conversation_prompt_version_defaults_to_v4_and_validates_the_format():
    assert _openai().conversation_prompt_version == "v4"
    assert _openai(conversation_prompt_version="v3").conversation_prompt_version == "v3"
    for invalid in ("latest", "../v3", "v", "V3"):
        with pytest.raises(ValidationError):
            _openai(conversation_prompt_version=invalid)


def test_boss_max_iterations_defaults_to_three_and_is_bounded():
    assert _openai().boss_max_iterations == 3
    assert _openai(boss_max_iterations=1).boss_max_iterations == 1 and _openai(boss_max_iterations=5)
    for invalid in (0, 6, -1):
        with pytest.raises(ValidationError):
            _openai(boss_max_iterations=invalid)


def test_app_env_and_log_level_defaults():
    settings = _openai()

    assert settings.app_env == "development" and settings.log_level == "DEBUG"


@pytest.mark.parametrize(
    ("env", "level", "expected_env", "expected_level"),
    [
        ("production", "INFO", "production", "INFO"),
        ("Production", "warning", "production", "WARNING"),
        ("  STAGING ", " error ", "staging", "ERROR"),
        ("test", "critical", "test", "CRITICAL"),
        ("development", "Debug", "development", "DEBUG"),
    ],
)
def test_app_env_and_log_level_are_normalized(env, level, expected_env, expected_level):
    settings = _openai(app_env=env, log_level=level)

    assert (settings.app_env, settings.log_level) == (expected_env, expected_level)


@pytest.mark.parametrize(
    "options",
    [
        {"app_env": "prod"},
        {"app_env": ""},
        {"app_env": "local"},
        {"log_level": "verbose"},
        {"log_level": ""},
        {"log_level": "WARN"},
        {"log_level": "FATAL"},
        {"log_level": 10},
    ],
)
def test_invalid_app_env_and_log_level_are_rejected(options):
    with pytest.raises(ValidationError):
        _openai(**options)


def test_invalid_environment_variables_are_rejected(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "chatty")

    with pytest.raises(ValidationError):
        Settings(llm_provider="openai", openai_api_key="sk", _env_file=None)
