"""Interfaz común de las estrategias de chunking.

Todas implementan `Chunker`, de modo que son intercambiables en el framework de comparación. Los helpers de
este módulo garantizan que el conteo de tokens y el evento de log `chunking_done` sean idénticos en todas.
"""

import time
from abc import ABC, abstractmethod

import structlog
import tiktoken

from app.generation.rag.schemas import Budget, Chunk

logger = structlog.get_logger(__name__)

# Todas las estrategias cuentan tokens con el tokenizador del modelo de embeddings (cl100k_base, el de
# `text-embedding-3-*`), para que las estadísticas sean comparables entre ellas.
_ENCODING = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


def encode(text: str) -> list[int]:
    return _ENCODING.encode(text)


def decode(tokens: list[int]) -> str:
    return _ENCODING.decode(tokens)


def emit_chunking_done(
    *,
    strategy: str,
    chunks: list[Chunk],
    n_input_documents: int,
    started: float,
    extra_api_calls: int = 0,
    extra_cost_usd: float = 0.0,
) -> None:
    """Evento uniforme de fin de chunking. `started` es un `time.perf_counter()` tomado al empezar."""
    logger.info(
        "chunking_done",
        strategy=strategy,
        n_chunks=len(chunks),
        n_input_documents=n_input_documents,
        extra_api_calls=extra_api_calls,
        extra_cost_usd=round(extra_cost_usd, 6),
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
    )


class Chunker(ABC):
    """Una estrategia de chunking: presupuestos de entrada, chunks de salida.

    Tras cada `chunk()` la estrategia deja en `last_extra_api_calls` y `last_extra_cost_usd` las llamadas y el
    coste adicionales de la ingesta (LLM o embeddings durante el chunking). Las que no llaman a ninguna API
    los dejan en cero.
    """

    last_extra_api_calls: int = 0
    last_extra_cost_usd: float = 0.0

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """Identificador estable, usado en logs, en la API y en el framework de comparación."""

    @abstractmethod
    async def chunk(self, budgets: list[Budget]) -> list[Chunk]: ...

    def _finish(
        self,
        chunks: list[Chunk],
        budgets: list[Budget],
        started: float,
        *,
        extra_api_calls: int = 0,
        extra_cost_usd: float = 0.0,
    ) -> list[Chunk]:
        self.last_extra_api_calls = extra_api_calls
        self.last_extra_cost_usd = extra_cost_usd
        emit_chunking_done(
            strategy=self.strategy_name,
            chunks=chunks,
            n_input_documents=len(budgets),
            started=started,
            extra_api_calls=extra_api_calls,
            extra_cost_usd=extra_cost_usd,
        )
        return chunks
