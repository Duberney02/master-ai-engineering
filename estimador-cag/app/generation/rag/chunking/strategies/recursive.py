"""Troceo recursivo por separadores naturales: el valor por defecto razonable.

Divide cada presupuesto serializado con una jerarquía de separadores (párrafo → línea → frase → palabra) y
solo baja a uno más fino cuando una pieza sigue siendo demasiado grande. El tamaño se mide en tokens, igual
que en el resto de estrategias. Implementación propia: evita la dependencia de LangChain.
"""

import time

from app.generation.rag.chunking.base import Chunker, count_tokens, decode, encode
from app.generation.rag.chunking.structural import budget_metadata, serialize_budget
from app.generation.rag.schemas import Budget, Chunk

CHUNK_SIZE_TOKENS = 512
OVERLAP_TOKENS = 80
# De grueso a fino: primero líneas en blanco, luego líneas, frases y espacios; "" parte por tokens.
SEPARATORS = ("\n\n", "\n", ". ", " ", "")


def _split_by_tokens(text: str, size: int, overlap: int) -> list[str]:
    tokens = encode(text)
    step = size - overlap
    return [decode(tokens[start : start + size]) for start in range(0, len(tokens), step)]


def recursive_split(
    text: str,
    size: int = CHUNK_SIZE_TOKENS,
    overlap: int = OVERLAP_TOKENS,
    separators: tuple[str, ...] = SEPARATORS,
) -> list[str]:
    if count_tokens(text) <= size:
        return [text]
    index = next((i for i, sep in enumerate(separators) if sep == "" or sep in text), len(separators) - 1)
    separator = separators[index]
    if separator == "":
        return _split_by_tokens(text, size, overlap)
    pieces: list[str] = []
    for part in text.split(separator):
        if not part.strip():
            continue
        if count_tokens(part) > size:
            pieces.extend(recursive_split(part, size, overlap, separators[index + 1 :]))
        else:
            pieces.append(part)
    return _merge(pieces, separator, size, overlap)


def _merge(pieces: list[str], separator: str, size: int, overlap: int) -> list[str]:
    """Junta piezas consecutivas hasta `size` tokens; cada trozo nuevo arrastra la cola del anterior."""
    chunks: list[str] = []
    window: list[str] = []
    for piece in pieces:
        if window and count_tokens(separator.join([*window, piece])) > size:
            chunks.append(separator.join(window))
            while window and (
                count_tokens(separator.join(window)) > overlap or count_tokens(separator.join([*window, piece])) > size
            ):
                window.pop(0)
        window.append(piece)
    if window:
        chunks.append(separator.join(window))
    return [chunk.strip() for chunk in chunks if chunk.strip()]


class RecursiveChunker(Chunker):
    strategy_name = "recursive"

    def __init__(self, size: int = CHUNK_SIZE_TOKENS, overlap: int = OVERLAP_TOKENS) -> None:
        if not 0 <= overlap < size:
            raise ValueError("overlap must be >= 0 and smaller than size")
        self._size = size
        self._overlap = overlap

    async def chunk(self, budgets: list[Budget]) -> list[Chunk]:
        started = time.perf_counter()
        chunks: list[Chunk] = []
        for budget in budgets:
            for i, piece in enumerate(recursive_split(serialize_budget(budget), self._size, self._overlap)):
                chunks.append(
                    Chunk(
                        chunk_id=f"{budget.budget_id}::r{i}",
                        text=piece,
                        metadata={**budget_metadata(budget), "part": i},
                        token_count=count_tokens(piece),
                    )
                )
        return self._finish(chunks, budgets, started)
