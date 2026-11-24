"""Mensajes de la generación fundamentada (Sesión 9), con las plantillas de `foundation/prompts/rag/generation`.

El prompt de sistema fija la política de fundamentación: cada cifra sale de un `<source>`, los ids inventados están
prohibidos y, si el contexto no basta, el modelo lo dice con `confidence="insufficient"` en lugar de adivinar.
"""

from app.foundation.prompts.loader import render_rag_template
from app.generation.rag.schemas import EstimationQuery


def build_generation_messages(
    context_block: str, query: EstimationQuery, feedback: str | None = None
) -> list[dict[str, str]]:
    """`[system, user]`: el brief estructurado, el bloque `<sources>` y, en un reintento, la corrección."""
    system = render_rag_template("generation", "system", {})
    user = render_rag_template(
        "generation",
        "user",
        {"query": query.model_dump(mode="json"), "context_block": context_block, "feedback": feedback},
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
