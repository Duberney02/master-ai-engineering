"""`GET /api/v1/estimations[/{id}]`: consulta del historial persistente de estimaciones."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.schemas.history import EstimationDetail, EstimationSummary
from app.services.history import EstimationHistory, HistoryUnavailable, get_history

router = APIRouter()

_UNAVAILABLE = {503: {"description": "Historial desactivado o base de datos no disponible."}}


@router.get("/estimations", response_model=list[EstimationSummary], responses=_UNAVAILABLE)
async def list_estimations(
    limit: int = Query(10, ge=1, le=50, description="Número de estimaciones más recientes."),
    history: EstimationHistory = Depends(get_history),
) -> list[EstimationSummary]:
    try:
        return await history.list_recent(limit)
    except HistoryUnavailable as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from None


@router.get(
    "/estimations/{estimation_id}",
    response_model=EstimationDetail,
    responses={404: {"description": "La estimación no existe."}, **_UNAVAILABLE},
)
async def get_estimation(estimation_id: int, history: EstimationHistory = Depends(get_history)) -> EstimationDetail:
    try:
        detail = await history.get(estimation_id)
    except HistoryUnavailable as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from None
    if detail is None:
        raise HTTPException(status_code=404, detail="Estimation not found")
    return detail
