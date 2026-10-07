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

from app.prompts.loader import DEFAULT_PROMPT_VERSION
from app.schemas import (
    MAX_DESCRIPTION_CHARS,
    MIN_DESCRIPTION_CHARS,
    DetailLevel,
    EstimationRequest,
    OutputFormat,
    ProjectType,
    ReferenceProject,
)
from app.schemas.sessions import SessionCreated, SessionEstimationResponse
from app.services.attachments import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS,
    AttachmentError,
    combine_text,
    extract_attachments,
)
from app.services.history import EstimationHistory, get_history
from app.services.session_estimation import SessionEstimationService, get_session_estimation_service
from app.services.sessions import SessionStore, get_session_store

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
                (key, value) for key, value in original.multi_items()
                if not (key == "attachments" and _is_blank(value))
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
        raise HTTPException(422, f"El texto (transcripción y adjuntos) debe tener al menos {MIN_DESCRIPTION_CHARS} caracteres.")
    references = None
    if reference_projects and reference_projects.strip():
        try:
            references = _REFERENCE_PROJECTS.validate_json(reference_projects)
        except ValidationError:
            raise HTTPException(422, "reference_projects debe ser una lista JSON de proyectos de referencia válidos.") from None
    try:
        return EstimationRequest(
            description=text, project_type=project_type, detail_level=detail_level,
            output_format=output_format, reference_projects=references,
        )
    except ValidationError:
        # Sin `detail` de Pydantic: incluiría el texto del usuario.
        raise HTTPException(422, "La solicitud no es válida.") from None


@router.post(
    "/sessions/{session_id}/estimate",
    response_model=SessionEstimationResponse,
    responses={
        400: {"description": "Entrada rechazada por los guardrails: `{reason, message}`."},
        404: {"description": "La sesión no existe o caducó."},
        413: {"description": "Adjuntos o texto demasiado grandes."},
        415: {"description": "Adjunto que no es PDF ni Word."},
        422: {"description": "Parámetros inválidos, texto demasiado corto o adjunto ilegible."},
    },
)
async def estimate_in_session(
    session_id: str,
    transcript: str = Form("", description="Mensaje o transcripción de este turno."),
    attachments: list[UploadFile] = File(default=[], description="Adjuntos PDF o Word (.docx)."),
    project_type: ProjectType = Form(...),
    detail_level: DetailLevel = Form(DetailLevel.MEDIUM),
    output_format: OutputFormat = Form(OutputFormat.PHASES_TABLE),
    reference_projects: str | None = Form(None, description="Lista JSON de proyectos de referencia."),
    prompt_version: str = Form(DEFAULT_PROMPT_VERSION, max_length=10),
    store: SessionStore = Depends(get_session_store),
    service: SessionEstimationService = Depends(get_session_estimation_service),
    history: EstimationHistory = Depends(get_history),
) -> SessionEstimationResponse:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, SESSION_NOT_FOUND)

    extracted = await extract_attachments(await _read_attachments(attachments))
    request = _request(
        combine_text(transcript, extracted), project_type, detail_level, output_format, reference_projects
    )

    requested_at = datetime.now(timezone.utc)
    result = await service.estimate(session, request, prompt_version)
    store.touch(session)
    outcome = result.outcome
    estimation_id = await history.save(request, outcome, requested_at)
    return SessionEstimationResponse(
        result=outcome.result, prompt_version=outcome.prompt_version, cached=outcome.cached,
        cache_source=outcome.cache_source, estimation_id=estimation_id, metrics=outcome.metrics(),
        session_id=session.session_id, project_metadata=result.metadata,
        turn_count=result.turn_count, max_turns=session.history.max_turns,
    )
