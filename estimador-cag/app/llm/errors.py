"""Excepciones del wrapper LLM, independientes de FastAPI y de los SDK.

Cada error lleva su **política**: si se puede reintentar con el mismo modelo y si
se permite pasar al siguiente candidato (fallback). La capa de transporte
(`app/transport/errors.py`) las traduce a HTTP/SSE con mensajes saneados.

| Tipo               | Reintento mismo modelo | Fallback |
|--------------------|:----------------------:|:--------:|
| timeout            | sí                     | sí       |
| rate_limited       | sí                     | sí       |
| unavailable (5xx, conexión) | sí            | sí       |
| auth               | no                     | sí       |
| empty_response     | no                     | sí       |
| provider_error (desconocido) | no           | sí       |
| invalid_request    | no                     | no       |
| stream_interrupted (tras emitir contenido) | no | no  |
"""


class LLMError(Exception):
    kind: str = "provider_error"
    retryable: bool = False
    fallback_allowed: bool = True

    def __init__(self, message: str = "", *, provider: str | None = None, model: str | None = None):
        # El mensaje es interno (logs sin datos sensibles); nunca se devuelve al usuario.
        super().__init__(message or self.kind)
        self.provider = provider
        self.model = model


class LLMAuthError(LLMError):
    kind = "auth"


class LLMTimeoutError(LLMError):
    kind = "timeout"
    retryable = True


class LLMRateLimitError(LLMError):
    kind = "rate_limited"
    retryable = True


class LLMUnavailableError(LLMError):
    kind = "unavailable"
    retryable = True


class LLMInvalidRequestError(LLMError):
    kind = "invalid_request"
    fallback_allowed = False


class LLMEmptyResponseError(LLMError):
    kind = "empty_response"


class LLMProviderError(LLMError):
    kind = "provider_error"


class LLMStreamInterruptedError(LLMError):
    """El proveedor falló después de haber emitido contenido: no se reintenta ni se
    cambia de modelo para no mezclar ni duplicar respuestas."""

    kind = "stream_interrupted"
    fallback_allowed = False

    def __init__(self, cause: LLMError):
        super().__init__(f"stream interrupted after content: {cause.kind}",
                         provider=cause.provider, model=cause.model)
        self.cause = cause


class ModelSelectionError(Exception):
    """La solicitud pide un modelo no permitido o no resoluble (error de validación)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
