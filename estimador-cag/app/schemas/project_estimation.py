"""Contrato tipado entre clientes y servicio IA para `POST /api/v1/estimate`.

Lo comparten el servidor y el cliente Streamlit: ambos importan estas clases
desde `app.schemas`.
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, computed_field


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
# Una transcripción completa de reunión cabe en ~20 000 tokens.
MIN_DESCRIPTION_CHARS = 20
MAX_DESCRIPTION_CHARS = 80_000

CacheSource = Literal["none", "exact", "semantic"]


class ReferenceProject(BaseModel):
    """Proyecto ya entregado que sirve como referencia de calibración."""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=500)
    actual_hours: float = Field(gt=0, le=100_000, allow_inf_nan=False)


class EstimationRequest(BaseModel):
    description: str = Field(
        min_length=MIN_DESCRIPTION_CHARS, max_length=MAX_DESCRIPTION_CHARS
    )
    project_type: ProjectType
    detail_level: DetailLevel
    output_format: OutputFormat
    reference_projects: list[ReferenceProject] | None = Field(
        default=None,
        max_length=MAX_REFERENCE_PROJECTS,
        description="Proyectos similares ya entregados; se incluyen en el prompt si se envían.",
    )


# Por debajo de esta confianza (%) la estimación se declara fuera de alcance.
OUT_OF_SCOPE_CONFIDENCE = 30
OUT_OF_SCOPE_PREFIX = "Out of scope:"


class Phase(BaseModel):
    """Fase del proyecto con su duración y coste."""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    duration_weeks: float = Field(gt=0, le=520, allow_inf_nan=False)
    cost_eur: float = Field(ge=0, le=100_000_000, allow_inf_nan=False)


class EstimationResult(BaseModel):
    """Estimación estructurada; las reglas de negocio se validan en `app.services.validation`."""

    summary: str = Field(min_length=1, max_length=2000)
    confidence_pct: int = Field(ge=0, le=100)
    phases: list[Phase] = Field(min_length=1, max_length=30)
    total_duration_weeks: float = Field(gt=0, le=2600, allow_inf_nan=False)
    total_cost_eur: float = Field(ge=0, le=100_000_000, allow_inf_nan=False)

    @computed_field
    @property
    def out_of_scope(self) -> bool:
        return self.confidence_pct < OUT_OF_SCOPE_CONFIDENCE


class StreamUsage(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class CallMetrics(BaseModel):
    """Métricas de la llamada que produjo (o sirvió desde caché) una estimación."""

    model: str
    provider: str
    finish_reason: str
    usage: StreamUsage
    latency_ms: int = Field(ge=0)
    cache_hit: bool
    estimated_cost_usd: float | None
    request_cost_usd: float | None


class EstimationResponse(BaseModel):
    result: EstimationResult
    prompt_version: str
    cached: bool = False
    cache_source: CacheSource = "none"
    estimation_id: int | None = None
    metrics: CallMetrics | None = None


class EstimationStreamMetadata(CallMetrics):
    """Evento `metadata` de `POST /api/v1/estimate/stream`, emitido tras el último `token`."""

    prompt_version: str
    cache_source: CacheSource = "none"
    estimation_id: int | None = None
