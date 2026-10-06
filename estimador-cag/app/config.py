from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_OPENAI_DEFAULT = "gpt-4o-mini"
_ANTHROPIC_DEFAULT = "claude-haiku-4-5"


class ModelPrice(BaseModel):
    input: float = Field(ge=0, allow_inf_nan=False)
    output: float = Field(ge=0, allow_inf_nan=False)


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
    llm_timeout: float = Field(default=60, gt=0, le=600)
    llm_retries: int = Field(default=2, ge=0, le=5)
    fallback_provider: Literal["openai", "anthropic"] | None = None
    fallback_model: str | None = None
    redis_url: str | None = None
    cache_ttl: int = Field(default=86400, gt=0)
    cache_timeout: float = Field(default=0.5, gt=0, le=10)
    model_prices: dict[str, ModelPrice] = Field(default_factory=dict)
    # Guardrails de entrada: la moderación usa OpenAI y se omite sin OPENAI_API_KEY.
    moderation_enabled: bool = True
    moderation_model: str = "omni-moderation-latest"
    moderation_fail_open: bool = True
    # Embeddings (OpenAI) y caché semántica sobre Redis Stack. El umbral es una
    # similitud coseno (1 = idéntico); log_only consulta y registra sin devolver aciertos.
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, gt=0, le=8192)
    semantic_cache_mode: Literal["off", "log_only", "active"] = "active"
    semantic_cache_threshold: float = Field(default=0.92, ge=0, le=1)
    semantic_cache_ttl: int = Field(default=86400, gt=0)
    # Por encima de esta longitud (caracteres) la caché semántica se omite: los embeddings
    # tienen un límite de tokens y truncar produciría aciertos falsos entre transcripciones.
    semantic_cache_max_chars: int = Field(default=8000, gt=0)
    # PostgreSQL del historial (postgresql+asyncpg://...). Sin valor, el historial se desactiva.
    database_url: str | None = None
    # Intentos totales para obtener un resultado que cumpla las reglas de negocio.
    validation_max_attempts: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def validate_provider_key(self) -> "Settings":
        if self.llm_provider == "openai" and not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        if bool(self.fallback_provider) != bool(self.fallback_model):
            raise ValueError("FALLBACK_PROVIDER and FALLBACK_MODEL must be configured together")
        if self.fallback_provider and not getattr(self, f"{self.fallback_provider}_api_key"):
            raise ValueError("API key for FALLBACK_PROVIDER is required")
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
