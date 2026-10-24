"""Ventana de tamaño fijo con solapamiento: la línea base degenerada.

Serializa cada componente y desliza una ventana de tokens ignorando cualquier frontera natural (frase,
componente, estructura JSON); sirve de suelo con el que comparar el resto.
"""

import time

from app.generation.rag.chunking.base import Chunker, decode, encode
from app.generation.rag.chunking.structural import component_metadata, render_component_text
from app.generation.rag.schemas import Budget, Chunk

# Geometría de la ventana, en tokens. Valores de partida: son los únicos parámetros de la estrategia.
CHUNK_SIZE_TOKENS = 512
OVERLAP_TOKENS = 80


class FixedSizeChunker(Chunker):
    strategy_name = "fixed_size"

    def __init__(self, size: int = CHUNK_SIZE_TOKENS, overlap: int = OVERLAP_TOKENS) -> None:
        if not 0 <= overlap < size:
            raise ValueError("overlap must be >= 0 and smaller than size")
        self._size = size
        self._overlap = overlap

    async def chunk(self, budgets: list[Budget]) -> list[Chunk]:
        started = time.perf_counter()
        step = self._size - self._overlap
        chunks: list[Chunk] = []
        for budget in budgets:
            for component in budget.components:
                tokens = encode(render_component_text(budget, component))
                for part, start in enumerate(range(0, len(tokens), step)):
                    window = tokens[start : start + self._size]
                    chunks.append(
                        Chunk(
                            chunk_id=f"{budget.budget_id}::{component.component_id}::p{part}",
                            text=decode(window),
                            metadata={**component_metadata(budget, component), "part": part},
                            token_count=len(window),
                        )
                    )
                    if start + self._size >= len(tokens):
                        break
        return self._finish(chunks, budgets, started)
