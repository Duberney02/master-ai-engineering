"""Contextual Retrieval (técnica de Anthropic): cada chunk lleva un párrafo que lo sitúa en su presupuesto.

Un LLM genera una breve descripción del componente dentro del documento completo y se antepone al texto del
chunk. El documento padre se envía con `cache_control`, de modo que los componentes de un mismo presupuesto
pagan el prefijo una sola vez y lo leen de la caché después. Para que la caché se escriba antes de leerse, la
primera llamada de cada presupuesto va sola y las demás en paralelo. El modelo es configurable
(`Settings.contextual_chunker_model`, debe ser de Anthropic). Es la estrategia más cara de instrumentar.
"""

import asyncio
import time

import structlog
from anthropic import AsyncAnthropic

from app.config import Settings
from app.generation.rag.chunking.base import Chunker, count_tokens
from app.generation.rag.chunking.pricing import llm_cost_usd
from app.generation.rag.chunking.structural import component_metadata, render_component_text, serialize_budget
from app.generation.rag.schemas import Budget, BudgetComponent, Chunk

logger = structlog.get_logger(__name__)

CONCURRENCY = 8
MAX_CONTEXT_TOKENS = 200

# Prompt canónico de Contextual Retrieval de Anthropic.
_CHUNK_CONTEXT_PROMPT = (
    "Here is the chunk we want to situate within the whole document:\n"
    "<chunk>\n{chunk}\n</chunk>\n\n"
    "Please give a short succinct context to situate this chunk within the overall document for the purposes of "
    "improving search retrieval of the chunk. Answer only with the succinct context and nothing else."
)


class ContextualRetrievalChunker(Chunker):
    strategy_name = "contextual_retrieval"

    def __init__(self, client: AsyncAnthropic, model: str, settings: Settings) -> None:
        self._client = client
        self._model = model
        self._settings = settings

    async def chunk(self, budgets: list[Budget]) -> list[Chunk]:
        started = time.perf_counter()
        gate = asyncio.Semaphore(CONCURRENCY)
        chunks: list[Chunk] = []
        calls = 0
        cost = 0.0
        for budget in budgets:
            document = serialize_budget(budget)

            async def situate(component: BudgetComponent, document: str = document, budget: Budget = budget):
                async with gate:
                    return await self._situate(document, render_component_text(budget, component))

            first, *rest = budget.components
            results = [await situate(first), *await asyncio.gather(*(situate(c) for c in rest))]
            for component, (context, call_cost) in zip(budget.components, results, strict=True):
                calls += 1
                cost += call_cost
                base_text = render_component_text(budget, component)
                enriched = f"{context}\n\n{base_text}" if context else base_text
                chunks.append(
                    Chunk(
                        chunk_id=f"{budget.budget_id}::{component.component_id}",
                        text=enriched,
                        metadata={**component_metadata(budget, component), "generated_context": context},
                        token_count=count_tokens(enriched),
                    )
                )
        return self._finish(chunks, budgets, started, extra_api_calls=calls, extra_cost_usd=cost)

    async def _situate(self, document: str, chunk_text: str) -> tuple[str, float]:
        """(contexto generado, coste en USD). Ante cualquier error de la API registra y devuelve ('', 0)."""
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=MAX_CONTEXT_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": f"<document>\n{document}\n</document>",
                        # El documento es grande y estable: se cachea para que el resto de componentes lo lean.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": _CHUNK_CONTEXT_PROMPT.format(chunk=chunk_text)}],
            )
        except Exception as exc:
            logger.warning("contextual_call_failed", error_type=type(exc).__name__)
            return "", 0.0
        context = response.content[0].text.strip() if response.content else ""
        usage = response.usage
        cost = llm_cost_usd(
            self._settings,
            self._model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )
        return context, cost
