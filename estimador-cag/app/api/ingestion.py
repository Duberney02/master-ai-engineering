"""`POST /ingestion/runs` y `GET /ingestion/jobs/{job_id}` (montados bajo `/api/v1`).

El router es deliberadamente fino: valida la fuente contra el catálogo, registra el trabajo, lanza el
orquestador como `BackgroundTask` y responde 202. Toda la lógica de ingesta vive en
`app.ingestion.orchestrator`; el router nunca importa parsers.
"""

import uuid

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_catalog, get_filesystem_loader, get_parser_registry
from app.domain.schemas.ingestion import IngestionJobView, IngestionRunRequest, IngestionRunResponse
from app.foundation.persistence.database import SessionLocal, get_session
from app.foundation.persistence.repositories.jobs import JobsRepository
from app.ingestion.catalog.models import CatalogDecision, DataCatalog
from app.ingestion.loaders.filesystem import FileSystemLoader
from app.ingestion.orchestrator import ingest_source
from app.ingestion.parsers.registry import ParserRegistry

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


async def _run_in_background(
    *,
    job_id: uuid.UUID,
    source_name: str,
    catalog: DataCatalog,
    loader: FileSystemLoader,
    registry: ParserRegistry,
) -> None:
    """Cuerpo de la tarea en segundo plano. Abre su propia sesión: la de la solicitud ya está cerrada."""
    async with SessionLocal() as session:
        try:
            await ingest_source(
                catalog=catalog,
                source_name=source_name,
                loader=loader,
                registry=registry,
                jobs_repo=JobsRepository(session),
                job_id=job_id,
            )
        except Exception as exc:
            # El orquestador ya dejó el trabajo en `failed`; aquí solo se registra.
            logger.error(
                "ingestion_background_failed",
                job_id=str(job_id),
                source_name=source_name,
                error_type=type(exc).__name__,
            )


@router.post(
    "/runs",
    response_model=IngestionRunResponse,
    status_code=202,
    responses={
        400: {"description": "La fuente existe pero su decisión es `review` o `exclude`."},
        404: {"description": "La fuente no existe en el catálogo."},
        503: {"description": "El seguimiento de ingesta (PostgreSQL) no está configurado."},
    },
)
async def create_ingestion_run(
    request: IngestionRunRequest,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    catalog: DataCatalog = Depends(get_catalog),
    loader: FileSystemLoader = Depends(get_filesystem_loader),
    registry: ParserRegistry = Depends(get_parser_registry),
) -> IngestionRunResponse:
    source = catalog.find(request.source_name)
    if source is None:
        raise HTTPException(
            status_code=404,
            detail={"reason": "unknown_source", "source_name": request.source_name},
        )
    if source.decision is not CatalogDecision.INCLUDE:
        raise HTTPException(
            status_code=400,
            detail={
                "reason": "source_not_included",
                "source_name": request.source_name,
                "decision": source.decision.value,
                "decision_reason": source.decision_reason,
            },
        )

    job = await JobsRepository(session).create(source_name=request.source_name)

    background.add_task(
        _run_in_background,
        job_id=job.job_id,
        source_name=request.source_name,
        catalog=catalog,
        loader=loader,
        registry=registry,
    )
    return IngestionRunResponse(job_id=job.job_id, source_name=job.source_name, status=job.status)


@router.get(
    "/jobs/{job_id}",
    response_model=IngestionJobView,
    responses={404: {"description": "El trabajo no existe."}, 503: {"description": "Seguimiento no configurado."}},
)
async def get_ingestion_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> IngestionJobView:
    job = await JobsRepository(session).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return IngestionJobView(
        job_id=job.job_id,
        source_name=job.source_name,
        status=job.status,
        documents_count=job.documents_count,
        error_message=job.error_message,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )
