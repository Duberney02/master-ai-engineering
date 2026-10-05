"""Pipeline de estimación estructurada.

Coordina, en orden: guardrails de entrada, caché exacta, caché semántica, renderizado del
prompt, generación tipada con validación y corrección automática, filtro de fuera de alcance
y almacenamiento en ambas cachés. Se inyecta en los routers con `Depends(get_pipeline)`.
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog
from fastapi import HTTPException

from app.config import Settings, get_settings
from app.prompts.loader import available_versions, render_estimation_prompt
from app.schemas import EstimationRequest, EstimationResult
from app.services.cache import CachedEstimation, EstimationCache, make_result_key
from app.services.guardrails import InputGuardrails
from app.services.llm_service import generate_from_prompts
from app.services.llm_wrapper import Completion, total_cost
from app.services.semantic_cache import SemanticCache
from app.services.validation import (
    ResultValidationError,
    apply_out_of_scope_filter,
    correction_message,
    validate_result,
    validate_text,
)

logger = structlog.get_logger(__name__)

# Máximo de caracteres de la respuesta inválida que se devuelven al modelo al pedir la corrección.
_PREVIOUS_ANSWER_LIMIT = 6000

Generator = Callable[[str, str], Awaitable[Completion]]


@dataclass
class PipelineOutcome:
    result: EstimationResult
    prompt_version: str
    cached: bool
    model: str = ""
    provider: str = ""
    finish_reason: str = "stop"
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    attempts: int = 0
    completion_cache_hit: bool = False
    estimated_cost_usd: float | None = 0.0
    request_cost_usd: float | None = 0.0


class EstimationPipeline:
    def __init__(
        self,
        settings: Settings,
        *,
        guardrails: InputGuardrails | None = None,
        exact_cache: EstimationCache | None = None,
        semantic_cache: SemanticCache | None = None,
        generate: Generator = generate_from_prompts,
    ):
        self.settings = settings
        self.guardrails = guardrails or InputGuardrails(settings)
        self.exact_cache = exact_cache or EstimationCache(settings)
        self.semantic_cache = semantic_cache or SemanticCache(settings)
        self._generate = generate

    @staticmethod
    def validate_version(prompt_version: str) -> None:
        if prompt_version not in available_versions():
            raise HTTPException(
                status_code=422,
                detail=f"Unknown prompt_version. Available: {', '.join(available_versions())}",
            )

    async def check_input(self, request: EstimationRequest, prompt_version: str) -> None:
        """Versión y guardrails; el stream lo ejecuta antes de abrir la respuesta."""
        self.validate_version(prompt_version)
        await self.guardrails.check(request)

    async def run(
        self, request: EstimationRequest, prompt_version: str, *, input_checked: bool = False
    ) -> PipelineOutcome:
        started = time.monotonic()
        if not input_checked:
            await self.check_input(request, prompt_version)

        key = make_result_key(
            request, prompt_version, self.settings.llm_provider, self.settings.effective_model()
        )
        raw = await self.exact_cache.get(key)
        entry = self._valid(CachedEstimation.parse(raw) if raw is not None else None)
        if entry is not None:
            logger.info("estimation_cache_hit", layer="exact", prompt_version=prompt_version)
            return self._cached(entry, prompt_version, started)

        entry = self._valid(await self.semantic_cache.lookup(request, prompt_version))
        if entry is not None:
            await self.exact_cache.set(key, entry.model_dump(mode="json"))
            return self._cached(entry, prompt_version, started)

        outcome = await self._generate_validated(request, prompt_version, started)
        entry = CachedEstimation(
            result=outcome.result, model=outcome.model, provider=outcome.provider
        )
        await self.exact_cache.set(key, entry.model_dump(mode="json"))
        await self.semantic_cache.store(request, prompt_version, entry)
        return outcome

    @staticmethod
    def _valid(entry: CachedEstimation | None) -> CachedEstimation | None:
        """Un resultado cacheado que ya no cumple las reglas de negocio cuenta como fallo."""
        if entry is None:
            return None
        try:
            validate_result(entry.result)
        except ResultValidationError:
            logger.warning("cached_estimation_invalid")
            return None
        return entry

    @staticmethod
    def _cached(entry: CachedEstimation, prompt_version: str, started: float) -> PipelineOutcome:
        return PipelineOutcome(
            result=entry.result, prompt_version=prompt_version, cached=True,
            model=entry.model, provider=entry.provider,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    async def _generate_validated(
        self, request: EstimationRequest, prompt_version: str, started: float
    ) -> PipelineOutcome:
        system, user = render_estimation_prompt(request, version=prompt_version)
        max_attempts = self.settings.validation_max_attempts
        completions: list[Completion] = []
        message = user
        for attempt in range(1, max_attempts + 1):
            completion = await self._generate(system, message)
            completions.append(completion)
            try:
                result = apply_out_of_scope_filter(validate_text(completion.text))
            except ResultValidationError as exc:
                logger.warning(
                    "estimation_validation_failed", attempt=attempt, max_attempts=max_attempts,
                    prompt_version=prompt_version, error=str(exc),
                )
                message = (
                    f"{user}\n\nRespuesta anterior:\n{completion.text[:_PREVIOUS_ANSWER_LIMIT]}\n\n"
                    f"{correction_message(str(exc))}"
                )
                continue
            return self._outcome(result, prompt_version, completions, started)
        logger.error("estimation_validation_exhausted", attempts=max_attempts,
                     prompt_version=prompt_version)
        raise HTTPException(status_code=502, detail="LLM returned an invalid estimation")

    @staticmethod
    def _outcome(
        result: EstimationResult, prompt_version: str, completions: list[Completion], started: float
    ) -> PipelineOutcome:
        last = completions[-1]
        return PipelineOutcome(
            result=result, prompt_version=prompt_version, cached=False,
            model=last.model, provider=last.provider, finish_reason=last.finish_reason,
            input_tokens=sum(c.input_tokens for c in completions),
            output_tokens=sum(c.output_tokens for c in completions),
            latency_ms=int((time.monotonic() - started) * 1000),
            attempts=len(completions),
            completion_cache_hit=all(c.cache_hit for c in completions),
            estimated_cost_usd=total_cost([c.estimated_cost_usd for c in completions]),
            request_cost_usd=total_cost([c.request_cost_usd for c in completions]),
        )


def get_pipeline() -> EstimationPipeline:
    """Dependencia de FastAPI; las pruebas la sustituyen con `app.dependency_overrides`."""
    return EstimationPipeline(get_settings())

