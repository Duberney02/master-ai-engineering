"""Ensamblado del contexto: chunks recuperados → bloque de fuentes delimitado (Sesión 9).

Evita dos antipatrones:

* Unir los chunks con saltos de línea: el modelo no sabe dónde acaba una fuente ni qué id citar. Cada chunk va en
  un elemento `<source>` con su `id` y metadatos, de modo que cada afirmación puede citar una fuente concreta.
* Partir un chunk cuando el contexto no cabe: `truncate_to_token_budget` descarta chunks COMPLETOS desde la cola (los
  menos relevantes). Media línea de presupuesto es peor que una línea menos.
"""

from app.generation.rag.chunking.base import count_tokens
from app.generation.rag.schemas import RetrievedChunk

_ATTRIBUTE_ESCAPES = str.maketrans({"&": "&amp;", '"': "&quot;", "<": "&lt;", ">": "&gt;"})


def _attribute(value: object) -> str:
    return str(value).translate(_ATTRIBUTE_ESCAPES)


def wrap_chunk(chunk: RetrievedChunk) -> str:
    """Un chunk como elemento `<source>` autodescriptivo; `id` es lo que cita la estimación."""
    # Un `</source>` dentro del contenido cerraría el elemento antes de tiempo.
    content = chunk.content.replace("</source>", "&lt;/source&gt;")
    return (
        f'<source id="{chunk.id}" budget_id="{_attribute(chunk.budget_id or "unknown")}" '
        f'sector="{_attribute(chunk.sector)}" project_year="{chunk.project_year}" '
        f'chunk_type="{_attribute(chunk.chunk_type)}" distance="{chunk.distance:.4f}">\n'
        f"{content}\n"
        "</source>"
    )


def build_context_block(chunks: list[RetrievedChunk]) -> str:
    """Bloque de fuentes, de la más relevante a la menos (el retriever ya las ordena por distancia)."""
    return "\n".join(wrap_chunk(chunk) for chunk in chunks)


def truncate_to_token_budget(chunks: list[RetrievedChunk], max_context_tokens: int) -> list[RetrievedChunk]:
    """Los chunks iniciales que caben en `max_context_tokens`, contados YA envueltos en `<source>`.

    Los delimitadores son tokens reales que ve el modelo. El primer chunk que desborda detiene el bucle y ningún
    chunk se parte.
    """
    kept: list[RetrievedChunk] = []
    used = 0
    for chunk in chunks:
        # +1: el salto de línea que separa las fuentes en el bloque.
        cost = count_tokens(wrap_chunk(chunk)) + (1 if kept else 0)
        if used + cost > max_context_tokens:
            break
        kept.append(chunk)
        used += cost
    return kept
