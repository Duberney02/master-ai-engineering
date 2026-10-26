"""Embeddings con OpenAI por lotes, asíncronos y con reintentos ante límite de tasa.

Modelo y dimensión salen de `Settings` (`embedding_model`, `embedding_dimensions`) y pueden fijarse al construir
el embedder. Con `dimensions` menor que la nativa del modelo, OpenAI trunca el vector (Matryoshka) y lo
renormaliza, lo que permite comparar dimensiones sin cambiar de modelo.
"""

import asyncio
import time

import structlog
from openai import AsyncOpenAI, RateLimitError

from app.config import get_settings
from app.generation.rag.chunking.pricing import EMBEDDING_PRICE_PER_MILLION_USD
from app.generation.rag.schemas import Chunk, EmbeddedChunk

logger = structlog.get_logger(__name__)

# Tarifa de referencia: USD por millón de tokens de entrada. VARÍA CON EL TIEMPO: revisa la página de
# precios de OpenAI antes de fiarte del coste estimado (es una estimación, no la factura).
PRICE_PER_MILLION_TOKENS_USD = EMBEDDING_PRICE_PER_MILLION_USD

BATCH_SIZE = 100
# Esperas antes de cada reintento ante RateLimitError (hasta tres reintentos).
RETRY_DELAYS_SECONDS = (1, 2, 4)


def estimate_cost_usd(total_tokens: int, price_per_million_tokens: float = PRICE_PER_MILLION_TOKENS_USD) -> float:
    return total_tokens / 1_000_000 * price_per_million_tokens


class OpenAIEmbedder:
    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        *,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._dimensions = dimensions

    @property
    def model(self) -> str:
        return self._model or get_settings().embedding_model

    @property
    def dimensions(self) -> int:
        return self._dimensions or get_settings().embedding_dimensions

    @property
    def client(self) -> AsyncOpenAI:
        # Perezoso: importar el módulo o construir el embedder no exige OPENAI_API_KEY.
        if self._client is None:
            settings = get_settings()
            # max_retries=0: los únicos reintentos son los de _create_with_retries, sin duplicarlos en el SDK.
            self._client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout, max_retries=0)
        return self._client

    async def embed_one(self, text: str) -> list[float]:
        return (await self._create_with_retries([text]))[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Vectores de varios textos, en lotes y en el mismo orden de entrada."""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            vectors.extend(await self._create_with_retries(texts[start : start + BATCH_SIZE]))
        return vectors

    async def embed_many(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        embedded: list[EmbeddedChunk] = []
        for batch_index, start in enumerate(range(0, len(chunks), BATCH_SIZE)):
            batch = chunks[start : start + BATCH_SIZE]
            started = time.perf_counter()
            vectors = await self._create_with_retries([chunk.text for chunk in batch])
            logger.info(
                "embedding_batch_completed",
                batch_index=batch_index,
                chunks_count=len(batch),
                total_tokens=sum(chunk.token_count for chunk in batch),
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            pairs = zip(batch, vectors, strict=True)
            embedded.extend(EmbeddedChunk(**chunk.model_dump(), embedding=vector) for chunk, vector in pairs)
        return embedded

    async def _create_with_retries(self, texts: list[str]) -> list[list[float]]:
        """Una llamada `embeddings.create`; hasta tres reintentos ante RateLimitError, otros errores se propagan."""
        for attempt, delay in enumerate((*RETRY_DELAYS_SECONDS, None), start=1):
            try:
                response = await self.client.embeddings.create(
                    model=self.model, input=texts, dimensions=self.dimensions
                )
                break
            except RateLimitError:
                if delay is None:
                    raise
                logger.warning("embedding_rate_limited", attempt=attempt, latency_ms=delay * 1000)
                await asyncio.sleep(delay)
        # El orden de `data` se ordena por `index` para garantizar la correspondencia texto-vector.
        ordered = sorted(response.data, key=lambda item: item.index)
        if len(ordered) != len(texts):
            raise ValueError(f"expected {len(texts)} embeddings, received {len(ordered)}")
        return [list(item.embedding) for item in ordered]
