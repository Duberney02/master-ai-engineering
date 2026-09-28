import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)

from app.llm.errors import (
    LLMAuthError,
    LLMError,
    LLMInvalidRequestError,
    LLMProviderError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.llm.providers.base import finish_reason_or_unknown, int_or_none
from app.llm.types import LLMRequest, ProviderCompletion, ProviderDelta, ProviderStreamEnd

logger = logging.getLogger(__name__)

# Temperatura que ya usaba el servicio con OpenAI (se conserva el comportamiento).
OPENAI_TEMPERATURE = 0.3


def translate_openai_error(exc: Exception, model: str) -> LLMError:
    """SDK → LLMError. El mensaje original (puede contener datos internos) no se propaga."""
    kw = {"provider": "openai", "model": model}
    if isinstance(exc, LLMError):
        return exc
    if isinstance(exc, APITimeoutError):  # subclase de APIConnectionError: va primero
        return LLMTimeoutError(**kw)
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return LLMAuthError(**kw)
    if isinstance(exc, RateLimitError):
        return LLMRateLimitError(**kw)
    if isinstance(exc, (BadRequestError, NotFoundError, UnprocessableEntityError)):
        return LLMInvalidRequestError(type(exc).__name__, **kw)
    if isinstance(exc, APIConnectionError):
        return LLMUnavailableError(type(exc).__name__, **kw)
    if isinstance(exc, APIStatusError) and exc.status_code >= 500:
        return LLMUnavailableError(f"status {exc.status_code}", **kw)
    return LLMProviderError(type(exc).__name__, **kw)


class OpenAIAdapter:
    name = "openai"

    def __init__(self, client: AsyncOpenAI):
        self._client = client

    @classmethod
    def from_api_key(cls, api_key: str, timeout: float) -> "OpenAIAdapter":
        # Reintentos desactivados en el SDK: la política la aplica LLMClient.
        return cls(AsyncOpenAI(api_key=api_key, timeout=timeout, max_retries=0))

    def generation_params(self) -> dict[str, Any]:
        return {"temperature": OPENAI_TEMPERATURE}

    def _kwargs(self, model: str, request: LLMRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "temperature": OPENAI_TEMPERATURE,
        }
        if request.max_tokens is not None:
            kwargs["max_completion_tokens"] = request.max_tokens
        return kwargs

    async def complete(self, model: str, request: LLMRequest) -> ProviderCompletion:
        try:
            response = await self._client.chat.completions.create(**self._kwargs(model, request))
        except Exception as exc:
            raise translate_openai_error(exc, model) from None

        choice = response.choices[0] if response.choices else None
        text = (choice.message.content if choice else None) or ""
        usage = getattr(response, "usage", None)
        return ProviderCompletion(
            text=text,
            model=getattr(response, "model", None) or None,
            finish_reason=finish_reason_or_unknown(getattr(choice, "finish_reason", None)),
            input_tokens=int_or_none(getattr(usage, "prompt_tokens", None)),
            output_tokens=int_or_none(getattr(usage, "completion_tokens", None)),
        )

    async def stream(
        self, model: str, request: LLMRequest
    ) -> AsyncIterator[ProviderDelta | ProviderStreamEnd]:
        reported_model: str | None = None
        finish_reason = "unknown"
        input_tokens: int | None = None
        output_tokens: int | None = None
        stream = None
        try:
            stream = await self._client.chat.completions.create(
                **self._kwargs(model, request),
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in stream:
                reported_model = getattr(chunk, "model", None) or reported_model
                if chunk.choices:
                    choice = chunk.choices[0]
                    delta = getattr(choice.delta, "content", None)
                    if delta:
                        yield ProviderDelta(delta)
                    if getattr(choice, "finish_reason", None):
                        finish_reason = choice.finish_reason
                usage = getattr(chunk, "usage", None)
                if usage:
                    input_tokens = int_or_none(getattr(usage, "prompt_tokens", None))
                    output_tokens = int_or_none(getattr(usage, "completion_tokens", None))
        except Exception as exc:
            raise translate_openai_error(exc, model) from None
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # noqa: BLE001 - cierre best-effort
                    logger.debug("openai stream close failed", exc_info=False)
        yield ProviderStreamEnd(
            model=reported_model,
            finish_reason=finish_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def aclose(self) -> None:
        await self._client.close()
