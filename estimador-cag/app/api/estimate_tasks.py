"""`POST /v1/estimate/tasks/hours`: horas por tarea desde el corpus histórico (Sesión 10).

Recibe módulos con tareas (la salida de `POST /v1/estimate/stages/structure` sirve tal cual) y devuelve, por tarea, las
horas por consenso ponderado de los vecinos históricos, su fiabilidad y los vecinos usados; una tarea sin vecino por
debajo del umbral vuelve con `has_match=false` y sin horas. Transporte fino: validación en `TaskHoursRequest` (422),
clave en `require_estimate_key` (401), límite en el decorador (429) y errores saneados (502 genérico; el detalle va al
log).
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.rate_limiting import STAGES_LIMIT, limiter
from app.api.security import require_estimate_key
from app.dependencies import get_task_hours_estimator
from app.generation.rag.observability import log_stage
from app.generation.rag.schemas import TaskHoursRequest, TaskHoursResult
from app.generation.rag.task_hours import TaskHoursEstimator

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1/estimate/tasks", tags=["estimate-tasks"], dependencies=[Depends(require_estimate_key)])

_RESPONSES = {
    401: {"description": "Clave de API ausente o no válida."},
    429: {"description": "Límite de peticiones superado (`Retry-After`)."},
    502: {"description": "Fallo de la búsqueda o de los embeddings (mensaje genérico; detalle en el log)."},
}


@router.post("/hours", response_model=TaskHoursResult, responses=_RESPONSES)
@limiter.limit(STAGES_LIMIT)
async def task_hours(
    request: Request, payload: TaskHoursRequest, estimator: TaskHoursEstimator = Depends(get_task_hours_estimator)
) -> TaskHoursResult:
    """Horas de cada tarea por consenso ponderado de sus vecinos históricos (`chunk_type="historical_task"`)."""
    tasks = sum(len(module.tasks) for module in payload.modules)
    try:
        with log_stage("task_hours", tasks=tasks):
            return await estimator.estimate_all(payload.modules)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudieron estimar las horas por tarea.") from exc
