"""Servicio de estimación: prompts, ejemplos, preprocesamiento y coordinación de fases.

No conoce HTTP, SSE, SDK ni Redis: recibe un `LLMGateway` (el wrapper LLM) y una
`ModelPolicy` por inyección, de modo que en pruebas se sustituyen sin parches globales.
"""

import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from app.context.examples import ExampleFormat
from app.llm.routing import ModelPolicy, ModelRoute
from app.llm.types import LLMRequest, LLMResult, StreamDelta, StreamFinal
from app.schemas.estimation import (
    DEFAULT_NUM_EXAMPLES,
    EstimationEvaluation,
    Phase,
    PreprocessingMode,
)
from app.services.evaluation import evaluate_estimation
from app.services.prompts import (
    EXTRACTION_MAX_TOKENS,
    EXTRACTION_SYSTEM_PROMPT,
    build_system_prompt,
    estimation_user_message,
)

logger = logging.getLogger(__name__)


class LLMGateway(Protocol):
    async def complete(self, request: LLMRequest, route: ModelRoute) -> LLMResult: ...

    def stream(
        self, request: LLMRequest, route: ModelRoute
    ) -> AsyncIterator[StreamDelta | StreamFinal]: ...


@dataclass(frozen=True)
class GenerationOptions:
    """Opciones por solicitud; los valores por defecto reproducen el comportamiento previo."""

    preprocessing: PreprocessingMode = "none"
    example_format: ExampleFormat = "markdown"
    num_examples: int = DEFAULT_NUM_EXAMPLES
    use_examples: bool = True
    model: str | None = None
    max_tokens: int | None = None
    allow_fallback: bool = False
    evaluate: bool = True


@dataclass(frozen=True)
class PhaseResult:
    phase: Phase
    llm: LLMResult


@dataclass
class EstimationResult:
    estimation: str
    phases: list[PhaseResult]
    latency_ms: int
    generated_at: datetime
    preprocessing: PreprocessingMode = "none"
    extracted_requirements: str | None = None
    evaluation: EstimationEvaluation | None = None

    @property
    def estimation_phase(self) -> LLMResult:
        return next(p.llm for p in self.phases if p.phase == "estimation")

    @property
    def preprocessing_phase(self) -> LLMResult | None:
        return next((p.llm for p in self.phases if p.phase == "preprocessing"), None)


# Eventos de `EstimationService.stream`
@dataclass(frozen=True)
class ExtractionCompleted:
    """Fase 1 (two_phase) terminada. Su texto viaja aparte: nunca se mezcla con la estimación."""

    text: str
    phase: PhaseResult


@dataclass(frozen=True)
class ContentDelta:
    text: str


@dataclass(frozen=True)
class EstimationCompleted:
    result: EstimationResult


StreamEvent = ExtractionCompleted | ContentDelta | EstimationCompleted


@dataclass
class EstimationService:
    llm: LLMGateway
    policy: ModelPolicy
    clock: Callable[[], float] = field(default=time.monotonic)

    # --- selección de modelo y prompts ---------------------------------------------

    def resolve_route(self, options: GenerationOptions) -> ModelRoute:
        """Lanza ModelSelectionError (validación) antes de cualquier llamada o stream."""
        return self.policy.route_for(options.model, options.allow_fallback)

    @staticmethod
    def system_prompt(options: GenerationOptions) -> str:
        return build_system_prompt(
            example_format=options.example_format,
            num_examples=options.num_examples,
            use_examples=options.use_examples,
            inline_cleaning=options.preprocessing == "inline_cleaning",
        )

    def _estimation_request(
        self, transcription: str, options: GenerationOptions, extracted: str | None
    ) -> LLMRequest:
        return LLMRequest(
            system=self.system_prompt(options),
            user=estimation_user_message(transcription, extracted),
            max_tokens=options.max_tokens,
            purpose="estimation",
        )

    @staticmethod
    def _extraction_request(transcription: str) -> LLMRequest:
        return LLMRequest(
            system=EXTRACTION_SYSTEM_PROMPT,
            user=transcription,
            max_tokens=EXTRACTION_MAX_TOKENS,
            purpose="preprocessing",
        )

    # --- generación ------------------------------------------------------------------

    async def generate(
        self,
        transcription: str,
        options: GenerationOptions | None = None,
        route: ModelRoute | None = None,
    ) -> EstimationResult:
        options = options or GenerationOptions()
        route = route or self.resolve_route(options)
        start = self.clock()
        self._log_start(transcription, options, route, streaming=False)

        phases: list[PhaseResult] = []
        extracted: str | None = None
        if options.preprocessing == "two_phase":
            extraction = await self.llm.complete(self._extraction_request(transcription), route)
            extracted = extraction.text
            phases.append(PhaseResult("preprocessing", extraction))

        estimation = await self.llm.complete(
            self._estimation_request(transcription, options, extracted), route
        )
        phases.append(PhaseResult("estimation", estimation))
        return self._finish(estimation.text, phases, options, extracted, start)

    async def stream(
        self,
        transcription: str,
        options: GenerationOptions | None = None,
        route: ModelRoute | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Extracción (si two_phase) sin streaming → `ExtractionCompleted`; estimación en
        streaming → `ContentDelta`...; al final `EstimationCompleted` con metadatos."""
        options = options or GenerationOptions()
        route = route or self.resolve_route(options)
        start = self.clock()
        self._log_start(transcription, options, route, streaming=True)

        phases: list[PhaseResult] = []
        extracted: str | None = None
        if options.preprocessing == "two_phase":
            extraction = await self.llm.complete(self._extraction_request(transcription), route)
            extracted = extraction.text
            phase = PhaseResult("preprocessing", extraction)
            phases.append(phase)
            yield ExtractionCompleted(extracted, phase)

        request = self._estimation_request(transcription, options, extracted)
        source = self.llm.stream(request, route)
        try:
            async for event in source:
                if isinstance(event, StreamDelta):
                    yield ContentDelta(event.text)
                elif isinstance(event, StreamFinal):
                    phases.append(PhaseResult("estimation", event.result))
                    yield EstimationCompleted(
                        self._finish(event.result.text, phases, options, extracted, start)
                    )
        finally:
            aclose = getattr(source, "aclose", None)
            if aclose is not None:
                await aclose()

    def _finish(
        self,
        text: str,
        phases: list[PhaseResult],
        options: GenerationOptions,
        extracted: str | None,
        start: float,
    ) -> EstimationResult:
        evaluation = None
        if options.evaluate:
            estimation = next(p.llm for p in phases if p.phase == "estimation")
            pre = next((p.llm for p in phases if p.phase == "preprocessing"), None)
            evaluation = evaluate_estimation(
                text,
                estimation.finish_reason,
                preprocessing_finish_reason=pre.finish_reason if pre else None,
            )
        result = EstimationResult(
            estimation=text,
            phases=phases,
            latency_ms=max(0, int((self.clock() - start) * 1000)),
            generated_at=datetime.now(tz=timezone.utc),
            preprocessing=options.preprocessing,
            extracted_requirements=extracted,
            evaluation=evaluation,
        )
        logger.info(
            "estimation_completed",
            extra={
                "preprocessing": options.preprocessing,
                "phases": [
                    {"phase": p.phase, "cache": p.llm.cache_status, "model": p.llm.model}
                    for p in phases
                ],
                "latency_ms": result.latency_ms,
                "score": evaluation.score if evaluation else None,
            },
        )
        return result

    @staticmethod
    def _log_start(
        transcription: str, options: GenerationOptions, route: ModelRoute, *, streaming: bool
    ) -> None:
        # Nunca se registra la transcripción ni el prompt: solo su tamaño y las opciones.
        logger.info(
            "estimation_started",
            extra={
                "streaming": streaming,
                "route": route.describe(),
                "preprocessing": options.preprocessing,
                "example_format": options.example_format,
                "num_examples": options.num_examples,
                "use_examples": options.use_examples,
                "max_tokens": options.max_tokens,
                "allow_fallback": options.allow_fallback,
                "transcription_chars": len(transcription),
            },
        )
