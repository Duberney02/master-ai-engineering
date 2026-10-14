"""Dataset de referencia: modelos estrictos y carga desde JSON versionado."""

import json
from pathlib import Path
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas import MIN_DESCRIPTION_CHARS, ProjectType

DATASETS_DIR = Path(__file__).parent / "datasets"
DEFAULT_DATASET = DATASETS_DIR / "reference_v1.json"

Category = Literal[
    "saas", "mobile", "internal_tool", "data_pipeline", "vague", "adversarial", "regulatory", "tight_deadline"
]
CATEGORIES: tuple[str, ...] = get_args(Category)

Keyword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
Range = tuple[float, float]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Expectations(_Strict):
    """Lo que debe cumplir la estimación de un caso. Todo es opcional salvo que el caso lo defina."""

    requirements: list[Keyword] = Field(default_factory=list, description="Palabras clave; `a|b` = alternativas.")
    technologies: list[Keyword] = Field(default_factory=list)
    phases: tuple[int, int] | None = None
    cost_eur: Range | None = None
    duration_weeks: Range | None = None
    expect_out_of_scope: bool = False
    expect_rejection: str | None = Field(default=None, description="Razón de guardrail esperada (HTTP 400).")
    min_recall: float = Field(default=0.6, ge=0, le=1)

    @model_validator(mode="after")
    def _ranges_are_ordered(self) -> "Expectations":
        for name in ("phases", "cost_eur", "duration_weeks"):
            bounds = getattr(self, name)
            if bounds is not None and not (0 <= bounds[0] <= bounds[1]):
                raise ValueError(f"{name}: el rango debe cumplir 0 <= mín <= máx")
        if self.expect_out_of_scope and self.expect_rejection:
            raise ValueError("expect_out_of_scope y expect_rejection son excluyentes")
        return self


class EvalCase(_Strict):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=60)]
    category: Category
    title: str = Field(min_length=3, max_length=120)
    project_type: ProjectType
    detail_level: Literal["summary", "medium", "detailed"] = "medium"
    output_format: Literal["phases_table", "line_items", "narrative"] = "phases_table"
    transcript: str = Field(min_length=MIN_DESCRIPTION_CHARS)
    expectations: Expectations

    @model_validator(mode="after")
    def _has_something_to_check(self) -> "EvalCase":
        e = self.expectations
        checkable = (
            e.requirements
            or e.technologies
            or e.phases
            or e.cost_eur
            or e.duration_weeks
            or e.expect_out_of_scope
            or e.expect_rejection
        )
        if not checkable:
            raise ValueError("el caso no define ninguna expectativa")
        return self


class EvalDataset(_Strict):
    version: str = Field(min_length=1)
    description: str = ""
    cases: list[EvalCase] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> "EvalDataset":
        ids = [case.id for case in self.cases]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            raise ValueError(f"identificadores duplicados: {', '.join(duplicated)}")
        return self


def load_dataset(path: Path | str | None = None) -> EvalDataset:
    """Carga y valida un dataset; lanza `ValueError` con el motivo si el archivo es ilegible o inválido."""
    target = Path(path) if path else DEFAULT_DATASET
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"No se pudo leer el dataset {target}: {exc}") from exc
    try:
        return EvalDataset.model_validate(raw)
    except ValueError as exc:  # ValidationError hereda de ValueError
        raise ValueError(f"Dataset inválido {target}: {exc}") from exc
