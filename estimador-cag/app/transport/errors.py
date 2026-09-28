"""Traducción de errores del dominio/wrapper al contrato HTTP y SSE.

Los mensajes son fijos y saneados: nunca incluyen el texto de excepciones de SDK,
credenciales ni rutas internas.
"""

from dataclasses import dataclass

from app.llm.errors import (
    LLMAuthError,
    LLMEmptyResponseError,
    LLMError,
    LLMInvalidRequestError,
    LLMRateLimitError,
    LLMStreamInterruptedError,
    LLMTimeoutError,
    LLMUnavailableError,
    ModelSelectionError,
)


@dataclass(frozen=True)
class PublicError:
    status: int
    code: str
    message: str
    retryable: bool = False


def public_error(exc: BaseException) -> PublicError:
    if isinstance(exc, ModelSelectionError):
        return PublicError(422, "model_not_allowed", exc.message)
    if isinstance(exc, LLMStreamInterruptedError):
        return PublicError(502, "stream_interrupted",
                           "LLM stream was interrupted after partial output", True)
    if isinstance(exc, LLMAuthError):
        return PublicError(502, "provider_auth", "LLM authentication failed")
    if isinstance(exc, LLMTimeoutError):
        return PublicError(504, "provider_timeout", "LLM request timed out", True)
    if isinstance(exc, LLMRateLimitError):
        return PublicError(429, "provider_rate_limited", "LLM provider rate limit reached", True)
    if isinstance(exc, LLMInvalidRequestError):
        return PublicError(400, "provider_rejected_request",
                           "LLM provider rejected the request (check model and options)")
    if isinstance(exc, LLMEmptyResponseError):
        return PublicError(502, "provider_empty_response", "LLM returned an empty response", True)
    if isinstance(exc, LLMUnavailableError):
        return PublicError(502, "provider_unavailable", "LLM provider error", True)
    if isinstance(exc, LLMError):
        return PublicError(502, "provider_error", "LLM provider error")
    return PublicError(500, "internal_error", "Internal server error")
