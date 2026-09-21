from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_OPENAI_DEFAULT = "gpt-4o-mini"
_ANTHROPIC_DEFAULT = "claude-haiku-4-5"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_model: str = _OPENAI_DEFAULT
    app_env: str = "development"
    log_level: str = "DEBUG"
    # Lista separada por comas de modelos que las solicitudes pueden pedir con el
    # campo `model`. Vacía = sin restricción (solo se valida el formato del nombre).
    allowed_models: str = ""

    @model_validator(mode="after")
    def validate_provider_key(self) -> "Settings":
        if self.llm_provider == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        return self

    def allowed_models_list(self) -> list[str]:
        return [m.strip() for m in self.allowed_models.split(",") if m.strip()]

    def effective_model(self) -> str:
        """Return the model to use, applying per-provider defaults when needed."""
        if self.llm_provider == "anthropic" and self.llm_model == _OPENAI_DEFAULT:
            return _ANTHROPIC_DEFAULT
        return self.llm_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
