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
