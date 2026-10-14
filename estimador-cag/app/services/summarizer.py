"""Resumidor acumulativo: combina el resumen anterior con los turnos que salen de la ventana."""

from typing import Protocol

from app.config import Settings
from app.prompts.loader import render_auxiliary_prompt
from app.services.context import SUMMARY_MAX_CHARS, clean_summary
from app.services.llm_service import generate_from_messages
from app.services.llm_wrapper import Completion
from app.services.structured import Generator

# Texto de cada mensaje y de la entrada completa que ve el resumidor (los turnos pueden ser enormes).
_USER_CHARS = 4000
_ASSISTANT_CHARS = 2500
_SUMMARY_MAX_TOKENS = 900


class Summarizer(Protocol):
    async def summarize(self, previous: str, turns: list[tuple[str, str]]) -> tuple[str, list[Completion]]:
        """Nuevo resumen (ya normalizado) y las completions consumidas. Puede lanzar excepciones."""
        ...


class LLMSummarizer:
    def __init__(self, settings: Settings, *, generate: Generator = generate_from_messages):
        self.settings = settings
        self._generate = generate

    async def summarize(self, previous: str, turns: list[tuple[str, str]]) -> tuple[str, list[Completion]]:
        system, user = render_auxiliary_prompt(
            "summary",
            {
                "previous_summary": previous,
                "turns": [{"user": u[:_USER_CHARS], "assistant": a[:_ASSISTANT_CHARS]} for u, a in turns],
                "max_chars": SUMMARY_MAX_CHARS,
            },
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        options: dict = {"max_tokens": _SUMMARY_MAX_TOKENS}
        if self.settings.summary_model:
            options["model"] = self.settings.summary_model
        completion = await self._generate(messages, **options)
        return clean_summary(completion.text), [completion]
