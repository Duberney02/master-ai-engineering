"""Tipos de la interfaz uniforme del wrapper LLM (generación normal y streaming)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

# Estado de la caché para UNA llamada al LLM:
# - hit:      resultado leído de Redis; no se llamó al proveedor.
# - shared:   resultado de una petición idéntica concurrente en curso; no se llamó al proveedor.
# - miss:     no había entrada; se llamó al proveedor.
# - disabled: caché desactivada por configuración; se llamó al proveedor.
# - error:    Redis no disponible/timeout; se llamó al proveedor (modo degradado).
CacheStatus = Literal["hit", "shared", "miss", "disabled", "error"]
REUSED_STATUSES: frozenset[str] = frozenset({"hit", "shared"})

# Motivos de finalización que confirman una respuesta completa.
COMPLETE_FINISH_REASONS: frozenset[str] = frozenset({"stop", "end_turn", "stop_sequence"})
UNKNOWN_FINISH_REASON = "unknown"


@dataclass(frozen=True)
class LLMRequest:
    """Una llamada: prompt de sistema, mensaje de usuario y límite de salida.

    `purpose` solo sirve para logs/métricas; no afecta a la generación ni a la clave.
    """

    system: str
    user: str
    max_tokens: int | None = None
    purpose: str = "generation"


@dataclass(frozen=True)
class ProviderCompletion:
    """Respuesta normalizada de un adaptador de proveedor (sin política ni caché)."""

    text: str
    model: str | None  # el que reporta el proveedor; None si no lo informa
    finish_reason: str  # "unknown" si el proveedor no lo confirma
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class ProviderDelta:
    text: str


@dataclass(frozen=True)
class ProviderStreamEnd:
    """Metadatos al final de un stream del proveedor (valores desconocidos = None)."""

    model: str | None
    finish_reason: str
    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True)
class LLMResult:
    """Resultado de una llamada del wrapper con metadatos reales y explícitos."""

    text: str
    provider: str
    model: str | None  # modelo que respondió según el proveedor (None = no informado)
    requested_model: str  # modelo al que se envió la llamada
    finish_reason: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int  # latencia de ESTA solicitud (lectura de caché en un acierto)
    cache_status: CacheStatus
    fallback_used: bool = False
    attempts: int = 1
    # Coste de la generación original (con la tarifa vigente al generarla).
    original_cost_usd: float | None = None
    # Coste incurrido por ESTA solicitud: 0.0 si se reutilizó (hit/shared).
    incurred_cost_usd: float | None = None
    # Solo en reutilizaciones: cuándo y con qué latencia se generó originalmente.
    generated_at: datetime | None = None
    original_latency_ms: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens

    @property
    def reused(self) -> bool:
        return self.cache_status in REUSED_STATUSES


@dataclass(frozen=True)
class StreamDelta:
    """Fragmento de contenido emitido por `LLMClient.stream`."""

    text: str


@dataclass(frozen=True)
class StreamFinal:
    """Último evento de `LLMClient.stream`: resultado completo con metadatos."""

    result: LLMResult
