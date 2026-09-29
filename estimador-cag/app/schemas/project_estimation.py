"""Contrato tipado entre clientes y servicio IA para `POST /api/v1/estimate`.

Lo comparten el servidor y el cliente Streamlit: ambos importan estas clases
desde `app.schemas`.
"""

from enum import Enum

from pydantic import BaseModel, Field


class ProjectType(str, Enum):
    MOBILE_APP = "mobile_app"
    WEB_SAAS = "web_saas"
    INTERNAL_TOOL = "internal_tool"
    DATA_PIPELINE = "data_pipeline"


class DetailLevel(str, Enum):
    SUMMARY = "summary"
    MEDIUM = "medium"
    DETAILED = "detailed"


class OutputFormat(str, Enum):
    PHASES_TABLE = "phases_table"
    LINE_ITEMS = "line_items"
    NARRATIVE = "narrative"


MAX_REFERENCE_PROJECTS = 5


class ReferenceProject(BaseModel):
    """Proyecto ya entregado que sirve como referencia de calibración."""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    actual_hours: float = Field(gt=0, le=100_000, allow_inf_nan=False)


class EstimationRequest(BaseModel):
    description: str = Field(min_length=20, max_length=2000)
    project_type: ProjectType
    detail_level: DetailLevel
    output_format: OutputFormat
    reference_projects: list[ReferenceProject] | None = Field(
        default=None,
        max_length=MAX_REFERENCE_PROJECTS,
        description="Proyectos similares ya entregados; se incluyen en el prompt si se envían.",
    )


class EstimationResponse(BaseModel):
    text: str
    prompt_version: str


class StreamUsage(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class EstimationStreamMetadata(BaseModel):
    """Evento `metadata` de `POST /api/v1/estimate/stream`, emitido tras el último `token`."""

    prompt_version: str
    model: str
    provider: str
    finish_reason: str
    usage: StreamUsage
    latency_ms: int = Field(ge=0)
    cache_hit: bool
    estimated_cost_usd: float | None
    request_cost_usd: float | None
