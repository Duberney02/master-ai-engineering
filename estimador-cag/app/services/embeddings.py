"""Embeddings para la caché semántica (OpenAI; Anthropic no ofrece embeddings)."""

import inspect
from typing import Protocol

from openai import AsyncOpenAI

from app.config import Settings


class Embedder(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class OpenAIEmbedder:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def embed(self, text: str) -> list[float]:
        settings = self.settings
        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout,
                             max_retries=settings.llm_retries)
        try:
            response = await client.embeddings.create(
                model=settings.embedding_model, input=text,
                dimensions=settings.embedding_dimensions,
            )
            return list(response.data[0].embedding)
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                result = close()
                if inspect.isawaitable(result):
                    await result


def embeddings_available(settings: Settings) -> bool:
    return bool(settings.openai_api_key)
