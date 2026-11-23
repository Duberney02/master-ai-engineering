"""Expansión y descomposición de consultas (Sesión 10).

Dos técnicas DISTINTAS que no son intercambiables; la pregunta que las separa es *¿una cosa dicha de varias formas, o
varias cosas dichas a la vez?*

* **Expansión (multi-query)**: N reformulaciones de la MISMA intención. Combate la lotería de la formulación (que el
  vocabulario de la consulta decida qué se recupera). Se fusiona por consenso (RRF): sube el chunk en el que muchas
  variantes coinciden.
* **Descomposición**: subconsultas independientes, una por TEMA. Combate el embedding promedio de una consulta
  multi-tema («cerca de todo, cerca de nada»). Se fusiona por cobertura (*round-robin*): cada tema queda representado.

Qué técnica aplicar (si alguna) lo decide una heurística barata sobre la longitud y la estructura de la consulta, y la
decisión se registra. La llamada al LLM usa la generación estructurada del proyecto con instrucciones de «correa
corta»: conservar los términos exactos del dominio, no inventar requisitos, menos es mejor que fragmentar y como máximo
4 subconsultas (el tope vive en el esquema Y en las instrucciones). Ante cualquier fallo, degrada a `direct`.
"""

from dataclasses import dataclass
from typing import Literal

import structlog
from pydantic import BaseModel, Field

from app.foundation.llm.structured import Generator, generate_structured
from app.foundation.prompts.loader import render_rag_template

logger = structlog.get_logger(__name__)

Technique = Literal["direct", "expand", "decompose"]
DIRECT: Technique = "direct"
EXPAND: Technique = "expand"
DECOMPOSE: Technique = "decompose"

# Umbrales de la heurística (deliberadamente simples).
_SHORT_WORDS = 6  # por debajo: la consulta pasa tal cual
_LONG_WORDS = 25  # a partir de aquí: se trata como multi-tema
_MULTITOPIC_CONNECTORS = 2  # tantos «and»/comas/«;» ⇒ multi-tema
_MAX_TOKENS = 1500


class SubQuery(BaseModel):
    """Una consulta generada y el tema que cubre (el tema ayuda al registro y a comprobar la cobertura)."""

    topic: str = Field(min_length=1, description="Etiqueta corta del ángulo o tema de esta consulta.")
    query: str = Field(min_length=1, description="Consulta de búsqueda autocontenida, en inglés.")


class QueryTransformation(BaseModel):
    """Salida estructurada: de 1 a 4 subconsultas."""

    subqueries: list[SubQuery] = Field(min_length=1, max_length=4)


@dataclass(frozen=True)
class QueryPlan:
    """La técnica elegida y las subconsultas a ejecutar."""

    technique: Technique
    subqueries: list[SubQuery]


def choose_technique(query_text: str) -> Technique:
    """Elige la técnica por la forma de la consulta: longitud y conectores de tema."""
    words = len(query_text.split())
    if words < _SHORT_WORDS:
        return DIRECT

    lowered = query_text.lower()
    connectors = (
        lowered.count(" and ")
        + lowered.count(" y ")
        + query_text.count(",")
        + query_text.count(";")
        + lowered.count(" plus ")
        + lowered.count(" also ")
        + lowered.count(" además ")
    )
    sentences = sum(query_text.count(mark) for mark in ".!?")
    if words >= _LONG_WORDS or connectors >= _MULTITOPIC_CONNECTORS or sentences >= 2:
        return DECOMPOSE
    return EXPAND


def _direct(query_text: str) -> QueryPlan:
    return QueryPlan(DIRECT, [SubQuery(topic="original", query=query_text)])


async def transform_query(
    query_text: str,
    *,
    generate: Generator,
    enabled: bool = True,
    model: str | None = None,
    max_subqueries: int = 4,
) -> QueryPlan:
    """Las subconsultas a ejecutar para `query_text` y la técnica usada.

    Ante cualquier fallo (o con la transformación deshabilitada) degrada a una única consulta directa: la recuperación
    nunca depende de que el transformador funcione.
    """
    technique = choose_technique(query_text) if enabled else DIRECT
    if technique == DIRECT:
        logger.info("query_transform_decided", technique=DIRECT, subqueries=1)
        return _direct(query_text)

    template = "system_expand" if technique == EXPAND else "system_decompose"
    messages = [
        {
            "role": "system",
            "content": render_rag_template("query_transform", template, {"max_subqueries": max_subqueries}),
        },
        {"role": "user", "content": render_rag_template("query_transform", "user", {"query": query_text})},
    ]
    options: dict = {"max_tokens": _MAX_TOKENS}
    if model:
        options["model"] = model
    try:
        result, _ = await generate_structured(generate, messages, QueryTransformation, **options)
        subqueries = result.subqueries[:max_subqueries]
    except Exception as exc:
        logger.warning("query_transform_failed", technique=technique, error_type=type(exc).__name__)
        return _direct(query_text)

    logger.info(
        "query_transform_decided",
        technique=technique,
        subqueries=len(subqueries),
        topics=[subquery.topic for subquery in subqueries],
    )
    return QueryPlan(technique, subqueries)
