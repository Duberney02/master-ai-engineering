"""Configuración del cliente: solo la URL de la API y timeouts. Sin credenciales."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_BASE_URL = "http://localhost:8000"


@dataclass(frozen=True)
class ClientSettings:
    base_url: str = DEFAULT_BASE_URL
    connect_timeout: float = 5.0
    # Máxima espera sin recibir bytes; el servidor envía latidos SSE cada ~15 s.
    read_timeout: float = 120.0

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ClientSettings":
        env = os.environ if environ is None else environ
        base_url = (env.get("ESTIMATOR_API_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("ESTIMATOR_API_BASE_URL must start with http:// or https://")
        return cls(
            base_url=base_url,
            connect_timeout=_float(env, "ESTIMATOR_API_CONNECT_TIMEOUT_SECONDS", 5.0),
            read_timeout=_float(env, "ESTIMATOR_API_READ_TIMEOUT_SECONDS", 120.0),
        )


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    value = float(raw)
    if value <= 0:
        raise ValueError(f"{name} must be > 0")
    return value
