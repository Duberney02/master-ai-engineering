"""Chunking estructural: un chunk por componente de presupuesto, sin overlap ni división por tamaño."""

import tiktoken

from app.generation.rag.schemas import Budget, BudgetComponent, Chunk

EMBEDDING_MODEL = "text-embedding-3-small"


def _format_hours(hours: float) -> str:
    return str(int(hours)) if float(hours).is_integer() else str(hours)


class JSONStructuralChunker:
    def __init__(self) -> None:
        self._encoding = tiktoken.encoding_for_model(EMBEDDING_MODEL)

    def chunk(self, budgets: list[Budget]) -> list[Chunk]:
        return [self._chunk_component(budget, component) for budget in budgets for component in budget.components]

    def _chunk_component(self, budget: Budget, component: BudgetComponent) -> Chunk:
        text = (
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
        # Los metadatos acompañan al chunk; no forman parte del texto que se envía al modelo.
        metadata = {
            "budget_id": budget.budget_id,
            "component_id": component.component_id,
            "client_sector": budget.client_metadata.sector,
            "main_technology": budget.main_technology,
            "year": budget.year,
            "complexity": component.complexity,
            "estimated_hours": component.estimated_hours,
        }
        return Chunk(
            chunk_id=f"{budget.budget_id}::{component.component_id}",
            text=text,
            metadata=metadata,
            token_count=len(self._encoding.encode(text)),
        )
