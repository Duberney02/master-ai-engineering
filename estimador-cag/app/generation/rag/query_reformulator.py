"""Comprensión de la consulta: de la transcripción cruda a un brief estructurado (Sesión 9).

Una transcripción no es una consulta: embeber cientos de tokens de digresiones produce un vector que promedia varias
intenciones y ruido, con distancias comprimidas y aciertos irrelevantes (fallo 1 de `arquitectura-actual.md`). Esta
etapa destila la transcripción en un `EstimationQuery` con la primitiva de generación estructurada del proyecto y
compone un texto de búsqueda corto, técnico y en inglés, alineado con el corpus.
"""

import structlog

from app.foundation.llm.structured import Generator, generate_structured
from app.foundation.prompts.loader import render_rag_template
from app.generation.rag.errors import ReformulationError
from app.generation.rag.schemas import EstimationQuery

logger = structlog.get_logger(__name__)

_MAX_TOKENS = 1000
_FALLBACK_MAX_TOKENS = 200
_FALLBACK_MAX_CHARS = 1000
_QUOTES = "\"'` "


def _messages(system: str, transcript: str) -> list[dict[str, str]]:
    user = render_rag_template("reformulation", "user", {"transcript": transcript})
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def reformulate_query(transcript: str, *, generate: Generator, model: str | None = None) -> EstimationQuery:
    """Brief estructurado de la transcripción.

    Si la extracción estructurada falla, degrada a una reescritura libre de una frase (solo `function`). Lanza
    `ReformulationError` si también falla el respaldo.
    """
    options: dict = {"max_tokens": _MAX_TOKENS}
    if model:
        options["model"] = model
    system = render_rag_template("reformulation", "system", {})
    try:
        query, _ = await generate_structured(generate, _messages(system, transcript), EstimationQuery, **options)
        return query
    except Exception as exc:
        logger.warning("rag_reformulation_fallback", error_type=type(exc).__name__)

    fallback = render_rag_template("reformulation", "fallback_system", {})
    try:
        completion = await generate(_messages(fallback, transcript), **{**options, "max_tokens": _FALLBACK_MAX_TOKENS})
    except Exception as exc:
        raise ReformulationError("query reformulation failed") from exc
    rewritten = " ".join((completion.text or "").split()).strip(_QUOTES)[:_FALLBACK_MAX_CHARS]
    if not rewritten:
        raise ReformulationError("fallback rewrite returned an empty query")
    return EstimationQuery(function=rewritten)


def compose_search_text(query: EstimationQuery) -> str:
    """Texto canónico que se embebe, p. ej. «Payments marketplace with Stripe for finance in DE, PSD2-compliant».

    Une los campos con evidencia en una frase alineada con el corpus; los vacíos se omiten.
    """
    parts = [query.function.strip()] if query.function.strip() else []
    if query.technologies:
        parts.append("with " + ", ".join(query.technologies))
    if query.sector:
        parts.append(f"for {query.sector}")
    if query.country:
        parts.append(f"in {query.country}")
    if query.regulations:
        parts.append(", ".join(query.regulations) + "-compliant")
    return " ".join(parts).strip()
