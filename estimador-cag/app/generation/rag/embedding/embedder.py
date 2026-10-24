"""Embeddings con OpenAI (`text-embedding-3-small`, 1536 dimensiones) por lotes y con reintentos ante límite de tasa."""

import time

import structlog
from openai import OpenAI, RateLimitError

from app.config import get_settings
from app.generation.rag.chunking.structural import EMBEDDING_MODEL
from app.generation.rag.schemas import Chunk, EmbeddedChunk

logger = structlog.get_logger(__name__)

# Tarifa de referencia: USD por millón de tokens de entrada. VARÍA CON EL TIEMPO: revisa la página de
# precios de OpenAI antes de fiarte del coste estimado (es una estimación, no la factura).
PRICE_PER_MILLION_TOKENS_USD = 0.02

BATCH_SIZE = 100
# Esperas antes de cada reintento ante RateLimitError (hasta tres reintentos).
RETRY_DELAYS_SECONDS = (1, 2, 4)


def estimate_cost_usd(total_tokens: int, price_per_million_tokens: float = PRICE_PER_MILLION_TOKENS_USD) -> float:
    return total_tokens / 1_000_000 * price_per_million_tokens


class OpenAIEmbedder:
    def __init__(self, client: OpenAI | None = None) -> None:
        self._client = client

    @property
    def client(self) -> OpenAI:
        # Perezoso: importar el módulo o construir el embedder no exige OPENAI_API_KEY.
        if self._client is None:
            settings = get_settings()
            # max_retries=0: los únicos reintentos son los de _create_with_retries, sin duplicarlos en el SDK.
            self._client = OpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout, max_retries=0)
        return self._client

    def embed_one(self, text: str) -> list[float]:
        return self._create_with_retries([text])[0]

    def embed_many(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        embedded: list[EmbeddedChunk] = []
        for batch_index, start in enumerate(range(0, len(chunks), BATCH_SIZE)):
            batch = chunks[start : start + BATCH_SIZE]
            started = time.perf_counter()
            vectors = self._create_with_retries([chunk.text for chunk in batch])
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

    def _create_with_retries(self, texts: list[str]) -> list[list[float]]:
        """Una llamada `embeddings.create`; hasta tres reintentos ante RateLimitError, otros errores se propagan."""
        for attempt, delay in enumerate((*RETRY_DELAYS_SECONDS, None), start=1):
            try:
                response = self.client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
                break
            except RateLimitError:
                if delay is None:
                    raise
                logger.warning("embedding_rate_limited", attempt=attempt, latency_ms=delay * 1000)
                time.sleep(delay)
        # El orden de `data` se ordena por `index` para garantizar la correspondencia texto-vector.
        ordered = sorted(response.data, key=lambda item: item.index)
        if len(ordered) != len(texts):
            raise ValueError(f"expected {len(texts)} embeddings, received {len(ordered)}")
        return [list(item.embedding) for item in ordered]
