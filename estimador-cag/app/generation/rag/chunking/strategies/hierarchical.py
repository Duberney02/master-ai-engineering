"""Padre-hijo: se indexan a la vez el presupuesto completo (padre) y cada componente (hijo).

Los hijos son pequeños y específicos (buena recuperación); el padre es grande y con todo el contexto (bueno
para alimentar al generador). Cada hijo lleva `metadata.parent_chunk_id`; el retriever de la Sesión 8 decidirá
qué nivel devolver.
"""

import time

from app.generation.rag.chunking.base import Chunker, count_tokens
from app.generation.rag.chunking.structural import (
    budget_metadata,
    component_metadata,
    render_component_text,
    serialize_budget,
)
from app.generation.rag.schemas import Budget, Chunk


class HierarchicalChunker(Chunker):
    strategy_name = "hierarchical"

    async def chunk(self, budgets: list[Budget]) -> list[Chunk]:
        started = time.perf_counter()
        chunks: list[Chunk] = []
        for budget in budgets:
            parent_id = f"{budget.budget_id}::parent"
            parent_text = serialize_budget(budget)
            chunks.append(
                Chunk(
                    chunk_id=parent_id,
                    text=parent_text,
                    metadata={**budget_metadata(budget), "level": "parent"},
                    token_count=count_tokens(parent_text),
                )
            )
            for component in budget.components:
                child_text = render_component_text(budget, component)
                metadata = {**component_metadata(budget, component), "level": "child", "parent_chunk_id": parent_id}
                chunks.append(
                    Chunk(
                        chunk_id=f"{budget.budget_id}::{component.component_id}",
                        text=child_text,
                        metadata=metadata,
                        token_count=count_tokens(child_text),
                    )
                )
        return self._finish(chunks, budgets, started)
