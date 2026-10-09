"""Conversaciones multi-turno hacia los proveedores (SDK simulados)."""

import json

import pytest

from app.services.llm_service import generate_from_messages
from tests._fakes import (
    anthropic_response,
    anthropic_settings,
    openai_response,
    openai_settings,
    patch_anthropic,
    patch_openai,
    patch_settings,
)

MESSAGES = [
    {"role": "system", "content": "SISTEMA"},
    {"role": "user", "content": "u1"},
    {"role": "assistant", "content": "a1"},
    {"role": "user", "content": "u2"},
]


async def test_openai_receives_system_and_every_turn(mocker):
    patch_settings(mocker, openai_settings(moderation_enabled=False))
    create = patch_openai(mocker, openai_response("respuesta"))

    completion = await generate_from_messages(MESSAGES)

    assert create.await_args.kwargs["messages"] == MESSAGES
    assert completion.text == "respuesta" and completion.provider == "openai"


async def test_anthropic_receives_system_parameter_and_the_rest_as_messages(mocker):
    patch_settings(mocker, anthropic_settings())
    create = patch_anthropic(mocker, anthropic_response("respuesta"))

    await generate_from_messages(MESSAGES)

    kwargs = create.await_args.kwargs
    assert kwargs["system"] == "SISTEMA" and kwargs["messages"] == MESSAGES[1:]


async def test_max_tokens_is_forwarded(mocker):
    patch_settings(mocker, openai_settings(moderation_enabled=False))
    create = patch_openai(mocker, openai_response("x"))

    await generate_from_messages(MESSAGES, max_tokens=800)

    assert create.await_args.kwargs["max_completion_tokens"] == 800


@pytest.mark.parametrize("bad", [[], [{"role": "system", "content": "s"}], MESSAGES[1:]])
async def test_requires_a_system_message_followed_by_a_turn(bad):
    with pytest.raises(ValueError):
        await generate_from_messages(bad)


async def test_completion_cache_key_depends_on_the_whole_conversation(mocker):
    from app.services.llm_wrapper import LLMWrapper

    wrapper = LLMWrapper(openai_settings(moderation_enabled=False))

    def key(turns):
        return wrapper.key("S", turns, "gpt-4o-mini", None, None, True)

    one = [{"role": "user", "content": "u"}]
    two = [{"role": "user", "content": "otro"}, {"role": "assistant", "content": "a"}, *one]
    assert key(one) != key(two) and key(two) == key(list(two))
    assert key("u") != key(one)
    json.dumps(two)  # la clave se serializa con json: la lista debe ser serializable
