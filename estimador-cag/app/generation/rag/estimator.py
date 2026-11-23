"""Orquestador RAG de estimación fundamentada (Sesión 9).

Cierra el ciclo que faltaba: `transcripción → reformulación → recuperación filtrada → ensamblado → generación`, con
una `Estimate` en jornadas-ingeniero, citas verificadas y un nivel de confianza honesto. La generación usa la
primitiva estructurada del proyecto (`generate_structured`: corrección en la misma conversación, caché, *fallback*,
costes), no Instructor (ver `docs/evaluacion-instructor-litellm.md`).

Los endpoints por etapa (`/v1/estimate/stages/*`) llaman a los MISMOS métodos públicos (`reformulate`, `retrieve`,
`assemble`, `generate`, `review`); solo `estimate_from_transcript` añade los reintentos correctivos.
"""

import structlog

from app.config import Settings
from app.foundation.llm.service import generate_from_messages
from app.foundation.llm.structured import Generator, generate_structured
from app.generation.rag.chunking.base import count_tokens
from app.generation.rag.context_assembler import build_context_block, truncate_to_token_budget
from app.generation.rag.errors import GenerationError, MalformedEstimateError
from app.generation.rag.idempotency import IdempotencyStore
from app.generation.rag.observability import log_stage
from app.generation.rag.prompt_builder import build_generation_messages
from app.generation.rag.query_reformulator import compose_search_text, reformulate_query
from app.generation.rag.retriever import ChunkRetriever, RetrievalFilters
from app.generation.rag.schemas import (
    AssembleResult,
    Estimate,
    EstimationQuery,
    ReformulationResult,
    RetrievalResult,
    RetrievedChunk,
)
from app.generation.rag.validation import check_coherence, fabricated_source_ids

logger = structlog.get_logger(__name__)

# Sectores presentes en el corpus: solo se filtra por sector si el brief nombra uno de ellos (un sector libre del
# LLM, como «fintech», vaciaría la recuperación sin motivo).
KNOWN_SECTORS = frozenset(
    {"finance", "ecommerce", "healthcare", "industrial", "logistics", "education", "media", "government"}
)

_GENERATION_MAX_TOKENS = 8000

CITATION_FEEDBACK = (
    "Tu respuesta anterior citó source_id que no están en el contexto: {ids}. Cita solo el atributo `id` de los "
    "elementos <source> que aparecen en el bloque <sources>."
)
COHERENCE_FEEDBACK = (
    'Cuando confidence es "insufficient", total_engineer_days y duration_weeks deben ser null, modules debe estar '
    "vacío e insufficient_context_explanation debe explicar qué falta; en otro caso, aporta módulos, tareas y cifras."
)
SOFT_FAIL_EXPLANATION = "Ningún presupuesto histórico superó el umbral de relevancia para este proyecto."


def insufficient_estimate(explanation: str = SOFT_FAIL_EXPLANATION) -> Estimate:
    """Estimación canónica de contexto insuficiente: sin cifras ni módulos."""
    return Estimate(
        confidence="insufficient",
        reasoning="La recuperación no encontró presupuestos históricos suficientemente relevantes.",
        insufficient_context_explanation=explanation,
    )


def sector_filter(query: EstimationQuery) -> list[str] | None:
    sector = (query.sector or "").strip().lower()
    return [sector] if sector in KNOWN_SECTORS else None


class GroundedEstimator:
    def __init__(
        self,
        settings: Settings,
        retriever: ChunkRetriever,
        idempotency: IdempotencyStore,
        *,
        generate: Generator | None = None,
    ) -> None:
        self.settings = settings
        self._retriever = retriever
        self._idempotency = idempotency
        self._generate = generate or generate_from_messages

    # --- Etapas (reutilizadas por `/v1/estimate/stages/*`) -----------------------------------------------------

    async def reformulate(self, transcript: str) -> ReformulationResult:
        query = await reformulate_query(transcript, generate=self._generate, model=self.settings.reformulation_model)
        return ReformulationResult(query=query, search_text=compose_search_text(query))

    async def retrieve(
        self,
        query_text: str,
        *,
        top_k: int | None = None,
        distance_threshold: float | None = None,
        filters: RetrievalFilters | None = None,
    ) -> RetrievalResult:
        return await self._retriever.search(
            query_text,
            top_k=top_k or self.settings.retrieval_top_k,
            distance_threshold=(
                self.settings.retrieval_distance_threshold if distance_threshold is None else distance_threshold
            ),
            filters=filters or RetrievalFilters(),
        )

    def assemble(self, chunks: list[RetrievedChunk], max_context_tokens: int | None = None) -> AssembleResult:
        kept = truncate_to_token_budget(chunks, max_context_tokens or self.settings.max_context_tokens)
        context_block = build_context_block(kept)
        return AssembleResult(
            context_block=context_block,
            kept_chunks=kept,
            dropped_count=len(chunks) - len(kept),
            token_count=count_tokens(context_block),
        )

    async def generate(self, context_block: str, query: EstimationQuery, feedback: str | None = None) -> Estimate:
        """Una generación estructurada; cualquier fallo (proveedor o salida inválida) es `GenerationError`."""
        options: dict = {"max_tokens": _GENERATION_MAX_TOKENS}
        if self.settings.generation_model:
            options["model"] = self.settings.generation_model
        messages = build_generation_messages(context_block, query, feedback)
        try:
            estimate, _ = await generate_structured(self._generate, messages, Estimate, **options)
        except Exception as exc:
            raise GenerationError("grounded estimate generation failed") from exc
        return estimate

    @staticmethod
    def review(estimate: Estimate, kept_chunks: list[RetrievedChunk]) -> tuple[list[int], bool]:
        """Señales de fundamentación: ids inventados y si cumple la regla de coherencia."""
        return fabricated_source_ids(estimate, {chunk.id for chunk in kept_chunks}), check_coherence(estimate)

    # --- Pipeline completo -------------------------------------------------------------------------------------

    async def estimate_from_transcript(self, transcript: str, idempotency_key: str | None = None) -> Estimate:
        """Transcripción → estimación fundamentada.

        Lanza `ReformulationError`, `EmbedderUnavailableError`, `RetrievalError`, `GenerationError` o
        `MalformedEstimateError` (todas `RagError`).
        """
        if idempotency_key:
            cached = await self._idempotency.get(idempotency_key)
            if cached is not None:
                logger.info("idempotency_hit", source=self._idempotency.backend)
                return cached

        estimate = await self._run(transcript)

        if idempotency_key:
            await self._idempotency.set(idempotency_key, estimate)
        return estimate

    async def _run(self, transcript: str) -> Estimate:
        with log_stage("reformulation", transcription_chars=len(transcript)):
            reformulation = await self.reformulate(transcript)
        query = reformulation.query

        sectors = sector_filter(query)
        with log_stage("retrieval", sector_filtered=bool(sectors)):
            retrieval = await self.retrieve(reformulation.search_text, filters=RetrievalFilters(sectors=sectors))
        if retrieval.low_confidence:
            logger.info("rag_retrieval_soft_fail", candidates_evaluated=retrieval.candidates_evaluated)
            return insufficient_estimate()

        with log_stage("augmentation", chunks_count=len(retrieval.chunks)):
            assembled = self.assemble(retrieval.chunks)
        context_block, kept = assembled.context_block, assembled.kept_chunks

        with log_stage("generation", chunks_count=len(kept)):
            estimate = await self.generate(context_block, query)

        fabricated, _ = self.review(estimate, kept)
        if fabricated:
            with log_stage("citation_retry", fabricated_count=len(fabricated)):
                estimate = await self.generate(context_block, query, CITATION_FEEDBACK.format(ids=fabricated))
            fabricated, _ = self.review(estimate, kept)
            if fabricated and estimate.confidence in ("high", "medium"):
                logger.warning("rag_citations_unrepaired", fabricated_count=len(fabricated))
                estimate = estimate.model_copy(update={"confidence": "low"})

        if not check_coherence(estimate):
            with log_stage("coherence_repair"):
                estimate = await self.generate(context_block, query, COHERENCE_FEEDBACK)
            if not check_coherence(estimate):
                raise MalformedEstimateError("estimate violates the insufficient-context coherence rule")
        return estimate
