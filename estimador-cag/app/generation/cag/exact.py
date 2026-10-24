"""Caché exacta de resultados validados: clave SHA-256 de solicitud, versión de prompt, proveedor y modelo."""

import structlog
from pydantic import BaseModel, ValidationError

from app.domain.schemas.project_estimation import EstimationRequest, EstimationResult
from app.foundation.llm.cache import EstimationCache, digest, make_key

logger = structlog.get_logger(__name__)


def make_result_key(request: EstimationRequest, prompt_version: str, provider: str, model: str) -> str:
    """Clave de la caché exacta de resultados validados (distinta de la de completions)."""
    return "estimation:v2:" + digest(
        {
            "request": request.model_dump(mode="json"),
            "prompt_version": prompt_version,
            "provider": provider,
            "model": model,
        }
    )


class CachedEstimation(BaseModel):
    """Resultado validado que comparten la caché exacta y la semántica."""

    result: EstimationResult
    model: str = ""
    provider: str = ""

    @classmethod
    def parse(cls, raw: object) -> "CachedEstimation | None":
        try:
            return cls.model_validate(raw)
        except ValidationError:
            logger.warning("cache_payload_invalid")
            return None

__all__ = ["CachedEstimation", "EstimationCache", "make_key", "make_result_key"]
