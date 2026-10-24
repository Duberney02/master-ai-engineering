"""Chunking estructural: un chunk por componente de presupuesto, sin overlap ni división por tamaño.

Las tres funciones de render (`render_component_text`, `serialize_budget`, `component_metadata`) las reutilizan
las demás estrategias: así todas trocean la misma representación textual del corpus.
"""

import time

from app.generation.rag.chunking.base import Chunker, count_tokens
from app.generation.rag.schemas import Budget, BudgetComponent, Chunk

EMBEDDING_MODEL = "text-embedding-3-small"


def _format_hours(hours: float) -> str:
    return str(int(hours)) if float(hours).is_integer() else str(hours)


def render_component_text(budget: Budget, component: BudgetComponent) -> str:
    """Cabecera con el contexto del presupuesto padre más el detalle del componente (lo que se embebe)."""
    return (
        f"[Project: {budget.project_summary}]\n"
        f"[Client sector: {budget.client_metadata.sector} | Year: {budget.year} "
        f"| Main tech: {budget.main_technology}]\n"
        "\n"
        f"Component: {component.name}\n"
        f"Description: {component.description}\n"
        f"Tech stack: {', '.join(component.tech_stack)}\n"
        f"Complexity: {component.complexity}\n"
        f"Estimated hours: {_format_hours(component.estimated_hours)}"
    )


def serialize_budget(budget: Budget) -> str:
    """El presupuesto completo como un solo texto (cabecera y un bloque por componente)."""
    header = (
        f"[Project: {budget.project_summary}]\n"
        f"[Client: {budget.client_metadata.name} | Sector: {budget.client_metadata.sector} "
        f"| Year: {budget.year} | Main tech: {budget.main_technology}]"
    )
    blocks = [header]
    for component in budget.components:
        blocks.append(
            f"Component: {component.name}\n"
            f"Description: {component.description}\n"
            f"Tech stack: {', '.join(component.tech_stack)}\n"
            f"Complexity: {component.complexity}\n"
            f"Estimated hours: {_format_hours(component.estimated_hours)}"
        )
    return "\n\n".join(blocks)


def budget_metadata(budget: Budget) -> dict:
    """Metadatos filtrables de un chunk a nivel de presupuesto."""
    return {
        "budget_id": budget.budget_id,
        "client_sector": budget.client_metadata.sector,
        "main_technology": budget.main_technology,
        "year": budget.year,
    }


def component_metadata(budget: Budget, component: BudgetComponent) -> dict:
    """Metadatos filtrables de un chunk a nivel de componente. No forman parte del texto que se embebe."""
    return {
        **budget_metadata(budget),
        "component_id": component.component_id,
        "complexity": component.complexity,
        "estimated_hours": component.estimated_hours,
    }


class JSONStructuralChunker(Chunker):
    """Un chunk por componente, con el contexto del presupuesto en la cabecera."""

    strategy_name = "structural"

    async def chunk(self, budgets: list[Budget]) -> list[Chunk]:
        started = time.perf_counter()
        chunks = [self._chunk_component(budget, component) for budget in budgets for component in budget.components]
        return self._finish(chunks, budgets, started)

    @staticmethod
    def _chunk_component(budget: Budget, component: BudgetComponent) -> Chunk:
        text = render_component_text(budget, component)
        return Chunk(
            chunk_id=f"{budget.budget_id}::{component.component_id}",
            text=text,
            metadata=component_metadata(budget, component),
            token_count=count_tokens(text),
        )
