"""Horas por tarea por búsqueda vectorial (Sesión 10).

La generación de la estructura produce módulos → tareas SIN horas. Este módulo deriva las horas de cada tarea del
corpus histórico de tareas (`chunk_type="historical_task"`, generado por `scripts/build_task_corpus.py`):

1. compone un texto de búsqueda con la tarea (módulo + nombre + descripción),
2. lo embebe y hace un k-NN filtrado por `historical_task`, y
3. combina las horas registradas de los vecinos en un solo número mediante un CONSENSO PONDERADO POR LA INVERSA DE LA
   DISTANCIA, con una fiabilidad que mezcla lo cerca que están los vecinos con lo mucho que se ponen de acuerdo.

Una tarea cuyo vecino más cercano supera el umbral de distancia NO recibe horas (`has_match=false`): es una bandera roja
para que la persona aporte el número, mejor que una conjetura de baja confianza. El consenso es una función PURA
(`weighted_consensus`), trivial de probar; el recuperador solo devuelve los chunks.

Reutiliza `ChunkRetriever` (híbrido y reranking incluidos, según runtime y `Settings`) y no importa ningún otro hermano
de `generation/` (ver `ARCHITECTURE.md`).
"""

import asyncio
import statistics
from dataclasses import dataclass

import structlog

from app.config import Settings
from app.foundation.llm.runtime_config import RetrievalToggles, RuntimeRetrievalConfig
from app.generation.rag.retriever import ChunkRetriever, RetrievalFilters
from app.generation.rag.schemas import (
    RetrievedChunk,
    TaskHoursEstimate,
    TaskHoursModuleInput,
    TaskHoursResult,
    TaskNeighbor,
)

logger = structlog.get_logger(__name__)

HISTORICAL_TASK_CHUNK_TYPE = "historical_task"
# Suelo de la distancia en el peso `1 / max(distancia, ε)`: un acierto exacto (distancia ≈ 0) no se dispara a peso
# infinito ni silencia a los demás vecinos.
WEIGHT_EPS = 1e-3
# Búsquedas simultáneas como máximo: cada tarea es un embedding y una sesión de base de datos.
MAX_CONCURRENT_SEARCHES = 8


@dataclass(frozen=True)
class Consensus:
    """Resultado del consenso: horas, fiabilidad en [0, 1] y dispersión (coeficiente de variación)."""

    hours: float
    reliability: float
    dispersion: float


def compose_task_search_text(module: str, name: str, description: str | None) -> str:
    """Texto embebible de una tarea, con la forma del chunk `historical_task` (módulo + nombre + descripción), para que
    consulta y corpus vivan en el mismo espacio de vocabulario."""
    parts = []
    if module:
        parts.append(f"Module: {module}")
    parts.append(f"Task: {name}")
    if description:
        parts.append(description)
    return "\n".join(parts)


def weighted_consensus(neighbors: list[tuple[float, float]]) -> Consensus:
    """Consenso ponderado de `(horas, distancia)` por vecino.

    * `hours`: media de las horas ponderada por `1 / max(distancia, ε)`, redondeada a una cifra decimal.
    * `dispersion`: coeficiente de variación de las horas vecinas (desviación típica / media), una medida transparente
      de «cuánto discrepan» (0 con un solo vecino o con media cero).
    * `reliability`: `similitud_ponderada × (1 − min(dispersión, 1))` en `[0, 1]`: alta solo cuando los vecinos están
      CERCA y de ACUERDO. La similitud de un vecino es `1 − distancia` (mínimo 0), ponderada igual que las horas.

    Precondición: `neighbors` no está vacío (quien llama resuelve antes el caso sin vecinos).
    """
    if not neighbors:
        raise ValueError("weighted_consensus needs at least one neighbour")
    weights = [1.0 / max(distance, WEIGHT_EPS) for _hours, distance in neighbors]
    total = sum(weights)
    hours_values = [hours for hours, _distance in neighbors]

    hours = sum(w * h for w, (h, _d) in zip(weights, neighbors, strict=True)) / total
    similarity = sum(w * max(0.0, 1.0 - d) for w, (_h, d) in zip(weights, neighbors, strict=True)) / total

    mean_hours = statistics.fmean(hours_values)
    dispersion = statistics.pstdev(hours_values) / mean_hours if len(hours_values) > 1 and mean_hours > 0 else 0.0

    reliability = max(0.0, min(1.0, similarity * (1.0 - min(dispersion, 1.0))))
    return Consensus(hours=round(hours, 1), reliability=round(reliability, 3), dispersion=round(dispersion, 3))


def estimate_from_chunks(module: str, name: str, chunks: list[RetrievedChunk]) -> TaskHoursEstimate:
    """Estimación de una tarea a partir de los vecinos recuperados; sin vecinos con horas, `has_match=false`."""
    usable = [chunk for chunk in chunks if chunk.estimated_hours is not None]
    if not usable:
        return TaskHoursEstimate(module=module, task=name, has_match=False)
    neighbors = [
        TaskNeighbor(
            source_id=chunk.id,
            budget_id=chunk.budget_id,
            estimated_hours=float(chunk.estimated_hours),
            distance=chunk.distance,
        )
        for chunk in usable
    ]
    consensus = weighted_consensus([(n.estimated_hours, n.distance) for n in neighbors])
    return TaskHoursEstimate(
        module=module,
        task=name,
        estimated_hours=consensus.hours,
        reliability=consensus.reliability,
        has_match=True,
        dispersion=consensus.dispersion,
        neighbors=neighbors,
    )


class TaskHoursEstimator:
    """Horas por tarea con el recuperador y los parámetros de runtime (`task_hours_*`, modo de búsqueda y rerank)."""

    def __init__(
        self, settings: Settings, retriever: ChunkRetriever, *, runtime_retrieval: RuntimeRetrievalConfig | None = None
    ) -> None:
        self.settings = settings
        self._retriever = retriever
        self._runtime_retrieval = runtime_retrieval

    async def _toggles(self) -> RetrievalToggles:
        if self._runtime_retrieval is None:
            return RetrievalToggles.from_settings(self.settings)
        return await self._runtime_retrieval.effective()

    async def estimate_one(
        self,
        module: str,
        name: str,
        description: str | None,
        *,
        top_k: int,
        distance_threshold: float,
        search_mode: str = "vector",
        rerank: bool = False,
    ) -> TaskHoursEstimate:
        """Horas de una tarea. Con `rerank`, los vecinos del consenso son los que el cross-encoder juzga más relevantes,
        no solo los más cercanos en coseno."""
        result = await self._retriever.search(
            compose_task_search_text(module, name, description),
            top_k=top_k,
            distance_threshold=distance_threshold,
            filters=RetrievalFilters(chunk_types=[HISTORICAL_TASK_CHUNK_TYPE]),
            search_mode=search_mode,
            rerank=rerank,
            rerank_top_n=top_k,
        )
        return estimate_from_chunks(module, name, result.chunks)

    async def estimate_all(
        self,
        modules: list[TaskHoursModuleInput],
        *,
        top_k: int | None = None,
        distance_threshold: float | None = None,
    ) -> TaskHoursResult:
        """Horas de todas las tareas (búsquedas concurrentes y acotadas); el orden de salida es el de entrada.

        Lanza `EmbedderUnavailableError` o `RetrievalError` (la API los traduce a un 502 genérico).
        """
        toggles = await self._toggles()
        k = top_k if top_k is not None else toggles.task_hours_top_k
        threshold = distance_threshold if distance_threshold is not None else toggles.task_hours_distance_threshold
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_SEARCHES)

        async def one(module: str, name: str, description: str | None) -> TaskHoursEstimate:
            async with semaphore:
                return await self.estimate_one(
                    module,
                    name,
                    description,
                    top_k=k,
                    distance_threshold=threshold,
                    search_mode=toggles.search_mode,
                    rerank=toggles.rerank,
                )

        estimates = await asyncio.gather(
            *(one(module.name, task.name, task.description) for module in modules for task in module.tasks)
        )
        matched = sum(1 for estimate in estimates if estimate.has_match)
        logger.info(
            "task_hours_done",
            tasks=len(estimates),
            matched=matched,
            flagged=len(estimates) - matched,
            top_k=k,
            distance_threshold=threshold,
            search_mode=toggles.search_mode,
            rerank=toggles.rerank,
        )
        return TaskHoursResult(tasks=list(estimates))
