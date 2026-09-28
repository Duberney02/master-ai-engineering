"""Contratos (Pydantic) de `/api/v1/estimate`, `/api/v1/estimate/stream` y `/api/v1/context`.

Todas las opciones de la solicitud son opcionales y sus valores por defecto
reproducen el comportamiento previo. La respuesta conserva todos los campos
anteriores; los cambios de tipo (valores desconocidos como `null`) y los campos
nuevos se documentan en el README («Cambios de contrato»).
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.context.examples import MAX_EXAMPLES, ExampleFormat

PreprocessingMode = Literal["none", "inline_cleaning", "two_phase"]
Phase = Literal["preprocessing", "estimation"]
CacheStatusField = Literal["hit", "shared", "miss", "disabled", "error"]
CacheSummaryStatus = Literal["hit", "partial", "miss", "disabled", "error"]

# Número de ejemplos que se inyectaban antes de existir esta opción.
DEFAULT_NUM_EXAMPLES = 2
MAX_OUTPUT_TOKENS = 16_000
MIN_TRANSCRIPTION_CHARS = 20
MAX_TRANSCRIPTION_CHARS = 50_000
# Identificadores de modelo: letras, dígitos y . _ : - / (sin espacios ni saltos de línea).
MODEL_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$"


class EstimationRequest(BaseModel):
    # Compatibilidad: /estimate sigue aceptando campos desconocidos, pero ya no los
    # descarta en silencio: el router los registra y los devuelve en la cabecera
    # `X-Ignored-Fields`. El endpoint SSE los rechaza (ver StreamEstimationRequest).
    model_config = ConfigDict(extra="allow")

    transcription: str = Field(
        min_length=MIN_TRANSCRIPTION_CHARS,
        max_length=MAX_TRANSCRIPTION_CHARS,
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
        description=(
            "Modelo a usar en esta solicitud (`gpt-4o`, `claude-haiku-4-5` o "
            "`proveedor/modelo`). Por defecto el primario configurado en LLM_MODEL. Si se "
            "indica, se usa EXACTAMENTE ese modelo salvo que `allow_fallback=true`."
        ),
    )
    allow_fallback: bool = Field(
        default=False,
        description=(
            "Solo con `model`: si el modelo pedido falla por un error recuperable, usar el "
            "modelo secundario configurado (LLM_FALLBACK_MODEL). Sin `model` el fallback "
            "configurado se aplica siempre."
        ),
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

    def ignored_fields(self) -> list[str]:
        return sorted((self.model_extra or {}).keys())


class StreamEstimationRequest(EstimationRequest):
    """Mismas opciones que /estimate; los campos no soportados se rechazan con 422."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- respuesta


class PhaseCost(BaseModel):
    original_generation_usd: float | None = Field(
        description="Coste estimado de la llamada que generó este resultado (null = desconocido)."
    )
    incurred_usd: float | None = Field(
        description="Coste estimado incurrido por ESTA solicitud (0 si se reutilizó de caché)."
    )


class PhaseUsage(BaseModel):
    phase: Phase
    provider: str = Field(description="Proveedor que generó el resultado.")
    model: str | None = Field(description="Modelo que respondió según el proveedor (null = no informado).")
    requested_model: str = Field(description="Modelo al que se envió la llamada.")
    finish_reason: str = Field(description="Motivo de finalización; `unknown` si no se confirmó.")
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: int = Field(description="Latencia de esta fase en ESTA solicitud.")
    original_latency_ms: int | None = Field(
        default=None, description="Latencia de la generación original (distinta en reutilizaciones)."
    )
    cache: CacheStatusField
    generated_at: datetime | None = Field(
        default=None, description="Momento de la generación original de este resultado."
    )
    fallback_used: bool = False
    attempts: int = Field(default=1, description="Llamadas al proveedor en esta solicitud (0 si se reutilizó).")
    cost: PhaseCost


class UsageInfo(BaseModel):
    """Tokens de la generación (suma de fases) y tokens incurridos por esta solicitud."""

    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    incurred_input_tokens: int | None = Field(
        description="Tokens de entrada consumidos por ESTA solicitud (fases reutilizadas cuentan 0)."
    )
    incurred_output_tokens: int | None
    incurred_total_tokens: int | None
    phases: list[PhaseUsage] = Field(default_factory=list)


class CostInfo(BaseModel):
    currency: Literal["USD"] = "USD"
    pricing_source: str
    original_generation_usd: float | None = Field(
        description="Coste estimado de generar este resultado desde cero (suma de fases)."
    )
    incurred_usd: float | None = Field(
        description="Coste estimado incurrido por esta solicitud (null si alguna fase es desconocida)."
    )
    saved_usd: float | None = Field(
        description="Ahorro estimado por reutilización (coste original de las fases reutilizadas)."
    )


class CacheInfo(BaseModel):
    status: CacheSummaryStatus = Field(
        description="`hit` (todas las fases reutilizadas), `partial`, `miss`, `disabled` o `error`."
    )
    phases: dict[str, CacheStatusField]


class EstimationEvaluation(BaseModel):
    """Evaluación estructural (sin llamadas al LLM) contra el formato exigido por el prompt."""

    sections: dict[str, bool] = Field(
        description="Encabezados obligatorios presentes (título y secciones ###)."
    )
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


class EstimationMetadata(BaseModel):
    """Todo lo que describe una estimación salvo su texto. Es el payload del evento SSE
    `metadata` y la base de `EstimationResponse`."""

    request_id: str | None = None
    model: str | None = Field(description="Modelo que respondió la fase de estimación.")
    provider: str
    finish_reason: str
    usage: UsageInfo
    estimated_cost_usd: float | None = Field(
        description="Alias compatible de `cost.incurred_usd` (coste de ESTA solicitud)."
    )
    cost: CostInfo
    cache: CacheInfo
    fallback_used: bool = False
    latency_ms: int
    generated_at: datetime
    preprocessing: PreprocessingMode = "none"
    extracted_requirements: str | None = Field(
        default=None,
        description="Requisitos extraídos en la primera fase (solo con preprocessing=two_phase).",
    )
    evaluation: EstimationEvaluation | None = None


class EstimationResponse(EstimationMetadata):
    estimation: str


# --------------------------------------------------------------------------- contexto


class ExampleSummary(BaseModel):
    title: str
    meeting_summary: str
    total_hours: int


class PublicModelConfig(BaseModel):
    primary: str
    fallback: str | None
    allowed_models: list[str]
    explicit_model_policy: str


class ContextResponse(BaseModel):
    """Contexto y configuración pública (sin credenciales) para mostrar en clientes."""

    system_prompt: str
    extraction_prompt: str | None
    examples: list[ExampleSummary]
    models: PublicModelConfig
    cache_enabled: bool
    limits: dict[str, int]
    options: dict[str, list[str]]
