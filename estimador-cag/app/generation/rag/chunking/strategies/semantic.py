"""Chunking semántico: corta donde cae la similitud entre frases consecutivas.

Embebe cada frase (junto a sus vecinas inmediatas, para suavizar el ruido) y marca un corte donde la distancia
coseno con la siguiente supera un percentil del propio documento. Su coste es que embebe durante la *ingesta*
—aproximadamente una pasada extra de embeddings sobre todo el corpus— antes de atender una sola consulta; ese
coste se reporta. Implementación propia sobre el embedder del proyecto: evita LangChain y se prueba con un
embedder falso.
"""

import math
import time
from typing import Protocol

from app.generation.rag.analysis.similarity import cosine_similarity, percentile
from app.generation.rag.chunking.base import Chunker, count_tokens
from app.generation.rag.chunking.pricing import embedding_cost_usd
from app.generation.rag.chunking.sentences import split_sentences
from app.generation.rag.chunking.structural import budget_metadata, serialize_budget
from app.generation.rag.embedding.embedder import BATCH_SIZE
from app.generation.rag.schemas import Budget, Chunk

# Percentil de las distancias a partir del cual se corta: 95 = solo los cambios de tema más marcados.
BREAKPOINT_PERCENTILE = 95
# Frases vecinas que se agregan a cada lado antes de embeber.
BUFFER_SIZE = 1


class TextEmbedder(Protocol):
    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class SemanticChunker(Chunker):
    strategy_name = "semantic"

    def __init__(
        self,
        embedder: TextEmbedder,
        breakpoint_percentile: float = BREAKPOINT_PERCENTILE,
        buffer_size: int = BUFFER_SIZE,
    ) -> None:
        self._embedder = embedder
        self._percentile = breakpoint_percentile
        self._buffer = buffer_size

    async def chunk(self, budgets: list[Budget]) -> list[Chunk]:
        started = time.perf_counter()
        chunks: list[Chunk] = []
        extra_calls = 0
        extra_tokens = 0
        for budget in budgets:
            sentences = split_sentences(serialize_budget(budget))
            groups = [sentences]
            if len(sentences) > 1:
                combined = [
                    " ".join(sentences[max(0, i - self._buffer) : i + self._buffer + 1]) for i in range(len(sentences))
                ]
                vectors = await self._embedder.embed_texts(combined)
                extra_calls += math.ceil(len(combined) / BATCH_SIZE)
                extra_tokens += sum(count_tokens(text) for text in combined)
                groups = self._group(sentences, vectors)
            for i, group in enumerate(groups):
                text = " ".join(group)
                chunks.append(
                    Chunk(
                        chunk_id=f"{budget.budget_id}::sem{i}",
                        text=text,
                        metadata={**budget_metadata(budget), "part": i},
                        token_count=count_tokens(text),
                    )
                )
        return self._finish(
            chunks, budgets, started, extra_api_calls=extra_calls, extra_cost_usd=embedding_cost_usd(extra_tokens)
        )

    def _group(self, sentences: list[str], vectors: list[list[float]]) -> list[list[str]]:
        distances = [1 - cosine_similarity(vectors[i], vectors[i + 1]) for i in range(len(vectors) - 1)]
        threshold = percentile(distances, self._percentile)
        groups: list[list[str]] = [[sentences[0]]]
        for i, distance in enumerate(distances):
            if distance > threshold:
                groups.append([])
            groups[-1].append(sentences[i + 1])
        return groups
