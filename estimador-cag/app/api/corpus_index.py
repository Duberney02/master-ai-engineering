"""`/embeddings/index/*`: expansión incremental del corpus y estadísticas del índice (Sesión 11).

Router fino: valida el lote (422), registra el trabajo, lanza `CorpusExpansionService.run` como `BackgroundTask` y
responde `202` con el `job_id`; `GET .../jobs/{id}` consulta su progreso y `GET .../stats` el tamaño del índice por
colección. Errores saneados: sin embedder disponible, `500` genérico; el detalle va al log.
"""

import uuid

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_corpus_expansion_service, get_rag_embedder
from app.foundation.persistence.database import get_session
from app.foundation.persistence.repositories.jobs import JobsRepository
from app.generation.rag.corpus_expansion import JOB_SOURCE_NAME, CorpusExpansionService
from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.schemas import IndexJobView, IndexRunRequest, IndexRunResponse, IndexStatsResponse

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/embeddings/index", tags=["corpus-index"])


@router.post(
    "/runs",
    response_model=IndexRunResponse,
    status_code=202,
    responses={
        500: {"description": "Sin embedder disponible (mensaje genérico; detalle en el log)."},
        503: {"description": "No hay base de datos configurada (`DATABASE_URL`)."},
    },
)
async def create_index_run(
    request: IndexRunRequest,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    service: CorpusExpansionService = Depends(get_corpus_expansion_service),
    embedder: OpenAIEmbedder | None = Depends(get_rag_embedder),
) -> IndexRunResponse:
    """Registra un trabajo y amplía el corpus en segundo plano; los presupuestos ya ingestados se omiten."""
    if embedder is None:
        logger.error("corpus_expansion_rejected", reason="embedder_unavailable")
        raise HTTPException(status_code=500, detail="No se pudo iniciar la expansión del corpus.")
    job = await JobsRepository(session).create(source_name=JOB_SOURCE_NAME)
    background.add_task(service.run, job.job_id, request)
    logger.info("corpus_expansion_accepted", job_id=str(job.job_id), documents_total=len(request.budgets))
    return IndexRunResponse(job_id=str(job.job_id), documents_total=len(request.budgets), status=job.status)


@router.get(
    "/jobs/{job_id}",
    response_model=IndexJobView,
    responses={404: {"description": "El trabajo no existe."}, 503: {"description": "Seguimiento no configurado."}},
)
async def get_index_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> IndexJobView:
    job = await JobsRepository(session).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return IndexJobView(
        job_id=str(job.job_id),
        status=job.status,
        documents_processed=job.documents_count,
        error_message=job.error_message,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get("/stats", response_model=IndexStatsResponse, responses={503: {"description": "Sin base de datos."}})
async def get_index_stats(session: AsyncSession = Depends(get_session)) -> IndexStatsResponse:
    """Documentos, chunks e índice HNSW por colección (`budget`, `transcript`, `technical_doc`)."""
    return await CorpusExpansionService.stats(session)
