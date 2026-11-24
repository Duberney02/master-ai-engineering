#!/usr/bin/env python3
"""Gate de regresión y monitor de la calidad de generación (Sesión 11).

* `--gate`: puntúa el golden set con las cuatro métricas de RAGAS (faithfulness, answer relevancy, context precision,
  context recall) y con las comprobaciones propias del servicio (citas colgantes y líneas `degraded`). Sale con código
  DISTINTO DE CERO si alguna métrica cae más de `0,05` por debajo de la línea base versionada
  (`evals/ragas_baseline_s11.json`), si una métrica no se pudo calcular, o si aparece alguna cita colgante. Imprime
  `PASS` o `FAIL` con el motivo de cada fallo.
* `--monitor`: lectura de salud SIN referencia. Calcula solo faithfulness y answer relevancy sobre una muestra de
  consultas (sin `ground_truth`), imprime las dos medias y SIEMPRE sale con 0: es un termómetro, no un bloqueo.

La lógica de decisión (`find_regressions`, `gate_verdict`, `run_gate`, `run_monitor`) son funciones puras que reciben
las puntuaciones: las pruebas la cubren con métricas falsas, sin RAGAS ni claves. Con claves reales y el stack
levantado (ver `eval_ragas_s11.py`)::

    docker compose -f docker-compose.verify.yml run --rm --entrypoint python api-test \
        scripts/eval_generation_s11.py --gate
    docker compose -f docker-compose.verify.yml run --rm --entrypoint python api-test \
        scripts/eval_generation_s11.py --monitor --sample 3

Si la caída es esperada y aceptada, regenera la línea base con `eval_ragas_s11.py --write-baseline` y versiónala.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from eval_ragas_s11 import (  # importa antes que `app`: pone la raíz del servicio en sys.path
    BASELINE_PATH,
    METRICS,
    Collected,
    build_estimator,
    collect_samples,
    load_golden,
    mean_scores,
)

# Caída máxima admitida por métrica respecto de la línea base.
TOLERANCE = 0.05
# Las únicas métricas de RAGAS que no necesitan `ground_truth`: las del monitor.
MONITOR_METRICS = ("faithfulness", "answer_relevancy")
DEFAULT_MONITOR_SAMPLE = 3

Scorer = Callable[[list[dict], Sequence[str]], list[dict[str, float | None]]]


@dataclass(frozen=True)
class Regression:
    metric: str
    baseline: float
    current: float | None

    @property
    def drop(self) -> float | None:
        return None if self.current is None else round(self.baseline - self.current, 4)

    def describe(self) -> str:
        if self.current is None:
            return f"{self.metric}: no se pudo calcular (línea base {self.baseline:.3f})"
        return f"{self.metric}: {self.current:.3f} frente a {self.baseline:.3f} de la línea base (cae {self.drop:.3f})"


@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    regressions: list[Regression] = field(default_factory=list)
    dangling_citations: int = 0

    def failures(self) -> list[str]:
        reasons = [regression.describe() for regression in self.regressions]
        if self.dangling_citations:
            reasons.append(f"citas colgantes: {self.dangling_citations} (debe ser 0)")
        return reasons


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, float]:
    """Medias por métrica de la línea base versionada; error claro si no existe."""
    if not path.exists():
        raise FileNotFoundError(
            f"No existe la línea base {path.name}: genérala con `eval_ragas_s11.py --write-baseline` y versiónala."
        )
    return json.loads(path.read_text(encoding="utf-8"))["metrics"]


def find_regressions(
    current: dict[str, float | None], baseline: dict[str, float], tolerance: float = TOLERANCE
) -> list[Regression]:
    """Métricas que caen MÁS de `tolerance` por debajo de la línea base, o que no se pudieron calcular.

    Una caída exactamente igual a la tolerancia es admisible; mejorar nunca es una regresión.
    """
    regressions: list[Regression] = []
    for metric, base in baseline.items():
        if base is None:
            continue
        value = current.get(metric)
        if value is None or round(base - value, 4) > tolerance:
            regressions.append(Regression(metric=metric, baseline=base, current=value))
    return regressions


def gate_verdict(
    current: dict[str, float | None],
    baseline: dict[str, float],
    dangling_citations: int,
    tolerance: float = TOLERANCE,
) -> GateVerdict:
    regressions = find_regressions(current, baseline, tolerance)
    return GateVerdict(
        passed=not regressions and dangling_citations == 0,
        regressions=regressions,
        dangling_citations=dangling_citations,
    )


def format_scores(scores: dict[str, float | None]) -> str:
    return " · ".join(f"{name}={'n/d' if value is None else f'{value:.3f}'}" for name, value in scores.items())


def run_gate(
    collected: Collected, scorer: Scorer, baseline: dict[str, float], *, tolerance: float = TOLERANCE
) -> int:
    """Puntúa las muestras, decide y devuelve el código de salida (0 = PASS, 1 = FAIL)."""
    rows = scorer(collected.samples, METRICS)
    current = mean_scores(rows)
    print(f"Medias actuales: {format_scores(current)}")
    print(f"Línea base:      {format_scores(baseline)}")
    verdict = gate_verdict(current, baseline, collected.dangling_citations, tolerance)
    if verdict.passed:
        print(f"PASS: ninguna métrica cae más de {tolerance} y no hay citas colgantes.")
        return 0
    print("FAIL:")
    for reason in verdict.failures():
        print(f"  - {reason}")
    return 1


def run_monitor(collected: Collected, scorer: Scorer) -> int:
    """Faithfulness y answer relevancy sin referencia; siempre 0 (no bloquea)."""
    rows = scorer(collected.samples, MONITOR_METRICS)
    means = format_scores(mean_scores(rows, MONITOR_METRICS))
    print(f"Monitor ({len(collected.samples)} consultas, sin referencia): {means}")
    return 0


def main(argv: Sequence[str] | None = None, *, estimator=None, scorer: Scorer | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate de regresión y monitor de la generación (RAGAS).")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--gate", action="store_true", help="Falla si una métrica cae más de 0,05 o hay citas colgantes.")
    mode.add_argument("--monitor", action="store_true", help="Faithfulness y answer relevancy sin referencia (exit 0).")
    parser.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    parser.add_argument("--tolerance", type=float, default=TOLERANCE)
    parser.add_argument("--sample", type=int, default=DEFAULT_MONITOR_SAMPLE, help="Consultas del monitor.")
    parser.add_argument("--seed", type=int, default=11, help="Semilla del muestreo del monitor.")
    parser.add_argument("--no-judge", action="store_true", help="El gate de alucinaciones sin juez (solo ancla).")
    args = parser.parse_args(argv)

    if args.gate:
        try:
            baseline = load_baseline(args.baseline)
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        entries = load_golden()
    else:
        golden = load_golden()
        entries = random.Random(args.seed).sample(golden, k=min(args.sample, len(golden)))

    if scorer is None:
        from score_ragas_s11 import score_samples

        scorer = score_samples
    collected = asyncio.run(
        collect_samples(
            estimator or build_estimator(), entries, use_judge=not args.no_judge, with_reference=args.gate
        )
    )
    if args.gate:
        return run_gate(collected, scorer, baseline, tolerance=args.tolerance)
    return run_monitor(collected, scorer)


if __name__ == "__main__":
    sys.exit(main())
