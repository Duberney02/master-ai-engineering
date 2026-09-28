from collections.abc import AsyncIterator
from typing import Any

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
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

# Límite de salida cuando la solicitud no indica uno (Anthropic lo exige).
ANTHROPIC_DEFAULT_MAX_TOKENS = 4096


def translate_anthropic_error(exc: Exception, model: str) -> LLMError:
    kw = {"provider": "anthropic", "model": model}
    if isinstance(exc, LLMError):
        return exc
    if isinstance(exc, APITimeoutError):
        return LLMTimeoutError(**kw)
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return LLMAuthError(**kw)
    if isinstance(exc, RateLimitError):
        return LLMRateLimitError(**kw)
    if isinstance(exc, (BadRequestError, NotFoundError, UnprocessableEntityError)):
        return LLMInvalidRequestError(type(exc).__name__, **kw)
    if isinstance(exc, APIConnectionError):
        return LLMUnavailableError(type(exc).__name__, **kw)
    if isinstance(exc, APIStatusError) and exc.status_code >= 500:  # incluye 529 overloaded
        return LLMUnavailableError(f"status {exc.status_code}", **kw)
    return LLMProviderError(type(exc).__name__, **kw)


def _text_of(message: Any) -> str:
    # El contenido puede mezclar bloques (p. ej. de razonamiento): solo cuentan los de texto.
    blocks = getattr(message, "content", None) or []
    return "".join(b.text for b in blocks if isinstance(getattr(b, "text", None), str))


class AnthropicAdapter:
    name = "anthropic"

    def __init__(self, client: AsyncAnthropic):
        self._client = client

    @classmethod
    def from_api_key(cls, api_key: str, timeout: float) -> "AnthropicAdapter":
        return cls(AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=0))

    def generation_params(self) -> dict[str, Any]:
        return {"default_max_tokens": ANTHROPIC_DEFAULT_MAX_TOKENS}

    def _kwargs(self, model: str, request: LLMRequest) -> dict[str, Any]:
        return {
            "model": model,
            "max_tokens": request.max_tokens or ANTHROPIC_DEFAULT_MAX_TOKENS,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
        }

    async def complete(self, model: str, request: LLMRequest) -> ProviderCompletion:
        try:
            response = await self._client.messages.create(**self._kwargs(model, request))
        except Exception as exc:
            raise translate_anthropic_error(exc, model) from None
        usage = getattr(response, "usage", None)
        return ProviderCompletion(
            text=_text_of(response),
            model=getattr(response, "model", None) or None,
            finish_reason=finish_reason_or_unknown(getattr(response, "stop_reason", None)),
            input_tokens=int_or_none(getattr(usage, "input_tokens", None)),
            output_tokens=int_or_none(getattr(usage, "output_tokens", None)),
        )

    async def stream(
        self, model: str, request: LLMRequest
    ) -> AsyncIterator[ProviderDelta | ProviderStreamEnd]:
        try:
            async with self._client.messages.stream(**self._kwargs(model, request)) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield ProviderDelta(text)
                final = await stream.get_final_message()
        except Exception as exc:
            raise translate_anthropic_error(exc, model) from None
        usage = getattr(final, "usage", None)
        yield ProviderStreamEnd(
            model=getattr(final, "model", None) or None,
            finish_reason=finish_reason_or_unknown(getattr(final, "stop_reason", None)),
            input_tokens=int_or_none(getattr(usage, "input_tokens", None)),
            output_tokens=int_or_none(getattr(usage, "output_tokens", None)),
        )

    async def aclose(self) -> None:
        await self._client.close()
