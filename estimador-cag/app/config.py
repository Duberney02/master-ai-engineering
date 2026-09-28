"""Configuración del **servidor** (API). El cliente Streamlit tiene la suya en
`estimator_client/config.py` y nunca carga este módulo ni sus credenciales."""

import json
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.llm.routing import ModelRef, ModelResolutionError, parse_model_ref

_OPENAI_DEFAULT = "gpt-4o-mini"
_ANTHROPIC_DEFAULT = "claude-haiku-4-5"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Credenciales (solo backend) -----------------------------------------
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    # --- Modelos ---------------------------------------------------------------
    # Proveedor del modelo primario (compatibilidad con la configuración previa).
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_model: str = _OPENAI_DEFAULT
    # Modelo secundario opcional: `proveedor/modelo` o un nombre cuyo proveedor se
    # pueda inferir (gpt-*, o1/o3/o4*, claude-*). Vacío = sin fallback.
    llm_fallback_model: str = ""
    # Lista separada por comas de modelos que las solicitudes pueden pedir con el
    # campo `model`. Vacía = sin restricción (solo formato y proveedor configurado).
    allowed_models: str = ""

    # --- Timeouts y reintentos del wrapper LLM ---------------------------------
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_retry_backoff_seconds: float = Field(default=0.5, ge=0, le=10)
    # Espera máxima de una petición idéntica concurrente por el resultado de otra.
    llm_inflight_wait_seconds: float = Field(default=120.0, gt=0, le=900)
    # JSON opcional para ampliar/sustituir la tabla de precios de app/llm/pricing.py:
    # {"openai/gpt-4.1": {"input": 2.0, "output": 8.0}} (USD por millón de tokens).
    llm_pricing_overrides: str = ""

    # --- Caché Redis -----------------------------------------------------------
    cache_enabled: bool = True
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = Field(default=86_400, ge=1, le=30 * 86_400)
    cache_prefix: str = Field(default="estimador-cag", pattern=r"^[A-Za-z0-9._-]{1,40}$")
    redis_timeout_seconds: float = Field(default=0.5, gt=0, le=5)
    # Tras un fallo de Redis se deja de consultar durante este intervalo (modo degradado).
    cache_retry_after_seconds: float = Field(default=15.0, ge=0, le=600)

    # --- SSE ------------------------------------------------------------------
    sse_heartbeat_seconds: float = Field(default=15.0, gt=0, le=120)

    # --- Aplicación -------------------------------------------------------------
    app_env: str = "development"
    log_level: str = "DEBUG"
    # auto = JSON si APP_ENV=production, legible en cualquier otro caso.
    log_format: Literal["auto", "json", "console"] = "auto"

    @model_validator(mode="after")
    def validate_models_and_credentials(self) -> "Settings":
        if self.llm_provider == "openai" and not self._has_key("openai"):
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        if self.llm_provider == "anthropic" and not self._has_key("anthropic"):
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")

        primary = self.primary_model()
        if primary.provider != self.llm_provider:
            raise ValueError(
                f"LLM_MODEL points to provider '{primary.provider}' but LLM_PROVIDER="
                f"{self.llm_provider}"
            )

        fallback = self.fallback_model()
        if fallback is not None:
            if fallback == primary:
                raise ValueError("LLM_FALLBACK_MODEL must differ from the primary model")
            if not self._has_key(fallback.provider):
                raise ValueError(
                    f"{fallback.provider.upper()}_API_KEY is required by LLM_FALLBACK_MODEL"
                )

        for ref in self.allowed_model_refs():
            if not self._has_key(ref.provider):
                raise ValueError(
                    f"ALLOWED_MODELS includes '{ref}' but {ref.provider.upper()}_API_KEY is not set"
                )
        self.pricing_overrides()  # valida el JSON al arrancar
        return self

    # --- Helpers -----------------------------------------------------------------

    def _has_key(self, provider: str) -> bool:
        secret = self.openai_api_key if provider == "openai" else self.anthropic_api_key
        return bool(secret and secret.get_secret_value())

    def api_key(self, provider: str) -> str | None:
        secret = self.openai_api_key if provider == "openai" else self.anthropic_api_key
        return secret.get_secret_value() if secret else None

    def configured_providers(self) -> frozenset[str]:
        return frozenset(p for p in ("openai", "anthropic") if self._has_key(p))

    def allowed_models_list(self) -> list[str]:
        return [m.strip() for m in self.allowed_models.split(",") if m.strip()]

    def allowed_model_refs(self) -> frozenset[ModelRef]:
        try:
            return frozenset(parse_model_ref(m) for m in self.allowed_models_list())
        except ModelResolutionError as exc:
            raise ValueError(f"ALLOWED_MODELS: {exc}") from None

    def effective_model(self) -> str:
        """Return the model to use, applying per-provider defaults when needed."""
        model = self.llm_model
        if "/" in model:
            model = model.split("/", 1)[1]
        if self.llm_provider == "anthropic" and model == _OPENAI_DEFAULT:
            return _ANTHROPIC_DEFAULT
        return model

    def primary_model(self) -> ModelRef:
        prefix = self.llm_model.split("/", 1)[0] if "/" in self.llm_model else None
        if prefix is not None and prefix in ("openai", "anthropic"):
            return ModelRef(provider=prefix, name=self.effective_model())
        # LLM_PROVIDER define el proveedor del primario aunque el nombre no lo delate.
        return ModelRef(provider=self.llm_provider, name=self.effective_model())

    def fallback_model(self) -> ModelRef | None:
        if not self.llm_fallback_model.strip():
            return None
        try:
            return parse_model_ref(self.llm_fallback_model.strip())
        except ModelResolutionError as exc:
            raise ValueError(f"LLM_FALLBACK_MODEL: {exc}") from None

    def pricing_overrides(self) -> dict[str, dict[str, float]]:
        if not self.llm_pricing_overrides.strip():
            return {}
        try:
            data = json.loads(self.llm_pricing_overrides)
            return {
                str(k): {"input": float(v["input"]), "output": float(v["output"])}
                for k, v in data.items()
            }
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValueError(
                'LLM_PRICING_OVERRIDES must be JSON like {"openai/gpt-4o": {"input": 2.5, "output": 10}}'
            ) from None

    def resolved_log_format(self) -> Literal["json", "console"]:
        if self.log_format != "auto":
            return self.log_format
        return "json" if self.app_env.lower() in ("production", "prod") else "console"


@lru_cache
def get_settings() -> Settings:
    return Settings()
