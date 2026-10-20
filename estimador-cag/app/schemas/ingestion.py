"""Esquemas HTTP de la ingesta: dos endpoints (POST y GET) y tres formas de respuesta."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal["pending", "running", "completed", "failed"]


class IngestionRunRequest(BaseModel):
    """Cuerpo de `POST /api/v1/ingestion/runs`."""

    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "Nombre de una fuente `include` del catálogo. Cualquier otra (desconocida, `review` o `exclude`) "
            "se rechaza: 404 si no existe, 400 si no está incluida."
        ),
    )


class IngestionRunResponse(BaseModel):
    """Respuesta de `POST /api/v1/ingestion/runs` (HTTP 202)."""

    job_id: uuid.UUID
    source_name: str
    status: JobStatus


class IngestionJobView(BaseModel):
    """Respuesta de `GET /api/v1/ingestion/jobs/{job_id}`."""

    job_id: uuid.UUID
    source_name: str
    status: JobStatus
    documents_count: int
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None
