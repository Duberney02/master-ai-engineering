"""Contrato JSON del backend `estimator-web` tal como lo consume el chat.

Son modelos locales y mínimos: describen solo la forma de las respuestas del backend Go (única dependencia compartida
con el resto del monorepo). Este proyecto no importa nada del servicio de IA.
"""

from enum import StrEnum

from pydantic import BaseModel, Field

MIN_DESCRIPTION_CHARS = 20
MAX_DESCRIPTION_CHARS = 80_000
OUT_OF_SCOPE_PREFIX = "Out of scope:"
# Versiones que ofrece el formulario; el backend valida y rechaza con 422 las que no conozca.
PROMPT_VERSIONS = ("v3", "v1", "v2")


class ProjectType(StrEnum):
    MOBILE_APP = "mobile_app"
    WEB_SAAS = "web_saas"
    INTERNAL_TOOL = "internal_tool"
    DATA_PIPELINE = "data_pipeline"


class DetailLevel(StrEnum):
    SUMMARY = "summary"
    MEDIUM = "medium"
    DETAILED = "detailed"


class OutputFormat(StrEnum):
    PHASES_TABLE = "phases_table"
    LINE_ITEMS = "line_items"
    NARRATIVE = "narrative"


class Phase(BaseModel):
    name: str
    description: str = ""
    duration_weeks: float
    cost_eur: float


class EstimationResult(BaseModel):
    summary: str
    confidence_pct: int
    phases: list[Phase]
    total_duration_weeks: float
    total_cost_eur: float
    out_of_scope: bool = False


class ProjectMetadata(BaseModel):
    """Hechos del proyecto acumulados durante la conversación."""

    project_name: str | None = None
    assumed_team_size: int | None = None
    mentioned_technologies: list[str] = Field(default_factory=list)
    agreed_scope: str | None = None

    def is_empty(self) -> bool:
        return not (
            self.project_name or self.assumed_team_size or self.mentioned_technologies or self.agreed_scope
        )


class EstimationResponse(BaseModel):
    """Respuesta de `POST /api/conversations/{id}/estimations`."""

    result: EstimationResult
    prompt_version: str = ""
    estimation_id: int | None = None
    metrics: dict | None = None
    project_metadata: ProjectMetadata


class FewShotExample(BaseModel):
    title: str
    description: str = ""


class PromptPreview(BaseModel):
    """Respuesta de `GET /api/prompt-preview`: prompt de sistema y ejemplos few-shot."""

    system_prompt: str
    examples: list[FewShotExample] = Field(default_factory=list)
