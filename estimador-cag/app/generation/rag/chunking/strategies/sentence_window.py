"""Ventana de frases: se indexa cada frase y se guarda en los metadatos el contexto que la rodea.

La frase sola es lo que se embebe (unidad pequeña y precisa, buena para recuperar). En la recuperación, lo que
se entregaría al generador es `metadata.window_text` (±N frases), de modo que la unidad indexada y la devuelta
son distintas a propósito.
"""

import time

from app.generation.rag.chunking.base import Chunker, count_tokens
from app.generation.rag.chunking.sentences import split_sentences
from app.generation.rag.chunking.structural import component_metadata
from app.generation.rag.schemas import Budget, Chunk

# Frases de contexto que se conservan a cada lado de la frase indexada.
WINDOW_SIZE = 2


class SentenceWindowChunker(Chunker):
    strategy_name = "sentence_window"

    def __init__(self, window_size: int = WINDOW_SIZE) -> None:
        self._window = window_size

    async def chunk(self, budgets: list[Budget]) -> list[Chunk]:
        started = time.perf_counter()
        chunks: list[Chunk] = []
        for budget in budgets:
            for component in budget.components:
                sentences = split_sentences(component.description)
                for i, sentence in enumerate(sentences):
                    low = max(0, i - self._window)
                    high = min(len(sentences), i + self._window + 1)
                    chunks.append(
                        Chunk(
                            chunk_id=f"{budget.budget_id}::{component.component_id}::s{i}",
                            text=sentence,
                            metadata={
                                **component_metadata(budget, component),
                                "sentence_index": i,
                                "window_text": " ".join(sentences[low:high]),
                            },
                            token_count=count_tokens(sentence),
                        )
                    )
        return self._finish(chunks, budgets, started)
