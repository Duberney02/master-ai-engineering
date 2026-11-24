"""Aumentación del contexto recuperado (Sesión 11): compresión extractiva y reordenación de bordes.

Ambas son funciones PURAS sin LLM y NO tocan los ids de los chunks (lo que cita la estimación):

* **Compresión extractiva**: de cada chunk se conservan solo las líneas con cifras o identificadores; el resto es
  relleno que gasta presupuesto de tokens sin respaldar ninguna cifra. Si ninguna línea califica, el chunk se deja
  intacto (un chunk vacío sería una fuente citable sin contenido).
* **Reordenación de bordes** (*lost-in-the-middle*): los modelos atienden mejor al principio y al final del contexto que
  al centro. Con los chunks de más a menos relevante, los más fuertes pasan a los extremos y los más débiles al medio.

Se ejecutan tras el truncado por tokens y antes del ensamblado (ver `GroundedEstimator.assemble`).
"""

import re

from app.generation.rag.schemas import RetrievedChunk

# Una cifra, o un identificador en mayúsculas con guion o subrayado (`BUD-12`, `KYC_V2`).
_FIGURE = re.compile(r"\d")
_IDENTIFIER = re.compile(r"\b[A-Z]{2,}(?:[-_][A-Z0-9]+)+\b")


def _is_informative(line: str) -> bool:
    return bool(_FIGURE.search(line) or _IDENTIFIER.search(line))


def compress_chunk(chunk: RetrievedChunk) -> RetrievedChunk:
    """El chunk reducido a sus líneas con cifras o identificadores; mismo `id` y metadatos."""
    kept = [line for line in chunk.content.splitlines() if _is_informative(line)]
    if not kept:
        return chunk
    return chunk.model_copy(update={"content": "\n".join(kept)})


def compress_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    return [compress_chunk(chunk) for chunk in chunks]


def reorder_edges(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Reordena de más a menos relevante (orden de entrada) a «fuertes en los bordes, débiles en el centro».

    Los chunks pares del ranking van delante, los impares detrás en orden inverso: el 1.º queda primero, el 2.º
    último, el 3.º segundo, el 4.º penúltimo… y el menos relevante cae en el centro.
    """
    front = chunks[0::2]
    back = chunks[1::2]
    return [*front, *reversed(back)]


def augment_chunks(
    chunks: list[RetrievedChunk], *, compress: bool = True, reorder: bool = True
) -> list[RetrievedChunk]:
    """Aplica la compresión y luego la reordenación (la compresión no cambia el orden ni los ids)."""
    result = compress_chunks(chunks) if compress else list(chunks)
    return reorder_edges(result) if reorder else result
