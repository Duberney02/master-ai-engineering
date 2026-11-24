"""*Routing* multi-índice en cascada de coste creciente (Sesión 10).

El corpus es heterogéneo: buscar en todas las colecciones en cada consulta deja que el tipo dominante inunde el top-k.
El *router* decide EN QUÉ colecciones buscar y resuelve por orden; gana la señal más barata que baste:

0. **Explícito**: la petición nombra las colecciones. El mejor router es no tener router: si el cliente lo sabe, se
   confía y no se clasifica nada.
1. **Reglas**: patrones de vocabulario deterministas (`collections.match_rules`). Una consulta que dice «budget», «cost»
   u «hours» quiere presupuestos; no hace falta un LLM.
2. **Clasificador**: un LLM con salida estructurada emite de 1 a `max_targets` destinos y un motivo de una frase. La
   ambigüedad se modela como VARIOS destinos, nunca con un umbral de confianza.
3. **Respaldo**: buscar en todas las colecciones en paralelo. Degradación elegante: nunca peor que el mundo de un solo
   índice del que partimos.

Cada decisión se registra con su nivel y su motivo (atribuir, auditar, depurar). Es un precursor deliberadamente
acotado de la delegación agéntica: una clasificación cerrada, sin razonamiento abierto ni herramientas.
"""

from dataclasses import dataclass
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from app.foundation.llm.structured import Generator, generate_structured
from app.foundation.prompts.loader import render_rag_template
from app.generation.rag.retrieval.collections import ALL_COLLECTIONS, Collection, match_rules

logger = structlog.get_logger(__name__)

RoutingLevel = Literal["explicit", "rules", "classifier", "fallback"]

_CLASSIFIER_MAX_TOKENS = 500


class RouteClassification(BaseModel):
    """Salida estructurada del clasificador: conjunto cerrado de destinos, de 1 a 3."""

    targets: list[Collection] = Field(
        min_length=1,
        max_length=3,
        description="Colecciones donde buscar: una por tipo de fuente relevante; la ambigüedad son varios destinos.",
    )
    reason: str = Field(min_length=1, description="Una frase que justifica la elección.")


@dataclass(frozen=True)
class RoutingDecision:
    """Dónde se enruta la consulta y cómo se decidió."""

    targets: list[Collection]
    level: RoutingLevel
    reason: str


def _decided(targets: list[Collection], level: RoutingLevel, reason: str) -> RoutingDecision:
    logger.info("routing_decided", level=level, targets=[target.value for target in targets], reason=reason)
    return RoutingDecision(targets, level, reason)


async def route(
    query_text: str,
    *,
    generate: Generator,
    explicit: list[Collection] | None = None,
    enabled: bool = True,
    max_targets: int = 3,
    model: str | None = None,
) -> RoutingDecision:
    """Resuelve las colecciones destino por la cascada descrita arriba.

    `explicit` se respeta siempre, incluso con el *routing* deshabilitado: es el contrato del cliente. Con el *routing*
    deshabilitado, o si el clasificador falla, el resultado es el nivel `fallback` (todas las colecciones).
    """
    if explicit:
        targets = list(dict.fromkeys(explicit))[:max_targets]
        return _decided(targets, "explicit", "La petición indicó las colecciones.")

    if enabled:
        hits = match_rules(query_text)
        if hits:
            targets = hits[:max_targets]
            return _decided(targets, "rules", f"El vocabulario coincide con: {', '.join(t.value for t in targets)}.")

        try:
            classification = await _classify(query_text, generate=generate, max_targets=max_targets, model=model)
        except Exception as exc:
            logger.warning("routing_classifier_failed", error_type=type(exc).__name__)
        else:
            targets = list(dict.fromkeys(classification.targets))[:max_targets]
            return _decided(targets, "classifier", classification.reason)

    reason = (
        "Sin señal de reglas ni del clasificador; se busca en todas las colecciones."
        if enabled
        else "Routing deshabilitado; se busca en todas las colecciones."
    )
    return _decided(list(ALL_COLLECTIONS), "fallback", reason)


async def _classify(
    query_text: str, *, generate: Generator, max_targets: int, model: str | None
) -> RouteClassification:
    messages = [
        {"role": "system", "content": render_rag_template("routing", "system", {"max_targets": max_targets})},
        {"role": "user", "content": render_rag_template("routing", "user", {"query": query_text})},
    ]
    options: dict = {"max_tokens": _CLASSIFIER_MAX_TOKENS}
    if model:
        options["model"] = model
    classification, _ = await generate_structured(generate, messages, RouteClassification, **options)
    return classification
