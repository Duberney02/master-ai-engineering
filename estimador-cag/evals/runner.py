"""Runner de evaluación: ejecuta el dataset de referencia contra la API y emite un reporte JSON.

    python -m evals.runner --mode actor                       # en proceso (TestClient), proveedor de .env
    python -m evals.runner --mode acb --base-url http://localhost:8000 --output informe.json

Cada caso usa una sesión nueva (`POST /api/v1/sessions`) y un único `estimate` o `estimate-acb`. El
código de salida es 0 si todos los casos aprueban, 1 si alguno falla o da error y 2 si el uso es incorrecto.
"""

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from app.schemas import EstimationResult
from evals.dataset import CATEGORIES, EvalCase, EvalDataset, load_dataset
from evals.metrics import MetricResult, evaluate_case

MODES = ("actor", "acb")
SUMMARY_CHARS = 300
EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
_ENDPOINT = {"actor": "estimate", "acb": "estimate-acb"}


class Client(Protocol):
    """Subconjunto de `httpx.Client` / `TestClient` que usa el runner."""

    def post(self, url: str, **kwargs: Any) -> Any: ...


@dataclass
class CaseReport:
    id: str
    category: str
    status: str = "error"  # passed | failed | error
    latency_ms: int = 0
    http_status: int | None = None
    metrics: dict[str, MetricResult] = field(default_factory=dict)
    estimation: dict[str, Any] | None = None
    prompt_version: str | None = None
    acb_final_decision: str | None = None
    rejected: str | None = None
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "status": self.status,
            "passed": self.passed,
            "latency_ms": self.latency_ms,
            "http_status": self.http_status,
            "metrics": {name: metric.as_dict() for name, metric in self.metrics.items()},
            "estimation": self.estimation,
            "prompt_version": self.prompt_version,
            "acb_final_decision": self.acb_final_decision,
            "rejected": self.rejected,
            "error": self.error,
        }


@dataclass
class Report:
    dataset: str
    mode: str
    target: str
    started_at: str
    cases: list[CaseReport]
    prompt_version_requested: str | None = None

    @property
    def totals(self) -> dict[str, int]:
        passed = sum(c.status == "passed" for c in self.cases)
        errors = sum(c.status == "error" for c in self.cases)
        return {
            "evaluated": len(self.cases),
            "passed": passed,
            "failed": len(self.cases) - passed,
            "errors": errors,
        }

    @property
    def ok(self) -> bool:
        return bool(self.cases) and all(c.passed for c in self.cases)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "mode": self.mode,
            "target": self.target,
            "started_at": self.started_at,
            "prompt_version_requested": self.prompt_version_requested,
            "totals": self.totals,
            "cases": [case.as_dict() for case in self.cases],
        }


def _brief(result: EstimationResult) -> dict[str, Any]:
    return {
        "summary": result.summary[:SUMMARY_CHARS],
        "confidence_pct": result.confidence_pct,
        "out_of_scope": result.out_of_scope,
        "total_cost_eur": result.total_cost_eur,
        "total_duration_weeks": result.total_duration_weeks,
        "phases": [p.name for p in result.phases],
    }


def _error_detail(response: Any) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    detail = body.get("message") or body.get("detail") if isinstance(body, dict) else None
    return f"HTTP {response.status_code}: {detail if isinstance(detail, str) else 'respuesta de error'}"


def run_case(
    client: Client, case: EvalCase, mode: str, prompt_version: str | None = None, tier: str | None = None
) -> CaseReport:
    """Evalúa un caso en una sesión nueva. Nunca lanza: los fallos quedan en el reporte."""
    report = CaseReport(id=case.id, category=case.category)
    started = time.perf_counter()
    try:
        created = client.post("/api/v1/sessions")
        if created.status_code != 201:
            report.http_status = created.status_code
            report.error = f"No se pudo crear la sesión ({_error_detail(created)})"
            return report
        session_id = created.json()["session_id"]
        form = {
            "transcript": case.transcript,
            "project_type": case.project_type.value,
            "detail_level": case.detail_level,
            "output_format": case.output_format,
        }
        if prompt_version:
            form["prompt_version"] = prompt_version
        if tier:
            form["tier"] = tier
        estimate_started = time.perf_counter()
        response = client.post(f"/api/v1/sessions/{session_id}/{_ENDPOINT[mode]}", data=form)
        report.latency_ms = int((time.perf_counter() - estimate_started) * 1000)
        report.http_status = response.status_code
        _score(report, case, response)
    except Exception as exc:  # red, JSON ilegible, etc.: el caso falla pero la ejecución sigue
        report.status, report.error = "error", f"{type(exc).__name__}: {exc}"[:300]
    finally:
        if not report.latency_ms:
            report.latency_ms = int((time.perf_counter() - started) * 1000)
    return report


def _score(report: CaseReport, case: EvalCase, response: Any) -> None:
    expected_rejection = case.expectations.expect_rejection
    if response.status_code == 400 and expected_rejection:
        reason = (response.json() or {}).get("reason")
        report.rejected = reason
        report.status = "passed" if reason == expected_rejection else "failed"
        if report.status == "failed":
            report.error = f"Rechazo con razón {reason!r}; se esperaba {expected_rejection!r}"
        return
    if response.status_code != 200:
        report.status, report.error = "error", _error_detail(response)
        return
    if expected_rejection:
        report.status, report.error = "failed", f"Se esperaba el rechazo {expected_rejection!r} y la API estimó"
        return
    body = response.json()
    try:
        result = EstimationResult.model_validate(body["result"])
    except (KeyError, ValidationError) as exc:
        report.status, report.error = "error", f"Respuesta con formato inesperado ({type(exc).__name__})"
        return
    report.prompt_version = body.get("prompt_version")
    report.estimation = _brief(result)
    trace = body.get("audit_trace")
    report.acb_final_decision = trace.get("final_decision") if isinstance(trace, dict) else None
    report.metrics = evaluate_case(result, case)
    report.status = "passed" if all(metric.passed for metric in report.metrics.values()) else "failed"


def select_cases(
    dataset: EvalDataset, limit: int | None = None, ids: Sequence[str] = (), categories: Sequence[str] = ()
) -> list[EvalCase]:
    cases = [c for c in dataset.cases if (not ids or c.id in ids) and (not categories or c.category in categories)]
    return cases[:limit] if limit is not None else cases


def run_evaluation(
    client: Client,
    cases: Sequence[EvalCase],
    *,
    mode: str,
    dataset_version: str,
    target: str = "in-process",
    prompt_version: str | None = None,
    tier: str | None = None,
    progress: Callable[[CaseReport], None] | None = None,
) -> Report:
    if mode not in MODES:
        raise ValueError(f"mode debe ser uno de {MODES}")
    report = Report(
        dataset=dataset_version,
        mode=mode,
        target=target,
        started_at=datetime.now(timezone.utc).isoformat(),
        cases=[],
        prompt_version_requested=prompt_version,
    )
    for case in cases:
        case_report = run_case(client, case, mode, prompt_version, tier)
        report.cases.append(case_report)
        if progress:
            progress(case_report)
    return report


@contextmanager
def open_client(base_url: str | None, timeout: float):
    """`httpx.Client` contra `base_url` o, sin ella, la aplicación en proceso con `TestClient`."""
    if base_url:
        import httpx

        with httpx.Client(base_url=base_url, timeout=timeout) as client:
            yield client
        return
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:  # dentro de `with`: un solo bucle de eventos y ciclo de vida de la app
        yield client


def _print_progress(case: CaseReport) -> None:
    mark = {"passed": "PASS", "failed": "FAIL", "error": "ERR "}[case.status]
    note = f"  {case.error}" if case.error else ""
    print(f"{mark} {case.id:<18} {case.latency_ms:>7} ms{note}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals.runner", description=__doc__.split("\n\n")[0])
    parser.add_argument("--mode", choices=MODES, default="actor", help="actor: /estimate · acb: /estimate-acb")
    parser.add_argument("--base-url", help="URL de la API (p. ej. http://localhost:8000); sin ella, en proceso.")
    parser.add_argument("--dataset", type=Path, help="Ruta de un dataset (por defecto reference_v1.json).")
    parser.add_argument("--limit", type=int, help="Evalúa solo los primeros N casos (tras filtrar).")
    parser.add_argument("--case", action="append", default=[], metavar="ID", help="Solo este caso (repetible).")
    parser.add_argument("--category", action="append", default=[], choices=CATEGORIES, help="Solo esta categoría.")
    parser.add_argument("--prompt-version", help="Versión del prompt (por defecto la configurada en la API).")
    parser.add_argument("--tier", choices=("executive", "pm", "developer", "default"), help="Audiencia explícita.")
    parser.add_argument("--timeout", type=float, default=300.0, help="Segundos por petición HTTP (con --base-url).")
    parser.add_argument("--output", type=Path, help="Escribe el reporte JSON en esta ruta.")
    parser.add_argument("--list", action="store_true", help="Lista los casos y termina.")
    return parser


def main(argv: Sequence[str] | None = None, client_factory: Callable[..., Any] = open_client) -> int:
    args = build_parser().parse_args(argv)
    if args.limit is not None and args.limit < 1:
        print("--limit debe ser al menos 1", file=sys.stderr)
        return EXIT_USAGE
    try:
        dataset = load_dataset(args.dataset)
    except ValueError as exc:
        print(str(exc)[:1000], file=sys.stderr)
        return EXIT_USAGE
    cases = select_cases(dataset, args.limit, args.case, args.category)
    unknown = sorted(set(args.case) - {c.id for c in dataset.cases})
    if unknown:
        print(f"Casos desconocidos: {', '.join(unknown)}", file=sys.stderr)
        return EXIT_USAGE
    if not cases:
        print("Ningún caso seleccionado.", file=sys.stderr)
        return EXIT_USAGE
    if args.list:
        for case in cases:
            print(f"{case.id:<18} {case.category:<15} {case.title}")
        return EXIT_OK

    print(f"Dataset v{dataset.version} · modo {args.mode} · {len(cases)} casos", flush=True)
    with client_factory(args.base_url, args.timeout) as client:
        report = run_evaluation(
            client,
            cases,
            mode=args.mode,
            dataset_version=dataset.version,
            target=args.base_url or "in-process",
            prompt_version=args.prompt_version,
            tier=args.tier,
            progress=_print_progress,
        )
    totals = report.totals
    print(
        f"Evaluados {totals['evaluated']} · aprobados {totals['passed']} · fallidos {totals['failed']} "
        f"(errores {totals['errors']})"
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Reporte: {args.output}")
    return EXIT_OK if report.ok else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
