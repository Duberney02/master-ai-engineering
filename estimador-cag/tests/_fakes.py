"""Utilidades compartidas: respuestas falsas de los SDK y parcheo de clientes/ajustes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.config import Settings

LONG_TRANSCRIPTION = "Transcripción suficientemente larga para ser válida en el test"


def openai_settings(**kw) -> Settings:
    return Settings(llm_provider="openai", openai_api_key="sk-test", _env_file=None, **kw)


def anthropic_settings(**kw) -> Settings:
    return Settings(llm_provider="anthropic", anthropic_api_key="sk-ant-test", _env_file=None, **kw)


def openai_response(
    text: str,
    *,
    finish_reason: str = "stop",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    model: str = "gpt-4o-mini",
):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=text), finish_reason=finish_reason)
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
        model=model,
    )


def anthropic_response(
    text: str,
    *,
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 50,
    model: str = "claude-haiku-4-5",
    extra_blocks: tuple = (),
):
    return SimpleNamespace(
        content=[*extra_blocks, SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason=stop_reason,
        model=model,
    )


def patch_settings(mocker, settings: Settings) -> None:
    mocker.patch("app.services.llm_service.get_settings", return_value=settings)


def patch_openai(mocker, *outcomes) -> AsyncMock:
    """Parchea AsyncOpenAI; cada llamada consume un resultado (respuesta o excepción)."""
    create = AsyncMock(side_effect=list(outcomes))
    client = MagicMock()
    client.chat.completions.create = create
    mocker.patch("app.services.llm_service.AsyncOpenAI", return_value=client)
    return create


def patch_anthropic(mocker, *outcomes) -> AsyncMock:
    create = AsyncMock(side_effect=list(outcomes))
    client = MagicMock()
    client.messages.create = create
    mocker.patch("app.services.llm_service.AsyncAnthropic", return_value=client)
    return create


class _AsyncIterFromList:
    def __init__(self, items: list):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


def openai_stream_chunks(
    deltas: list[str],
    *,
    model: str = "gpt-4o-mini",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> list:
    """Fake ChatCompletionChunk sequence: one chunk per delta, then a final usage-only chunk."""
    chunks = [
        SimpleNamespace(
            model=model,
            choices=[SimpleNamespace(delta=SimpleNamespace(content=d), finish_reason=None)],
            usage=None,
        )
        for d in deltas
    ]
    chunks.append(
        SimpleNamespace(
            model=model,
            choices=[],
            usage=SimpleNamespace(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )
    )
    return chunks


def patch_openai_stream(mocker, chunks: list) -> AsyncMock:
    """Parchea AsyncOpenAI para que `create(..., stream=True)` devuelva un stream fake."""
    create = AsyncMock(return_value=_AsyncIterFromList(chunks))
    client = MagicMock()
    client.chat.completions.create = create
    mocker.patch("app.services.llm_service.AsyncOpenAI", return_value=client)
    return create


def anthropic_final_message(
    text: str,
    *,
    model: str = "claude-haiku-4-5",
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 50,
):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason=stop_reason,
        model=model,
    )


class _FakeAnthropicStream:
    def __init__(self, deltas: list[str], final_message):
        self._deltas = deltas
        self._final_message = final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    @property
    def text_stream(self):
        return _AsyncIterFromList(list(self._deltas))

    async def get_final_message(self):
        return self._final_message


def patch_anthropic_stream(mocker, deltas: list[str], final_message) -> MagicMock:
    """Parchea AsyncAnthropic para que `messages.stream(...)` devuelva un context manager fake."""
    client = MagicMock()
    client.messages.stream = MagicMock(return_value=_FakeAnthropicStream(deltas, final_message))
    mocker.patch("app.services.llm_service.AsyncAnthropic", return_value=client)
    return client
