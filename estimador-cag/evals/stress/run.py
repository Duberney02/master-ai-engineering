"""Runner del stress test del CAG: ejecuta escenarios multi-turno contra la API y escribe un CSV por turno.

    uv run python -m evals.stress.run --http http://localhost:8000 \\
        --scenarios growing,pivot,contradiction --attachment-sizes 0,5,20,50,100 --repeats 3 \\
        --output evals/stress/results.csv

Sin `--http` usa la aplicación en proceso (`TestClient`), con el proveedor de `.env`. Crea una sesión por
escenario × tamaño de adjunto × repetición y ejecuta sus turnos en orden (el adjunto, si lo hay, va en el
turno 1 con el mismo transcript corto para todos los tamaños). Tras cada turno consulta
`GET /sessions/{id}?include_memory=true`: `last_turn` es la observación `turn_observed` y el resumen, las
anclas y los metadatos son el snapshot que evalúa `MemoryDriftMetric`. Reutiliza el cliente y el patrón de
`evals.runner`. Una fila por turno, también si el turno falla (campo `error`).
"""

import argparse
import csv
import json
import sys
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.runner import Client, _error_detail, open_client
from evals.stress.fixtures.build_pdfs import FACTS, GENERATED_DIR, AttachmentFixture, build_pdfs
from evals.stress.metrics import (
    DEFAULT_COST_BUDGET_USD,
    DEFAULT_LATENCY_BUDGET_MS,
    CostBudgetMetric,
    LatencyBudgetMetric,
    MemoryDriftMetric,
    Snapshot,
)
from evals.stress.scenarios import ALLOWED_N, PROFILES, PROJECT_TYPE, FactTracker, Scenario, build_scenario

EXIT_OK, EXIT_ERRORS, EXIT_USAGE = 0, 1, 2
DEFAULT_OUTPUT = Path(__file__).parent / "results.csv"
OBSERVED_FIELDS = (
    "enriched_transcript_chars",
    "attachments_total_chars",
    "messages_in_window",
    "anchors_count",
    "summary_chars",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "latency_ms",
    "cache_hit_kind",
    "last_resolved_tier",
)
COLUMNS = (
    "run_id",
    "scenario",
    "attachment_kb",
    "repeat",
    "session_id",
    "turn_index",
    "is_checkpoint",
    "server_turn_index",
    "model",
    *OBSERVED_FIELDS,
    "wall_latency_ms",
    "http_status",
    "error",
    "latency_budget_ms",
    "latency_budget_score",
    "cost_budget_usd",
    "cost_budget_score",
    "new_fact",
    "facts_evaluated",
    "facts_retained",
    "memory_recall",
    "stale_facts_present",
    "attachment_fact_retained",
    "attachment_bytes",
    "attachment_extracted_chars",
    "memory_details",
)


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    latency_budget_ms: float = DEFAULT_LATENCY_BUDGET_MS
    cost_budget_usd: float = DEFAULT_COST_BUDGET_USD
    max_turns: int = max(ALLOWED_N)


def _csv_ints(text: str, name: str) -> list[int]:
    try:
        values = [int(part) for part in text.split(",") if part.strip()]
    except ValueError:
        raise ValueError(f"{name} debe ser una lista de enteros separados por comas") from None
    if not values or any(v < 0 for v in values):
        raise ValueError(f"{name} debe contener enteros mayores o iguales que 0")
    return values


def _attachment(fixtures: dict[int, AttachmentFixture], size_kb: int) -> tuple[AttachmentFixture, bytes] | None:
    if size_kb == 0:
        return None
    fixture = fixtures[size_kb]
    return fixture, Path(fixture.path).read_bytes()


def _snapshot(turn_index: int, state: dict[str, Any]) -> Snapshot:
    return Snapshot(
        turn_index=turn_index,
        summary=state.get("summary") or "",
        anchors=tuple(state.get("anchors") or ()),
        metadata=state.get("project_metadata") or {},
    )


def run_session(
    client: Client,
    scenario: Scenario,
    size_kb: int,
    repeat: int,
    config: RunConfig,
    fixtures: dict[int, AttachmentFixture],
) -> list[dict[str, Any]]:
    """Ejecuta un escenario completo en una sesión nueva y devuelve una fila por turno. Nunca lanza."""
    latency_metric = LatencyBudgetMetric(config.latency_budget_ms)
    cost_metric = CostBudgetMetric(config.cost_budget_usd)
    drift = MemoryDriftMetric()
    tracker = FactTracker(scenario, drift)
    attachment = _attachment(fixtures, size_kb)
    base = {"run_id": config.run_id, "scenario": scenario.profile, "attachment_kb": size_kb, "repeat": repeat}
    rows: list[dict[str, Any]] = []

    created = client.post("/api/v1/sessions")
    if created.status_code != 201:
        return [
            {
                **base,
                "turn_index": 0,
                "http_status": created.status_code,
                "error": f"No se pudo crear la sesión ({_error_detail(created)})",
            }
        ]
    session_id = created.json()["session_id"]
    base["session_id"] = session_id

    for turn in scenario.prefix(config.max_turns):
        row: dict[str, Any] = {
            **base,
            "turn_index": turn.turn_index,
            "is_checkpoint": turn.turn_index in ALLOWED_N,
            "new_fact": turn.fact_to_remember or "",
            "latency_budget_ms": config.latency_budget_ms,
            "cost_budget_usd": config.cost_budget_usd,
        }
        rows.append(row)
        try:
            _run_turn(client, session_id, scenario, turn, attachment, tracker, latency_metric, cost_metric, drift, row)
        except Exception as exc:  # red, JSON ilegible…: el turno falla pero la ejecución sigue
            row["error"] = f"{type(exc).__name__}: {exc}"[:300]
    return rows


def _run_turn(client, session_id, scenario, turn, attachment, tracker, latency_metric, cost_metric, drift, row) -> None:
    form = {
        "transcript": turn.transcript,
        "project_type": PROJECT_TYPE,
        "detail_level": "medium",
        "output_format": "phases_table",
    }
    files = None
    if attachment is not None and turn.turn_index == 1:
        fixture, data = attachment
        files = [("attachments", (Path(fixture.path).name, data, "application/pdf"))]
        row["attachment_bytes"], row["attachment_extracted_chars"] = fixture.size_bytes, fixture.extracted_chars
    started = time.perf_counter()
    response = client.post(f"/api/v1/sessions/{session_id}/estimate", data=form, files=files)
    row["wall_latency_ms"] = int((time.perf_counter() - started) * 1000)
    row["http_status"] = response.status_code
    if response.status_code != 200:
        row["error"] = _error_detail(response)
        return
    row["model"] = (response.json().get("metrics") or {}).get("model", "")

    state_response = client.get(f"/api/v1/sessions/{session_id}", params={"include_memory": "true"})
    if state_response.status_code != 200:
        row["error"] = f"GET sesión: {_error_detail(state_response)}"
        return
    state = state_response.json()
    observed = state.get("last_turn")
    if not observed:
        row["error"] = "GET sesión sin last_turn"
        return
    row["server_turn_index"] = observed["turn_index"]
    for name in OBSERVED_FIELDS:
        row[name] = observed[name]
    row["latency_budget_score"] = latency_metric.evaluate(observed["latency_ms"]).score
    row["cost_budget_score"] = cost_metric.evaluate(observed["cost_usd"]).score

    checks = tracker.evaluate(_snapshot(turn.turn_index, state))
    active = [c for c in checks if c.active]
    row["facts_evaluated"] = len(active)
    row["facts_retained"] = sum(c.retained for c in active)
    recall = FactTracker.recall(checks)
    row["memory_recall"] = "" if recall is None else round(recall, 4)
    row["stale_facts_present"] = sum(c.stale_present for c in checks)
    row["memory_details"] = json.dumps(
        {c.fact.text: c.result.details["found_in"] for c in checks}, ensure_ascii=False, separators=(",", ":")
    )
    if attachment is not None and turn.turn_index >= 2:
        token = FACTS["head"][0]
        row["attachment_fact_retained"] = int(drift.evaluate(token, 1, _snapshot(turn.turn_index, state)).passed)


def run_matrix(
    client: Client,
    scenarios: Sequence[Scenario],
    sizes_kb: Sequence[int],
    repeats: int,
    config: RunConfig,
    fixtures: dict[int, AttachmentFixture],
    *,
    workers: int = 1,
    on_session: Callable[[list[dict[str, Any]]], None] | None = None,
) -> list[dict[str, Any]]:
    """Todas las combinaciones escenario × tamaño × repetición; `workers` sesiones a la vez."""
    jobs = [(s, kb, r) for r in range(1, repeats + 1) for s in scenarios for kb in sizes_kb]
    lock = threading.Lock()
    all_rows: list[dict[str, Any]] = []

    def work(job) -> None:
        scenario, kb, repeat = job
        rows = run_session(client, scenario, kb, repeat, config, fixtures)
        with lock:
            all_rows.extend(rows)
            if on_session:
                on_session(rows)

    if workers <= 1:
        for job in jobs:
            work(job)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(work, jobs))
    return all_rows


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, restval="", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals.stress.run", description=__doc__.split("\n\n")[0])
    parser.add_argument("--http", help="URL de la API (p. ej. http://localhost:8000); sin ella, en proceso.")
    parser.add_argument("--scenarios", default=",".join(PROFILES), help=f"Perfiles separados por comas: {PROFILES}.")
    parser.add_argument("--attachment-sizes", default="0,5,20,50,100", help="KB del PDF del turno 1 (0 = sin adjunto).")
    parser.add_argument("--repeats", type=int, default=1, help="Repeticiones por escenario × tamaño.")
    parser.add_argument("--max-turns", type=int, default=max(ALLOWED_N), help=f"Turnos por sesión, uno de {ALLOWED_N}.")
    parser.add_argument("--workers", type=int, default=1, help="Sesiones simultáneas (recomendado solo con --http).")
    parser.add_argument("--latency-budget-ms", type=float, default=DEFAULT_LATENCY_BUDGET_MS)
    parser.add_argument("--cost-budget-usd", type=float, default=DEFAULT_COST_BUDGET_USD)
    parser.add_argument("--timeout", type=float, default=300.0, help="Segundos por petición HTTP.")
    parser.add_argument("--fixtures-dir", type=Path, default=GENERATED_DIR, help="Dónde se regeneran los PDFs.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="CSV de salida (una fila por turno).")
    return parser


def main(argv: Sequence[str] | None = None, client_factory: Callable[..., Any] = open_client) -> int:
    args = build_parser().parse_args(argv)
    try:
        profiles = [p.strip() for p in args.scenarios.split(",") if p.strip()]
        scenarios = [build_scenario(p) for p in profiles]
        sizes = _csv_ints(args.attachment_sizes, "--attachment-sizes")
        if args.repeats < 1 or args.workers < 1:
            raise ValueError("--repeats y --workers deben ser al menos 1")
        if args.max_turns not in ALLOWED_N:
            raise ValueError(f"--max-turns debe ser uno de {ALLOWED_N}")
        if not scenarios:
            raise ValueError("ningún escenario seleccionado")
        config = RunConfig(
            run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            latency_budget_ms=args.latency_budget_ms,
            cost_budget_usd=args.cost_budget_usd,
            max_turns=args.max_turns,
        )
        LatencyBudgetMetric(config.latency_budget_ms), CostBudgetMetric(config.cost_budget_usd)  # validan
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE

    print("Regenerando PDFs sintéticos…", flush=True)
    fixtures = build_pdfs(args.fixtures_dir, sizes)
    for kb, fixture in fixtures.items():
        print(f"  {kb} KB: {fixture.size_bytes} bytes, {fixture.extracted_chars} caracteres extraídos", flush=True)
    total = len(scenarios) * len(sizes) * args.repeats
    print(f"{total} sesiones × {args.max_turns} turnos · destino {args.http or 'en proceso'}", flush=True)

    def progress(rows: list[dict[str, Any]]) -> None:
        first = rows[0]
        errors = sum(1 for r in rows if r.get("error"))
        last = rows[-1]
        print(
            f"{first['scenario']:<13} {first['attachment_kb']:>3} KB r{first['repeat']} · {len(rows)} turnos · "
            f"{errors} con error · último recall {last.get('memory_recall', '')}",
            flush=True,
        )

    with client_factory(args.http, args.timeout) as client:
        rows = run_matrix(
            client, scenarios, sizes, args.repeats, config, fixtures, workers=args.workers, on_session=progress
        )
    write_csv(args.output, rows)
    errors = sum(1 for r in rows if r.get("error"))
    print(f"{len(rows)} filas ({errors} con error) en {args.output}")
    return EXIT_OK if rows and errors == 0 else EXIT_ERRORS


if __name__ == "__main__":
    sys.exit(main())
