"""Contratos Pydantic v2 del pipeline de embeddings.

`complexity` y `sector` son `str`: no se conoce el conjunto completo de valores válidos, así que no se
restringen con `Literal`.
"""

from typing import Any

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
