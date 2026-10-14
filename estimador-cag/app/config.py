from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_OPENAI_DEFAULT = "gpt-4o-mini"
_ANTHROPIC_DEFAULT = "claude-haiku-4-5"


Task = Literal["estimator", "metadata", "summary", "critic"]


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
    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "DEBUG"
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
    # Sesiones conversacionales en memoria del proceso (ver app.services.sessions): turnos
    # (pares usuario+asistente) que conserva cada sesión —6 es app.services.sessions.MAX_TURNS—,
    # inactividad tras la que caduca y número máximo de sesiones simultáneas.
    session_max_turns: int = Field(default=6, ge=1, le=50)
    session_ttl_seconds: float = Field(default=6 * 3600, gt=0)
    session_max_count: int = Field(default=200, ge=1)
    # Modelo por tarea del LLM; sin valor, la tarea usa `effective_model()`. El del crítico lo consume
    # el orquestador Actor–Critic–Boss.
    estimator_model: str | None = Field(default=None, min_length=1, max_length=100)
    metadata_model: str | None = Field(default=None, min_length=1, max_length=100)
    summary_model: str | None = Field(default=None, min_length=1, max_length=100)
    critic_model: str | None = Field(default=None, min_length=1, max_length=100)
    # Detección de anclas de memoria: reglas locales o una llamada al LLM (con las reglas como respaldo).
    anchor_detection_mode: Literal["heuristic", "llm"] = "heuristic"
    # Versión del prompt de estimación que usan las sesiones cuando la solicitud no indica `prompt_version`.
    conversation_prompt_version: str = Field(default="v4", pattern=r"^v\d+$")
    # Máximo de generaciones del actor en el flujo Actor–Critic–Boss, contando la primera.
    boss_max_iterations: int = Field(default=3, ge=1, le=5)
    # Máximo de generaciones del actor en el flujo Actor–Critic–Boss, contando la primera.
    boss_max_iterations: int = Field(default=3, ge=1, le=5)

    @field_validator("app_env", mode="before")
    @classmethod
    def _normalize_app_env(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

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

    def model_for(self, task: Task) -> str:
        """Modelo de una tarea: el configurado para ella o, si no hay, el modelo efectivo global."""
        return getattr(self, f"{task}_model") or self.effective_model()

    def effective_model(self) -> str:
        """Return the model to use, applying per-provider defaults when needed."""
        if self.llm_provider == "anthropic" and self.llm_model == _OPENAI_DEFAULT:
            return _ANTHROPIC_DEFAULT
        return self.llm_model


@lru_cache
def get_settings() -> Settings:
    return Settings()
