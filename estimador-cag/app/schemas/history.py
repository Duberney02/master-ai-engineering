"""Contrato de lectura del historial de estimaciones (`GET /api/v1/estimations[/{id}]`)."""

from datetime import datetime

from pydantic import BaseModel

from app.schemas.project_estimation import (
    CacheSource,
    CallMetrics,
    DetailLevel,
    EstimationResult,
    OutputFormat,
    ProjectType,
    ReferenceProject,
)

EXCERPT_CHARS = 200


class EstimationOptions(BaseModel):
    project_type: ProjectType
    detail_level: DetailLevel
    output_format: OutputFormat
    reference_projects: list[ReferenceProject] | None = None


class EstimationSummary(BaseModel):
    """Elemento del listado: sin la descripción completa, que puede tener 80 000 caracteres."""

    id: int
    requested_at: datetime
    project_type: ProjectType
    detail_level: DetailLevel
    output_format: OutputFormat
    prompt_version: str
    cache_source: CacheSource
    confidence_pct: int
    total_cost_eur: float
    total_duration_weeks: float
    out_of_scope: bool
    description_excerpt: str


class EstimationDetail(BaseModel):
    id: int
    requested_at: datetime
    completed_at: datetime
    description: str
    options: EstimationOptions
    result: EstimationResult
    prompt_version: str
    cached: bool
    cache_source: CacheSource
    model: str
    provider: str
    metrics: CallMetrics | None = None
    conversation_id: str | None = None
    metadata_snapshot: dict | None = None
