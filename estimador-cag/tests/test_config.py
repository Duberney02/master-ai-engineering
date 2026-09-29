import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


def _openai(**kw) -> Settings:
    return Settings(llm_provider="openai", openai_api_key="sk-test", _env_file=None, **kw)


def _anthropic(**kw) -> Settings:
    return Settings(
        llm_provider="anthropic", anthropic_api_key="sk-ant-test", _env_file=None, **kw
    )


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


@pytest.mark.parametrize("options", [
    {"fallback_provider": "anthropic"},
    {"fallback_model": "claude"},
    {"fallback_provider": "anthropic", "fallback_model": "claude", "anthropic_api_key": None},
    {"llm_timeout": 0}, {"llm_retries": -1}, {"cache_ttl": 0},
    {"model_prices": {"model": {"input": -1, "output": 2}}},
    {"model_prices": {"model": {"input": float("inf"), "output": 2}}},
])
def test_invalid_resilience_settings(options):
    with pytest.raises(ValidationError):
        _openai(**options)
