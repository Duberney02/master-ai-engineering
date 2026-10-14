"""Métricas deterministas del stress test del CAG: presupuestos de latencia y coste y deriva de memoria.

Reutilizan `evals.metrics.MetricResult` (nombre, puntuación 0/1, aprobado, detalles). Viven aquí y no en
`evals/metrics.py` porque consumen la observación de un turno y el snapshot de la memoria de la sesión, no
un `EstimationResult` frente a las expectativas de un caso; así `METRIC_NAMES` del dataset de referencia no
cambia ni hay importaciones circulares. No usan embeddings ni LLM.

Presupuestos por defecto (por turno; se pueden cambiar en el constructor y con las opciones del runner):

- `DEFAULT_LATENCY_BUDGET_MS = 30_000`: un turno encadena de 3 a 5 llamadas secuenciales al LLM
  (estimación, metadatos, anclas y resumen al salir de la ventana) sin streaming; 30 s es el límite a partir
  del cual un chat se percibe como roto.
- `DEFAULT_COST_BUDGET_USD = 0.01`: un céntimo por turno. Con tarifas de modelo pequeño (gpt-4o-mini) un turno
  sin adjuntos cuesta una fracción de esa cifra; el presupuesto se agota cuando el contexto se acerca a
  decenas de miles de tokens.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

from evals.metrics import MetricResult

DEFAULT_LATENCY_BUDGET_MS = 30_000
DEFAULT_COST_BUDGET_USD = 0.01
ALTERNATIVES_SEPARATOR = "|"


def _validated_budget(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or math.isnan(value) or value < 0:
        raise ValueError(f"{name} debe ser un número mayor o igual que 0")
    return float(value)


class LatencyBudgetMetric:
    """1.0 si `latency_ms <= budget_ms` (límite inclusivo); 0.0 si no."""

    name = "latency_budget"

    def __init__(self, budget_ms: float = DEFAULT_LATENCY_BUDGET_MS):
        self.budget_ms = _validated_budget(budget_ms, "budget_ms")

    def evaluate(self, latency_ms: float) -> MetricResult:
        passed = latency_ms <= self.budget_ms
        return MetricResult(
            self.name, 1.0 if passed else 0.0, passed, {"latency_ms": latency_ms, "budget_ms": self.budget_ms}
        )


class CostBudgetMetric:
    """1.0 si `cost_usd <= budget_usd` (límite inclusivo); 0.0 si no. Un coste desconocido (None) puntúa 0.0."""

    name = "cost_budget"

    def __init__(self, budget_usd: float = DEFAULT_COST_BUDGET_USD):
        self.budget_usd = _validated_budget(budget_usd, "budget_usd")

    def evaluate(self, cost_usd: float | None) -> MetricResult:
        if cost_usd is None:
            return MetricResult(
                self.name, 0.0, False, {"cost_usd": None, "budget_usd": self.budget_usd, "unknown": True}
            )
        passed = cost_usd <= self.budget_usd
        return MetricResult(
            self.name, 1.0 if passed else 0.0, passed, {"cost_usd": cost_usd, "budget_usd": self.budget_usd}
        )


@dataclass(frozen=True)
class Snapshot:
    """Memoria comprimida de la sesión tras un turno: lo que sobrevive fuera de la ventana reciente."""

    turn_index: int
    summary: str = ""
    anchors: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def sources(self) -> dict[str, str]:
        """Texto de cada fuente de memoria; la ventana reciente no cuenta (no es memoria comprimida)."""
        metadata = self.metadata
        technologies = metadata.get("mentioned_technologies") or []
        parts = [
            metadata.get("project_name"),
            metadata.get("agreed_scope"),
            metadata.get("assumed_team_size"),
            *(technologies if isinstance(technologies, list) else []),
        ]
        return {
            "summary": self.summary or "",
            "anchors": "\n".join(self.anchors),
            "metadata": "\n".join(str(part) for part in parts if part not in (None, "")),
        }


class MemoryDriftMetric:
    """1.0 si un hecho anterior aparece en el resumen, las anclas o los metadatos de un snapshot posterior.

    Coincidencia exacta de subcadena sin distinguir mayúsculas (sin acentos ni sinónimos): una paráfrasis del
    modelo cuenta como olvido. `fact` admite alternativas separadas por `|` (por ejemplo `30.000|30000`)."""

    name = "memory_drift"

    def evaluate(self, fact: str, introduced_at: int, snapshot: Snapshot) -> MetricResult:
        alternatives = [alt.strip().casefold() for alt in fact.split(ALTERNATIVES_SEPARATOR) if alt.strip()]
        if not alternatives:
            raise ValueError("fact no puede estar vacío")
        if snapshot.turn_index <= introduced_at:
            raise ValueError("el snapshot debe ser posterior al turno que introdujo el hecho")
        found_in = [
            source for source, text in snapshot.sources().items() if any(alt in text.casefold() for alt in alternatives)
        ]
        return MetricResult(
            self.name,
            1.0 if found_in else 0.0,
            bool(found_in),
            {
                "fact": fact,
                "introduced_at": introduced_at,
                "snapshot_turn": snapshot.turn_index,
                "found_in": found_in,
            },
        )
