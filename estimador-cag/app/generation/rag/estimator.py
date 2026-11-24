"""Orquestador RAG de estimación fundamentada (Sesión 9).

Cierra el ciclo que faltaba: `transcripción → reformulación → recuperación filtrada → ensamblado → generación`, con
una `Estimate` en jornadas-ingeniero, citas verificadas y un nivel de confianza honesto. La generación usa la
primitiva estructurada del proyecto (`generate_structured`: corrección en la misma conversación, caché, *fallback*,
costes), no Instructor (ver `docs/evaluacion-instructor-litellm.md`).

Los endpoints por etapa (`/v1/estimate/stages/*`) llaman a los MISMOS métodos públicos (`reformulate`, `retrieve`,
`assemble`, `generate`, `review`, `verify`); solo `estimate_from_transcript` añade los reintentos correctivos.

Sesión 11: `assemble` aplica la aumentación (compresión y reordenación) tras el truncado; el pipeline completo verifica
las citas por línea y, con el gate habilitado, rebaja la confianza a `low` si alguna línea queda `degraded`.
"""

import structlog

from app.config import Settings
from app.foundation.llm.runtime_config import RetrievalToggles, RuntimeRetrievalConfig
from app.foundation.llm.service import generate_from_messages
from app.foundation.llm.structured import Generator, generate_structured
from app.generation.rag.chunking.base import count_tokens
from app.generation.rag.context_assembler import build_context_block, truncate_to_token_budget
from app.generation.rag.errors import GenerationError, MalformedEstimateError
from app.generation.rag.idempotency import IdempotencyStore
from app.generation.rag.observability import log_stage
from app.generation.rag.prompt_builder import build_generation_messages
from app.generation.rag.quality.augmentation import augment_chunks
from app.generation.rag.quality.hallucination import run_gate
from app.generation.rag.query_reformulator import compose_search_text, reformulate_query
from app.generation.rag.retriever import ChunkRetriever, RetrievalFilters
from app.generation.rag.schemas import (
    AssembleResult,
    CitationReport,
    Estimate,
    EstimationQuery,
    ReformulationResult,
    RetrievalResult,
    RetrievedChunk,
    StructureResult,
    VerifyReport,
)
from app.generation.rag.structure import generate_structure
from app.generation.rag.validation import build_citation_report, check_coherence, fabricated_source_ids

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
        runtime_retrieval: RuntimeRetrievalConfig | None = None,
    ) -> None:
        self.settings = settings
        self._retriever = retriever
        self._idempotency = idempotency
        self._generate = generate or generate_from_messages
        self._runtime_retrieval = runtime_retrieval

    async def retrieval_toggles(self) -> RetrievalToggles:
        """Parámetros de recuperación efectivos: override de runtime (Redis) y, sin él, `Settings`."""
        if self._runtime_retrieval is None:
            return RetrievalToggles.from_settings(self.settings)
        return await self._runtime_retrieval.effective()

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
        search_mode: str | None = None,
        rerank: bool | None = None,
    ) -> RetrievalResult:
        """Recupera con la precedencia petición → runtime → `Settings` para `search_mode` y `rerank`."""
        if search_mode is None or rerank is None:
            toggles = await self.retrieval_toggles()
            search_mode = search_mode or toggles.search_mode
            rerank = toggles.rerank if rerank is None else rerank
        return await self._retriever.search(
            query_text,
            top_k=top_k or self.settings.retrieval_top_k,
            distance_threshold=(
                self.settings.retrieval_distance_threshold if distance_threshold is None else distance_threshold
            ),
            filters=filters or RetrievalFilters(),
            search_mode=search_mode,
            rerank=rerank,
        )

    def assemble(
        self,
        chunks: list[RetrievedChunk],
        max_context_tokens: int | None = None,
        *,
        toggles: RetrievalToggles | None = None,
    ) -> AssembleResult:
        """Truncado al presupuesto de tokens y, con `toggles.augmentation_enabled`, compresión y reordenación."""
        kept = truncate_to_token_budget(chunks, max_context_tokens or self.settings.max_context_tokens)
        dropped = len(chunks) - len(kept)
        if toggles is not None and toggles.augmentation_enabled:
            kept = augment_chunks(kept, compress=toggles.augmentation_compress, reorder=toggles.augmentation_reorder)
        context_block = build_context_block(kept)
        return AssembleResult(
            context_block=context_block,
            kept_chunks=kept,
            dropped_count=dropped,
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

    async def structure(self, query: EstimationQuery) -> StructureResult:
        """Módulos → tareas del brief SIN horas ni fuentes (las horas salen de `task_hours`).

        Lanza `GenerationError` si la generación falla."""
        return await generate_structure(query, generate=self._generate, model=self.settings.generation_model)

    @staticmethod
    def review(estimate: Estimate, kept_chunks: list[RetrievedChunk]) -> tuple[list[int], bool]:
        """Señales de fundamentación: ids inventados (globales o por línea) y si cumple la regla de coherencia."""
        return fabricated_source_ids(estimate, {chunk.id for chunk in kept_chunks}), check_coherence(estimate)

    @staticmethod
    def citation_report(estimate: Estimate, kept_chunks: list[RetrievedChunk]) -> CitationReport:
        """Informe de citas por línea (`grounded`, `dangling`, `insufficient`) contra el contexto."""
        return build_citation_report(estimate, {chunk.id for chunk in kept_chunks})

    async def verify(
        self, estimate: Estimate, kept_chunks: list[RetrievedChunk], *, use_judge: bool = True
    ) -> VerifyReport:
        """Gate de alucinaciones: ancla numérica por línea y, con `use_judge`, un juez para toda la estimación.

        Un fallo del juez se propaga (la etapa lo traduce a 502; el pipeline lo degrada a solo-ancla)."""
        toggles = await self.retrieval_toggles()
        return await run_gate(
            estimate,
            kept_chunks,
            generate=self._generate,
            tolerance=toggles.hallucination_numeric_tolerance,
            use_judge=use_judge,
            judge_model=self.settings.hallucination_judge_model or self.settings.generation_model,
        )

    async def _apply_gate(self, estimate: Estimate, kept: list[RetrievedChunk]) -> Estimate:
        """Pasa el gate y rebaja `high`/`medium` a `low` si alguna línea queda `degraded`.

        Si el juez falla, el gate se degrada a solo ancla numérica: una verificación caída no tumba la estimación."""
        try:
            report = await self.verify(estimate, kept, use_judge=True)
        except Exception as exc:
            logger.warning("rag_gate_judge_failed", error_type=type(exc).__name__)
            report = await self.verify(estimate, kept, use_judge=False)
        if report.totals.degraded and estimate.confidence in ("high", "medium"):
            logger.warning("rag_gate_degraded", degraded_count=report.totals.degraded, judge_used=report.judge_used)
            return estimate.model_copy(update={"confidence": "low"})
        return estimate

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

        toggles = await self.retrieval_toggles()
        with log_stage("augmentation", chunks_count=len(retrieval.chunks)):
            assembled = self.assemble(retrieval.chunks, toggles=toggles)
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

        if toggles.hallucination_gate_enabled and estimate.confidence != "insufficient":
            with log_stage("hallucination_gate", lines=sum(len(m.tasks) for m in estimate.modules)):
                estimate = await self._apply_gate(estimate, kept)
        return estimate
