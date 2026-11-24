"""Contratos Pydantic v2 del pipeline de embeddings.

`complexity` y `sector` son `str`: no se conoce el conjunto completo de valores válidos, así que no se
restringen con `Literal`.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_NonEmptyStr = Field(min_length=1)


class ClientMetadata(BaseModel):
    name: str = _NonEmptyStr
    sector: str = _NonEmptyStr
    country: str = _NonEmptyStr


class BudgetComponent(BaseModel):
    component_id: str = _NonEmptyStr
    name: str = _NonEmptyStr
    description: str = _NonEmptyStr
    # Bloque funcional de la tarea (corpus de tareas históricas de la Sesión 9); opcional y aditivo.
    module: str | None = None
    tech_stack: list[str] = Field(default_factory=list)
    estimated_hours: float = Field(ge=0, allow_inf_nan=False)
    complexity: str = _NonEmptyStr
    dependencies: list[str] = Field(default_factory=list)

    @field_validator("component_id", "name", "description", "complexity")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class Budget(BaseModel):
    budget_id: str = _NonEmptyStr
    client_metadata: ClientMetadata
    project_summary: str = _NonEmptyStr
    main_technology: str = _NonEmptyStr
    year: int = Field(ge=1990, le=2100)
    total_estimated_hours: float = Field(ge=0, allow_inf_nan=False)
    components: list[BudgetComponent] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_component_ids(self) -> "Budget":
        ids = [component.component_id for component in self.components]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            raise ValueError(f"duplicate component_id in budget {self.budget_id}: {duplicated}")
        return self


class Chunk(BaseModel):
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    token_count: int = Field(ge=0)


class EmbeddedChunk(Chunk):
    embedding: list[float]


class IngestRequest(BaseModel):
    """Un presupuesto histórico a persistir: `content` es el JSON completo de un `Budget`."""

    source_path: str = Field(min_length=1)
    document_type: str = Field(min_length=1, max_length=50)
    content: Budget
    # `chunk_type` de todos los chunks del documento (filtrable). El corpus de tareas usa `historical_task`.
    chunk_type: str = Field(default="budget_component", min_length=1, max_length=50, pattern=r"^[a-z_]+$")


class IngestResponse(BaseModel):
    document_id: int
    chunks_created: int
    embedding_dimension: int
    ingestion_time_ms: int


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class SearchResult(BaseModel):
    chunk_id: int
    document_id: int
    chunk_type: str
    content: str
    # Distancia coseno (`<=>`): 0 = misma dirección, 2 = opuestos. Menor es más parecido.
    distance: float
    metadata: dict[str, Any]


class SearchResponse(BaseModel):
    query: str
    k: int
    search_time_ms: int
    results: list[SearchResult]


# ---------------------------------------------------------------------------------------------------------------
# Sesión 9: pipeline RAG de estimación fundamentada (reformulación → recuperación → ensamblado → generación).
# Conviven con los contratos de la Sesión 8 (`SearchRequest`/`SearchResponse` de `POST /search`), que no cambian.
# ---------------------------------------------------------------------------------------------------------------

# Margen (jornadas) entre `total_engineer_days` y la suma de las tareas: absorbe redondeos del modelo.
_TOTAL_TOLERANCE_DAYS = 0.5

Scale = Literal["small", "medium", "large", "unknown"]
Confidence = Literal["high", "medium", "low", "insufficient"]
Relevance = Literal["primary", "supporting", "tangential"]
Impact = Literal["high", "medium", "low"]


class EstimationQuery(BaseModel):
    """Brief estructurado extraído de la transcripción: solo lo que guía la recuperación (qué, con qué, dónde)."""

    function: str = Field(min_length=1, max_length=1000, description="Resumen funcional del proyecto.")
    technologies: list[str] = Field(default_factory=list)
    sector: str | None = None
    scale: Scale = "unknown"
    country: str | None = None
    regulations: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class RetrievedChunk(BaseModel):
    """Chunk devuelto por la recuperación filtrada. `id` (clave primaria) es el id de fuente que se cita."""

    id: int
    content: str
    sector: str = "unknown"
    project_year: int = 0
    chunk_type: str
    # Distancia coseno (`<=>`): 0 = misma dirección, 2 = opuestos. Menor es más parecido.
    distance: float
    budget_id: str | None = Field(default=None, description="Identificador trazable del presupuesto padre.")
    document_id: int | None = None


class RetrievalRequest(BaseModel):
    """`POST /v1/retrieval/search`: consulta, límites y filtros estructurales opcionales (`None` = sin filtro)."""

    query_text: str = Field(min_length=3, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=30, description="Por defecto, `retrieval_top_k`.")
    distance_threshold: float | None = Field(
        default=None, ge=0, le=2, description="Por defecto, `retrieval_distance_threshold`."
    )
    sectors: list[str] | None = Field(default=None, max_length=20)
    project_year_min: int | None = Field(default=None, ge=1990, le=2100)
    project_year_max: int | None = Field(default=None, ge=1990, le=2100)
    chunk_types: list[str] | None = Field(default=None, max_length=10)

    @field_validator("query_text")
    @classmethod
    def _query_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class RetrievalResult(BaseModel):
    chunks: list[RetrievedChunk]
    low_confidence: bool = Field(description="True cuando ningún chunk supera el umbral (soft-fail).")
    candidates_evaluated: int = Field(ge=0, description="Chunks que cumplen los filtros antes del umbral y el límite.")


class SourceCitation(BaseModel):
    """Referencia de la estimación a un chunk recuperado."""

    source_id: int = Field(description="Id del chunk citado (un `RetrievedChunk.id`).")
    relevance: Relevance
    used_for: str = Field(description="Qué aportó esta fuente a la estimación.")


class Assumption(BaseModel):
    """Parte de la estimación que NO respalda ninguna fuente recuperada."""

    description: str
    impact: Impact
    rationale: str


class TaskItem(BaseModel):
    """Tarea concreta de un módulo, en jornadas-ingeniero."""

    name: str = Field(min_length=1)
    description: str | None = None
    engineer_days: float = Field(ge=0, allow_inf_nan=False)


class WorkModule(BaseModel):
    """Bloque funcional (autenticación, pagos, datos, frontend, infraestructura, QA…) con sus tareas."""

    name: str = Field(min_length=1)
    description: str | None = None
    tasks: list[TaskItem] = Field(default_factory=list)


class Estimate(BaseModel):
    """Estimación fundamentada en presupuestos recuperados, en jornadas-ingeniero y con citas.

    Distinta de `EstimationResult` (euros/semanas/fases). Con `confidence="insufficient"` los totales son nulos,
    `modules` está vacío y `insufficient_context_explanation` explica qué falta: la regla la comprueba
    `validation.check_coherence` fuera del esquema, para que el pipeline pueda reintentar con *feedback*.
    """

    total_engineer_days: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    duration_weeks: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    modules: list[WorkModule] = Field(default_factory=list)
    sources: list[SourceCitation] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    confidence: Confidence
    reasoning: str = Field(description="Cómo se derivó la estimación de las fuentes.")
    insufficient_context_explanation: str | None = None

    @model_validator(mode="after")
    def _total_matches_tasks(self) -> "Estimate":
        """Con tareas y confianza distinta de `insufficient`, el total es la suma de las tareas.

        Un fallo aquí hace que `generate_structured` pida la corrección en la misma conversación. Las estimaciones
        `insufficient` no se validan aquí: su forma la comprueba `validation.check_coherence`, con su propia
        reparación.
        """
        if self.confidence == "insufficient":
            return self
        task_days = sum(task.engineer_days for module in self.modules for task in module.tasks)
        if not task_days:
            return self
        if self.total_engineer_days is None or abs(self.total_engineer_days - task_days) > _TOTAL_TOLERANCE_DAYS:
            raise ValueError(f"total_engineer_days must equal the sum of the task engineer_days ({task_days:g})")
        return self


class EstimateRequest(BaseModel):
    """`POST /v1/estimate/from-transcript`."""

    transcript: str = Field(min_length=100, max_length=50_000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class ReformulateRequest(BaseModel):
    """`POST /v1/estimate/stages/reformulate`."""

    transcript: str = Field(min_length=100, max_length=50_000)


class ReformulationResult(BaseModel):
    query: EstimationQuery
    search_text: str = Field(description="Texto canónico que se embebe para la recuperación.")


class AssembleRequest(BaseModel):
    """`POST /v1/estimate/stages/assemble`. Sin `max_context_tokens`, se usa el ajuste del servidor."""

    chunks: list[RetrievedChunk] = Field(max_length=100)
    query: EstimationQuery | None = None
    max_context_tokens: int | None = Field(default=None, ge=256, le=128_000)


class AssembleResult(BaseModel):
    context_block: str
    kept_chunks: list[RetrievedChunk]
    dropped_count: int = Field(ge=0, description="Chunks descartados por el presupuesto de tokens.")
    token_count: int = Field(ge=0, description="Tokens del bloque de contexto ensamblado.")


class GenerateRequest(BaseModel):
    """`POST /v1/estimate/stages/generate`. `kept_chunks` son los chunks del bloque: validan las citas."""

    context_block: str = Field(min_length=1, max_length=600_000)
    query: EstimationQuery
    kept_chunks: list[RetrievedChunk] = Field(default_factory=list, max_length=100)


class GenerateResult(BaseModel):
    estimate: Estimate
    fabricated_source_ids: list[int] = Field(
        default_factory=list, description="Ids citados que no estaban en `kept_chunks` (vacío = limpio)."
    )
    coherent: bool = Field(description="False si una estimación `insufficient` incumple su forma.")
