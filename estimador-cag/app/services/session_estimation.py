"""Estimación con memoria conversacional.

Orquesta un turno de una sesión: guardrails de entrada, mensajes del LLM con la ventana de la
sesión (`Session.to_messages_list`), generación con validación y corrección automática —reutilizando
las reglas de `app.services.validation`—, actualización de los metadatos con una llamada adicional al
LLM y, solo si todo ha ido bien, confirmación del turno en la sesión.

La caché exacta y la semántica del pipeline sin sesión no se usan aquí: su resultado depende del
historial. La caché de completions del wrapper sí aplica, con el historial completo en su clave.
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog
from fastapi import HTTPException
from pydantic import ValidationError

from app.config import Settings, Task, get_settings
from app.prompts.loader import (
    render_metadata_extraction_prompt,
    render_system_prompt,
    render_user_prompt,
)
from app.schemas import EstimationRequest, EstimationResult
from app.services.anchors import build_anchor_detector
from app.services.audience import Audience, AudienceResolution, resolve_audience
from app.services.compression import CompressionPolicy
from app.services.guardrails import InputGuardrails
from app.services.llm_service import generate_from_messages
from app.services.llm_wrapper import Completion
from app.services.pipeline import EstimationPipeline, PipelineOutcome
from app.services.sessions import Message, ProjectMetadata, Session
from app.services.summarizer import LLMSummarizer
from app.services.validation import (
    ResultValidationError,
    apply_out_of_scope_filter,
    correction_message,
    extract_json,
    validate_text,
)

logger = structlog.get_logger(__name__)

# Respuesta inválida que se devuelve al modelo al pedir la corrección (como en el pipeline).
_PREVIOUS_ANSWER_LIMIT = 6000
# Texto del usuario y de la estimación que ve la llamada de extracción de metadatos.
_METADATA_INPUT_CHARS = 20_000
_METADATA_SUMMARY_CHARS = 2000
# La salida es un JSON pequeño.
_METADATA_MAX_TOKENS = 800

Generator = Callable[..., Awaitable[Completion]]


def _is_valid_estimation(text: str) -> bool:
    try:
        validate_text(text)
    except ResultValidationError:
        return False
    return True


def parse_metadata(text: str) -> ProjectMetadata:
    """Metadatos de la respuesta del modelo; lanza `ResultValidationError` si no son válidos."""
    try:
        return ProjectMetadata.model_validate(extract_json(text))
    except ValidationError:
        raise ResultValidationError("El JSON no cumple el esquema de metadatos.") from None


def _is_valid_metadata(text: str) -> bool:
    try:
        parse_metadata(text)
    except ResultValidationError:
        return False
    return True


@dataclass
class Draft:
    """Estimación generada y validada, todavía sin confirmar en la sesión."""

    result: EstimationResult
    text: str
    user: str
    completions: list[Completion]


@dataclass
class Feedback:
    """Revisión del crítico para la regeneración: respuesta anterior del actor y mensaje con los defectos."""

    previous_text: str
    message: str


@dataclass
class SessionOutcome:
    outcome: PipelineOutcome
    metadata: ProjectMetadata
    turn_count: int
    audience: Audience = Audience.DEFAULT
    audience_rule: str = "no_match"


class SessionEstimationService:
    def __init__(
        self,
        settings: Settings,
        *,
        guardrails: InputGuardrails | None = None,
        generate: Generator = generate_from_messages,
        compression: CompressionPolicy | None = None,
    ):
        self.settings = settings
        self.guardrails = guardrails or InputGuardrails(settings)
        self._generate = generate
        self.compression = compression or CompressionPolicy(
            build_anchor_detector(settings, generate), LLMSummarizer(settings, generate=generate)
        )

    def _model_options(self, task: Task) -> dict[str, str]:
        """`model=` solo cuando la tarea tiene un modelo propio; si no, el generador usa el global."""
        model = getattr(self.settings, f"{task}_model")
        return {"model": model} if model else {}

    async def check_input(self, request: EstimationRequest, prompt_version: str) -> None:
        EstimationPipeline.validate_version(prompt_version)
        await self.guardrails.check(request)

    @staticmethod
    def audience_transcript(session: Session, request: EstimationRequest) -> str:
        """Texto sobre el que se resuelve la audiencia: el turno actual y lo que la sesión recuerda
        (resumen, anclas y mensajes de usuario recientes)."""
        history = session.history
        remembered = [history.summary, *(a.user for a in history.anchors), *(user for user, _ in history.turns)]
        return "\n".join([request.description, *filter(None, remembered)])

    def resolve_audience(
        self, session: Session, request: EstimationRequest, tier: Audience | None
    ) -> AudienceResolution:
        resolution = resolve_audience(self.audience_transcript(session, request), session.metadata, tier)
        logger.info("audience_resolved", audience=resolution.audience.value, audience_rule=resolution.rule)
        return resolution

    async def estimate(
        self, session: Session, request: EstimationRequest, prompt_version: str, tier: Audience | None = None
    ) -> SessionOutcome:
        await self.check_input(request, prompt_version)
        # Un turno por sesión a la vez: el siguiente ve el historial y los metadatos ya actualizados.
        async with session.lock:
            started = time.monotonic()
            resolution = self.resolve_audience(session, request, tier)
            draft = await self.draft(session, request, prompt_version, resolution)
            return await self.commit(session, request, prompt_version, draft, resolution, started)

    async def draft(
        self,
        session: Session,
        request: EstimationRequest,
        prompt_version: str,
        resolution: AudienceResolution,
        feedback: Feedback | None = None,
    ) -> Draft:
        """Genera y valida una estimación sin modificar la sesión (el llamador debe tener su cerrojo).

        `feedback` añade la respuesta anterior del actor y el mensaje de revisión del crítico solo a esta
        llamada; nunca llegan al historial. La corrección automática por validación funciona igual."""
        user = render_user_prompt(request, prompt_version)
        base_messages = session.to_messages_list(
            lambda metadata: render_system_prompt(request, prompt_version, metadata, resolution.audience.value),
            user,
        )
        if feedback is not None:
            base_messages = [
                *base_messages,
                {"role": "assistant", "content": feedback.previous_text[:_PREVIOUS_ANSWER_LIMIT]},
                {"role": "user", "content": feedback.message},
            ]
        messages = base_messages
        completions: list[Completion] = []
        result = None
        for attempt in range(1, self.settings.validation_max_attempts + 1):
            completion = await self._generate(messages, accept=_is_valid_estimation, **self._model_options("estimator"))
            completions.append(completion)
            try:
                result = apply_out_of_scope_filter(validate_text(completion.text))
            except ResultValidationError as exc:
                logger.warning(
                    "session_validation_failed",
                    attempt=attempt,
                    max_attempts=self.settings.validation_max_attempts,
                    error=str(exc),
                )
                # La corrección va solo en esta llamada: el historial guarda únicamente turnos válidos.
                messages = [
                    *base_messages,
                    {"role": "assistant", "content": completion.text[:_PREVIOUS_ANSWER_LIMIT]},
                    {"role": "user", "content": correction_message(str(exc))},
                ]
                continue
            break
        if result is None:
            logger.error("session_validation_exhausted", attempts=len(completions))
            raise HTTPException(status_code=502, detail="LLM returned an invalid estimation")
        return Draft(result=result, text=completions[-1].text, user=user, completions=completions)

    async def commit(
        self,
        session: Session,
        request: EstimationRequest,
        prompt_version: str,
        draft: Draft,
        resolution: AudienceResolution,
        started: float,
        extra_completions: list[Completion] | None = None,
    ) -> SessionOutcome:
        """Confirma el borrador como turno de la sesión: metadatos, historial, audiencia y compresión.

        `extra_completions` (borradores previos, revisiones del crítico) suman a las métricas del turno."""
        metadata, metadata_completions = await self._updated_metadata(session, request, draft.result.summary)
        session.record_turn(draft.user, draft.text, metadata)
        self._remember_audience(session, resolution)
        # Política de compresión tras cada turno: anclas y resumen de lo que sale de la ventana.
        compression = await self.compression.apply(session.history)
        outcome = EstimationPipeline._outcome(
            draft.result,
            prompt_version,
            [*metadata_completions, *compression.completions, *(extra_completions or []), *draft.completions],
            started,
        )
        outcome.attempts = len(draft.completions)
        logger.info(
            "session_estimation_completed",
            prompt_version=prompt_version,
            turns=len(session.history),
            attempts=outcome.attempts,
            metadata_updated=bool(metadata_completions),
            anchors=len(session.history.anchors),
            summary_chars=len(session.history.summary),
        )
        return SessionOutcome(
            outcome=outcome,
            metadata=metadata,
            turn_count=len(session.history),
            audience=resolution.audience,
            audience_rule=resolution.rule,
        )

    @staticmethod
    def _remember_audience(session: Session, resolution: AudienceResolution) -> None:
        session.audience = resolution.audience.value
        session.audience_rule = resolution.rule

    async def _updated_metadata(
        self, session: Session, request: EstimationRequest, estimation_summary: str
    ) -> tuple[ProjectMetadata, list[Completion]]:
        """Llamada adicional al LLM que devuelve los metadatos actualizados (JSON validado).

        Nunca falla la estimación: ante cualquier error se conservan los metadatos anteriores."""
        current = session.metadata
        system, user = render_metadata_extraction_prompt(
            current, request.description[:_METADATA_INPUT_CHARS], estimation_summary[:_METADATA_SUMMARY_CHARS]
        )
        messages: list[Message] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            completion = await self._generate(
                messages,
                accept=_is_valid_metadata,
                max_tokens=_METADATA_MAX_TOKENS,
                **self._model_options("metadata"),
            )
        except Exception as exc:
            logger.warning("metadata_extraction_failed", error_type=type(exc).__name__)
            return current, []
        try:
            return current.merge(parse_metadata(completion.text)), [completion]
        except ResultValidationError as exc:
            logger.warning("metadata_extraction_invalid", error=str(exc))
            return current, [completion]


def get_session_estimation_service() -> SessionEstimationService:
    """Dependencia de FastAPI; las pruebas la sustituyen con `app.dependency_overrides`."""
    return SessionEstimationService(get_settings())


__all__ = [
    "SessionEstimationService",
    "SessionOutcome",
    "get_session_estimation_service",
    "parse_metadata",
]
