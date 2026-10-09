"""`POST /api/v1/sessions[/{id}/estimate]`: estimaciones con memoria conversacional y adjuntos.

El router traduce HTTP (multipart, errores): la orquestación vive en `SessionEstimationService`, la
extracción de adjuntos en `app.services.attachments` y el estado en `SessionStore`.
"""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.datastructures import FormData
from fastapi.routing import APIRoute
from pydantic import TypeAdapter, ValidationError

from app.schemas import (
    MAX_DESCRIPTION_CHARS,
    MIN_DESCRIPTION_CHARS,
    DetailLevel,
    EstimationRequest,
    OutputFormat,
    ProjectType,
    ReferenceProject,
)
from app.schemas.acb import AcbEstimationResponse
from app.schemas.sessions import SessionCreated, SessionEstimationResponse, SessionState
from app.services.acb import ActorCriticBoss, get_actor_critic_boss
from app.services.attachments import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS,
    AttachmentError,
    combine_text,
    extract_attachments,
)
from app.services.audience import Audience
from app.services.history import EstimationHistory, get_history
from app.services.session_estimation import SessionEstimationService, SessionOutcome, get_session_estimation_service
from app.services.sessions import Session, SessionStore, get_session_store

logger = structlog.get_logger(__name__)

_REFERENCE_PROJECTS = TypeAdapter(list[ReferenceProject])


class _BlankFilePartsRequest(Request):
    """Descarta del formulario las partes `attachments` vacías.

    Sin archivo elegido, los navegadores y Rails (`file_field multiple`) envían igualmente un campo
    `attachments` vacío, que llega como texto y haría fallar la validación de `list[UploadFile]`.
    """

    async def form(self, **kwargs) -> FormData:
        if not hasattr(self, "_form") or self._form is None:
            original = await super().form(**kwargs)
            kept = [
                (key, value) for key, value in original.multi_items() if not (key == "attachments" and _is_blank(value))
            ]
            self._form = FormData(kept)
        return self._form


def _is_blank(value: object) -> bool:
    if isinstance(value, str):
        return not value.strip()
    return isinstance(value, UploadFile) and not value.filename


class _BlankFilePartsRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def route_handler(request: Request) -> Response:
            return await handler(_BlankFilePartsRequest(request.scope, request.receive))

        return route_handler


router = APIRouter(route_class=_BlankFilePartsRoute)
SESSION_NOT_FOUND = "Session not found or expired"


@router.post("/sessions", response_model=SessionCreated, status_code=201)
async def create_session(store: SessionStore = Depends(get_session_store)) -> SessionCreated:
    """Crea una sesión vacía. Vive en memoria: se pierde al reiniciar el servicio o al caducar."""
    session = store.create()
    logger.info("session_created", sessions=len(store))
    return SessionCreated(session_id=session.session_id)


async def _read_attachments(files: list[UploadFile]) -> list[tuple[str | None, bytes]]:
    # Un `UploadFile` sin nombre es la parte vacía que algunos clientes envían sin archivo elegido.
    chosen = [file for file in files if file.filename]
    if len(chosen) > MAX_ATTACHMENTS:
        raise AttachmentError(413, f"Se admiten como máximo {MAX_ATTACHMENTS} adjuntos por solicitud.")
    contents = []
    for file in chosen:
        data = await file.read(MAX_ATTACHMENT_BYTES + 1)
        contents.append((file.filename, data))
    return contents


def _request(
    text: str,
    project_type: ProjectType,
    detail_level: DetailLevel,
    output_format: OutputFormat,
    reference_projects: str | None,
) -> EstimationRequest:
    if len(text) > MAX_DESCRIPTION_CHARS:
        raise HTTPException(413, f"El texto (transcripción y adjuntos) supera los {MAX_DESCRIPTION_CHARS} caracteres.")
    if len(text) < MIN_DESCRIPTION_CHARS:
        raise HTTPException(
            422, f"El texto (transcripción y adjuntos) debe tener al menos {MIN_DESCRIPTION_CHARS} caracteres."
        )
    references = None
    if reference_projects and reference_projects.strip():
        try:
            references = _REFERENCE_PROJECTS.validate_json(reference_projects)
        except ValidationError:
            raise HTTPException(
                422, "reference_projects debe ser una lista JSON de proyectos de referencia válidos."
            ) from None
    try:
        return EstimationRequest(
            description=text,
            project_type=project_type,
            detail_level=detail_level,
            output_format=output_format,
            reference_projects=references,
        )
    except ValidationError:
        # Sin `detail` de Pydantic: incluiría el texto del usuario.
        raise HTTPException(422, "La solicitud no es válida.") from None


@router.get(
    "/sessions/{session_id}",
    response_model=SessionState,
    responses={404: {"description": "La sesión no existe o caducó."}},
)
async def get_session_state(session_id: str, store: SessionStore = Depends(get_session_store)) -> SessionState:
    """Estado de la sesión (ventana, anclas, resumen, metadatos y última audiencia); no estima ni llama al LLM."""
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, SESSION_NOT_FOUND)
    history = session.history
    return SessionState(
        session_id=session.session_id,
        recent_message_count=2 * len(history),
        max_turns=history.max_turns,
        project_metadata=session.metadata,
        anchored_message_count=2 * len(history.anchors),
        summary_length=len(history.summary),
        last_audience=session.audience,
        last_audience_rule=session.audience_rule,
    )


def parse_tier(tier: str | None) -> Audience | None:
    """`tier` opcional del formulario: vacío equivale a no indicarlo; un valor desconocido es un 422."""
    if tier is None or not tier.strip():
        return None
    try:
        return Audience(tier.strip().lower())
    except ValueError:
        allowed = ", ".join(a.value for a in Audience)
        raise HTTPException(422, f"tier debe ser uno de: {allowed}.") from None


_ESTIMATE_RESPONSES = {
    400: {"description": "Entrada rechazada por los guardrails: `{reason, message}`."},
    404: {"description": "La sesión no existe o caducó."},
    413: {"description": "Adjuntos o texto demasiado grandes."},
    415: {"description": "Adjunto que no es PDF ni Word."},
    422: {"description": "Parámetros inválidos, texto demasiado corto o adjunto ilegible."},
}


async def _prepare(
    store: SessionStore,
    session_id: str,
    transcript: str,
    attachments: list[UploadFile],
    project_type: ProjectType,
    detail_level: DetailLevel,
    output_format: OutputFormat,
    reference_projects: str | None,
    tier: str | None,
) -> tuple[Session, EstimationRequest, Audience | None]:
    """Sesión, solicitud validada y audiencia explícita: lo común a las estimaciones de sesión."""
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, SESSION_NOT_FOUND)
    audience = parse_tier(tier)
    extracted = await extract_attachments(await _read_attachments(attachments))
    request = _request(
        combine_text(transcript, extracted), project_type, detail_level, output_format, reference_projects
    )
    return session, request, audience


def _response_fields(session: Session, result: SessionOutcome, estimation_id: int | None) -> dict:
    outcome = result.outcome
    return dict(
        result=outcome.result,
        prompt_version=outcome.prompt_version,
        cached=outcome.cached,
        cache_source=outcome.cache_source,
        estimation_id=estimation_id,
        metrics=outcome.metrics(),
        session_id=session.session_id,
        project_metadata=result.metadata,
        turn_count=result.turn_count,
        max_turns=session.history.max_turns,
        audience=result.audience,
        audience_rule=result.audience_rule,
    )


async def _save(
    history: EstimationHistory,
    session: Session,
    request: EstimationRequest,
    result: SessionOutcome,
    requested_at: datetime,
) -> int | None:
    return await history.save(
        request,
        result.outcome,
        requested_at,
        conversation_id=session.session_id,
        metadata_snapshot=result.metadata.model_dump(mode="json"),
    )


@router.post("/sessions/{session_id}/estimate", response_model=SessionEstimationResponse, responses=_ESTIMATE_RESPONSES)
async def estimate_in_session(
    session_id: str,
    transcript: str = Form("", description="Mensaje o transcripción de este turno."),
    attachments: list[UploadFile] = File(default=[], description="Adjuntos PDF o Word (.docx)."),
    project_type: ProjectType = Form(...),
    detail_level: DetailLevel = Form(DetailLevel.MEDIUM),
    output_format: OutputFormat = Form(OutputFormat.PHASES_TABLE),
    reference_projects: str | None = Form(None, description="Lista JSON de proyectos de referencia."),
    prompt_version: str | None = Form(
        None, max_length=10, description="Versión del prompt; por defecto CONVERSATION_PROMPT_VERSION."
    ),
    tier: str | None = Form(
        None, description="Audiencia: executive, pm, developer o default; prevalece sobre las reglas."
    ),
    store: SessionStore = Depends(get_session_store),
    service: SessionEstimationService = Depends(get_session_estimation_service),
    history: EstimationHistory = Depends(get_history),
) -> SessionEstimationResponse:
    session, request, audience = await _prepare(
        store,
        session_id,
        transcript,
        attachments,
        project_type,
        detail_level,
        output_format,
        reference_projects,
        tier,
    )
    requested_at = datetime.now(timezone.utc)
    result = await service.estimate(
        session, request, prompt_version or service.settings.conversation_prompt_version, audience
    )
    store.touch(session)
    estimation_id = await _save(history, session, request, result, requested_at)
    return SessionEstimationResponse(**_response_fields(session, result, estimation_id))


@router.post(
    "/sessions/{session_id}/estimate-acb",
    response_model=AcbEstimationResponse,
    responses={**_ESTIMATE_RESPONSES, 502: {"description": "El actor no produjo una estimación válida."}},
)
async def estimate_in_session_with_review(
    session_id: str,
    transcript: str = Form("", description="Mensaje o transcripción de este turno."),
    attachments: list[UploadFile] = File(default=[], description="Adjuntos PDF o Word (.docx)."),
    project_type: ProjectType = Form(...),
    detail_level: DetailLevel = Form(DetailLevel.MEDIUM),
    output_format: OutputFormat = Form(OutputFormat.PHASES_TABLE),
    reference_projects: str | None = Form(None, description="Lista JSON de proyectos de referencia."),
    prompt_version: str | None = Form(
        None, max_length=10, description="Versión del prompt; por defecto CONVERSATION_PROMPT_VERSION."
    ),
    tier: str | None = Form(
        None, description="Audiencia: executive, pm, developer o default; prevalece sobre las reglas."
    ),
    store: SessionStore = Depends(get_session_store),
    orchestrator: ActorCriticBoss = Depends(get_actor_critic_boss),
    history: EstimationHistory = Depends(get_history),
) -> AcbEstimationResponse:
    """Como `estimate`, pero un crítico independiente revisa la estimación y el Boss decide si aceptarla,
    regenerarla con el feedback o devolverla con reservas. La respuesta incluye la traza de auditoría."""
    session, request, audience = await _prepare(
        store,
        session_id,
        transcript,
        attachments,
        project_type,
        detail_level,
        output_format,
        reference_projects,
        tier,
    )
    requested_at = datetime.now(timezone.utc)
    version = prompt_version or orchestrator.service.settings.conversation_prompt_version
    acb = await orchestrator.run(session, request, version, audience)
    store.touch(session)
    estimation_id = await _save(history, session, request, acb.session_outcome, requested_at)
    return AcbEstimationResponse(**_response_fields(session, acb.session_outcome, estimation_id), audit_trace=acb.trace)
