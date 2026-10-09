"""Primitiva de generación estructurada con modelos Pydantic."""

import json

import pytest
from pydantic import BaseModel, Field

from app.services.llm_wrapper import Completion
from app.services.structured import StructuredOutputError, generate_structured


class Verdict(BaseModel):
    ok: bool
    score: int = Field(ge=0, le=10)


MESSAGES = [{"role": "system", "content": "Eres un revisor."}, {"role": "user", "content": "Revisa esto."}]


class Generator:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[tuple[list[dict], dict]] = []

    async def __call__(self, messages, accept=None, **options):
        self.calls.append((messages, options))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return Completion(text=text, model="m", provider="openai", input_tokens=10, output_tokens=5)


async def test_valid_answer_returns_the_model_and_the_completion():
    generate = Generator({"ok": True, "score": 7})

    verdict, completions = await generate_structured(generate, MESSAGES, Verdict)

    assert verdict == Verdict(ok=True, score=7) and len(completions) == 1
    assert generate.calls[0][0] == MESSAGES


async def test_json_inside_code_fences_and_prose_is_accepted():
    generate = Generator('Claro:\n```json\n{"ok": false, "score": 2}\n```')

    verdict, _ = await generate_structured(generate, MESSAGES, Verdict)

    assert verdict.score == 2 and verdict.ok is False


async def test_invalid_answer_is_retried_with_the_previous_answer_and_the_reason():
    generate = Generator({"ok": True, "score": 99}, {"ok": True, "score": 9})

    verdict, completions = await generate_structured(generate, MESSAGES, Verdict)

    assert verdict.score == 9 and len(completions) == 2
    retry = generate.calls[1][0]
    assert retry[:2] == MESSAGES
    assert retry[2]["role"] == "assistant" and '"score": 99' in retry[2]["content"]
    assert retry[3]["role"] == "user" and "score" in retry[3]["content"] and "Corrígela" in retry[3]["content"]


async def test_the_original_messages_are_not_modified_by_the_correction():
    generate = Generator("nada", {"ok": True, "score": 1})
    original = list(MESSAGES)

    await generate_structured(generate, MESSAGES, Verdict)

    assert MESSAGES == original


@pytest.mark.parametrize("answer", ["no es json", "[1, 2]", '{"ok": "quizá"}', "{truncado"])
async def test_attempts_exhausted_raise_a_structured_output_error(answer):
    generate = Generator(answer, answer)

    with pytest.raises(StructuredOutputError):
        await generate_structured(generate, MESSAGES, Verdict)

    assert len(generate.calls) == 2


async def test_attempts_are_configurable():
    generate = Generator("mal", "mal", {"ok": True, "score": 3})

    verdict, completions = await generate_structured(generate, MESSAGES, Verdict, attempts=3)

    assert verdict.score == 3 and len(completions) == 3


async def test_options_are_forwarded_to_the_generator_on_every_attempt():
    generate = Generator("mal", {"ok": True, "score": 3})

    await generate_structured(generate, MESSAGES, Verdict, model="gpt-6-sol", max_tokens=300)

    assert all(options == {"model": "gpt-6-sol", "max_tokens": 300} for _, options in generate.calls)


async def test_provider_errors_are_not_swallowed():
    generate = Generator(RuntimeError("proveedor caído"))

    with pytest.raises(RuntimeError, match="proveedor caído"):
        await generate_structured(generate, MESSAGES, Verdict)


async def test_the_acceptance_callback_given_to_the_generator_validates_the_schema():
    seen = {}

    async def generate(messages, accept=None, **options):
        seen["accept"] = accept
        return Completion(text='{"ok": true, "score": 4}', model="m", provider="openai")

    await generate_structured(generate, MESSAGES, Verdict)

    assert seen["accept"]('{"ok": true, "score": 4}') is True
    assert seen["accept"]('{"ok": true, "score": 40}') is False and seen["accept"]("basura") is False
