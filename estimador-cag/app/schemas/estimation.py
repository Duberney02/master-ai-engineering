"""Contratos (Pydantic) del endpoint de estimación.

Define explícitamente la forma de los datos que intercambian el servidor y
sus consumidores para `/api/v1/transcription/estimate` (y `/stream`), separada
de la lógica del router.

Todas las opciones nuevas de la solicitud son opcionales y sus valores por
defecto reproducen el comportamiento previo: sin preprocesamiento, dos
ejemplos CAG en Markdown, modelo y límite de tokens del proveedor sin cambios.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.context.examples import MAX_EXAMPLES, ExampleFormat

PreprocessingMode = Literal["none", "inline_cleaning", "two_phase"]
Phase = Literal["preprocessing", "estimation"]

# Número de ejemplos que se inyectaban antes de existir esta opción.
DEFAULT_NUM_EXAMPLES = 2
MAX_OUTPUT_TOKENS = 16_000
# Identificadores de modelo: letras, dígitos y . _ : - / (sin espacios ni saltos de línea).
MODEL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$"


class EstimationRequest(BaseModel):
    transcription: str = Field(
        min_length=20,
        max_length=50_000,
        description="Transcripción de la reunión con el cliente.",
    )
    preprocessing: PreprocessingMode = Field(
        default="none",
        description=(
            "Preparación de la transcripción: `none` (tal cual), `inline_cleaning` "
            "(instrucciones de limpieza dentro del prompt) o `two_phase` (una primera "
            "llamada extrae los requisitos y una segunda estima a partir de ellos)."
        ),
    )
    example_format: ExampleFormat = Field(
        default="markdown",
        description="Formato de los ejemplos CAG en el prompt: markdown, json o narrative.",
    )
    num_examples: int = Field(
        default=DEFAULT_NUM_EXAMPLES,
        ge=0,
        le=MAX_EXAMPLES,
        description=f"Cantidad de ejemplos históricos a incluir (0–{MAX_EXAMPLES}).",
    )
    use_examples: bool = Field(
        default=True,
        description="Si es false se omite por completo el bloque de ejemplos (ignora num_examples).",
    )
    model: str | None = Field(
        default=None,
        pattern=MODEL_PATTERN,
        description="Modelo a usar en esta solicitud; por defecto el configurado en LLM_MODEL.",
    )
    max_tokens: int | None = Field(
        default=None,
        gt=0,
        le=MAX_OUTPUT_TOKENS,
        description=(
            "Límite de tokens de salida de la estimación. Por defecto: el del proveedor "
            "(OpenAI) o 4096 (Anthropic)."
        ),
    )
    evaluate: bool = Field(
        default=True,
        description="Incluir la evaluación estructural de la estimación en la respuesta.",
    )
    thinking_budget: int | None = Field(default=None, ge=1024, le=15000)
    include_project_costs: bool = False
    developer_rate_eur: float = Field(default=62.5, gt=0, le=10000, allow_inf_nan=False)
    designer_rate_eur: float = Field(default=50, gt=0, le=10000, allow_inf_nan=False)


class PhaseUsage(BaseModel):
    phase: Phase
    model: str
    finish_reason: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: int
    provider: str = ""
    cache_hit: bool = False
    estimated_cost_usd: float | None = None
    request_cost_usd: float | None = None
    usage_available: bool = True


class UsageInfo(BaseModel):
    """Tokens agregados de todas las fases y el detalle por fase."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    phases: list[PhaseUsage] = Field(default_factory=list)


class EstimationEvaluation(BaseModel):
    """Evaluación estructural (sin llamadas al LLM) contra el formato exigido por el prompt."""

    sections: dict[str, bool] = Field(
        description="Encabezados obligatorios presentes (título y secciones ###)."
    )
    project_cost_match: bool | None = None
    declared_project_cost_eur: float | None = None
    sections_in_order: bool
    has_breakdown_table: bool
    table_rows: int
    declared_total_hours: float | None
    sum_row_hours_min: float | None
    sum_row_hours_max: float | None
    hours_match: bool | None = Field(
        description="El total declarado coincide con la suma de la tabla; null si no es verificable."
    )
    range_min: float | None
    range_max: float | None
    range_consistent: bool | None
    has_team: bool
    has_duration: bool
    finish_reason_ok: bool
    truncated: bool
    score: float = Field(ge=0, le=1)
    issues: list[str]


class EstimationResponse(BaseModel):
    estimation: str
    model: str
    provider: str
    finish_reason: str
    usage: UsageInfo
    estimated_cost_usd: float | None
    request_cost_usd: float | None = None
    cache_hit: bool = False
    latency_ms: int
    generated_at: datetime
    preprocessing: PreprocessingMode = "none"
    extracted_requirements: str | None = Field(
        default=None,
        description="Requisitos extraídos en la primera fase (solo con preprocessing=two_phase).",
    )
    evaluation: EstimationEvaluation | None = None
