"""Chunking proposicional: un LLM descompone cada componente en hechos atómicos autocontenidos.

Cada proposición es un chunk. Es preciso para recuperar hechos concretos, pero caro: una llamada al LLM por
componente. Se acumulan los tokens de uso y se reporta el coste. Las llamadas se hacen en paralelo (acotadas
por `CONCURRENCY`) y un fallo de una llamada degrada ese componente a un único chunk, nunca descarta contenido.
El modelo es configurable (`Settings.propositional_chunker_model`, debe ser de OpenAI).
"""

import asyncio
import time

import structlog
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import Settings
from app.generation.rag.chunking.base import Chunker, count_tokens
from app.generation.rag.chunking.pricing import llm_cost_usd
from app.generation.rag.chunking.structural import component_metadata, render_component_text
from app.generation.rag.schemas import Budget, BudgetComponent, Chunk

logger = structlog.get_logger(__name__)

CONCURRENCY = 8

_SYSTEM_PROMPT = (
    "Descompón el siguiente contenido en proposiciones claras, simples y autocontenidas. Cada proposición debe:\n"
    "1. Expresar un único hecho atómico.\n"
    "2. Entenderse por sí sola, sin el texto que la rodea.\n"
    "3. Sustituir pronombres y referencias por la entidad explícita a la que se refieren "
    "(por ejemplo, 'ello' por el nombre del componente).\n"
    "Mantén el idioma del contenido. Devuelve la lista de proposiciones."
)


class _Propositions(BaseModel):
    propositions: list[str] = Field(default_factory=list)


class PropositionalChunker(Chunker):
    strategy_name = "propositional"

    def __init__(self, client: AsyncOpenAI, model: str, settings: Settings) -> None:
        self._client = client
        self._model = model
        self._settings = settings

    async def chunk(self, budgets: list[Budget]) -> list[Chunk]:
        started = time.perf_counter()
        gate = asyncio.Semaphore(CONCURRENCY)
        jobs = [(budget, component) for budget in budgets for component in budget.components]

        async def decompose(job: tuple[Budget, BudgetComponent]) -> tuple[list[str], float]:
            async with gate:
                return await self._decompose(render_component_text(*job))

        results = await asyncio.gather(*(decompose(job) for job in jobs))

        chunks: list[Chunk] = []
        cost = 0.0
        for (budget, component), (propositions, call_cost) in zip(jobs, results, strict=True):
            cost += call_cost
            # Si la descomposición falla se conserva el componente entero: nunca se pierde contenido.
            for j, text in enumerate(propositions or [render_component_text(budget, component)]):
                chunks.append(
                    Chunk(
                        chunk_id=f"{budget.budget_id}::{component.component_id}::prop{j}",
                        text=text,
                        metadata={**component_metadata(budget, component), "proposition": j},
                        token_count=count_tokens(text),
                    )
                )
        return self._finish(chunks, budgets, started, extra_api_calls=len(jobs), extra_cost_usd=cost)

    async def _decompose(self, text: str) -> tuple[list[str], float]:
        """(proposiciones, coste en USD). Ante cualquier error de la API registra y devuelve ([], 0)."""
        try:
            completion = await self._client.beta.chat.completions.parse(
                model=self._model,
                response_format=_Propositions,
                messages=[{"role": "system", "content": _SYSTEM_PROMPT}, {"role": "user", "content": text}],
            )
        except Exception as exc:
            logger.warning("propositional_call_failed", error_type=type(exc).__name__)
            return [], 0.0
        parsed = completion.choices[0].message.parsed
        usage = completion.usage
        cost = llm_cost_usd(
            self._settings,
            self._model,
            input_tokens=getattr(usage, "prompt_tokens", 0),
            output_tokens=getattr(usage, "completion_tokens", 0),
        )
        propositions = [p.strip() for p in (parsed.propositions if parsed else []) if p.strip()]
        return propositions, cost
