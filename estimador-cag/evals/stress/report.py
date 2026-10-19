"""Genera `REPORT.md` a partir del CSV del stress test: tablas por escenario × tamaño y tres curvas.

    uv run python -m evals.stress.report --input evals/stress/results.csv --output evals/stress/REPORT.md

Todas las cifras salen del CSV (sin librerías de análisis ni gráficos: tablas Markdown con barras ASCII).
El análisis en prosa vive en `evals/stress/analysis.md`, que se incrusta tal cual; el generador solo pone un
aviso si falta. Los percentiles usan interpolación lineal.
"""

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from evals.stress.scenarios import ALLOWED_N, PROFILES

HERE = Path(__file__).parent
TOKEN_BINS = ((0, 2_000), (2_000, 4_000), (4_000, 8_000), (8_000, 16_000), (16_000, 32_000), (32_000, 10**9))
BAR_WIDTH = 24
NUMERIC = {
    "attachment_kb", "repeat", "turn_index", "server_turn_index", "tokens_in", "tokens_out", "cost_usd",
    "latency_ms", "wall_latency_ms", "messages_in_window", "anchors_count", "summary_chars", "http_status",
    "latency_budget_score", "cost_budget_score", "memory_recall", "facts_evaluated", "facts_retained",
    "stale_facts_present", "attachment_fact_retained", "enriched_transcript_chars", "attachments_total_chars",
    "attachment_bytes", "attachment_extracted_chars", "latency_budget_ms", "cost_budget_usd",
}  # fmt: skip


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            row: dict[str, Any] = {}
            for key, value in raw.items():
                row[key] = (float(value) if value != "" else None) if key in NUMERIC else value
            rows.append(row)
    return rows


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return statistics.fmean(values) if values else None


def _fmt(value: float | None, digits: int = 0, suffix: str = "") -> str:
    return "n/d" if value is None else f"{value:,.{digits}f}{suffix}".replace(",", " ")


def _pct(part: int, total: int) -> str:
    return "n/d" if not total else f"{100 * part / total:.0f}%"


def _bar(value: float | None, maximum: float) -> str:
    if value is None or maximum <= 0:
        return ""
    return "█" * max(1, round(BAR_WIDTH * value / maximum))


def _table(headers: Sequence[str], body: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(cells) + " |" for cells in body]
    return "\n".join(lines)


def _ok(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filas de turnos observados (sin error)."""
    return [r for r in rows if not r["error"] and r["tokens_in"] is not None]


def cold_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filas de sesiones sin ningún acierto de caché: las únicas cuya latencia y coste miden el CAG."""
    rows = list(rows)
    warm = {r["session_id"] for r in rows if r["cache_hit_kind"] in ("exact", "semantic")}
    return [r for r in rows if r["session_id"] not in warm]


def session_costs(rows: Iterable[dict[str, Any]]) -> dict[tuple, float]:
    totals: dict[tuple, float] = defaultdict(float)
    for r in rows:
        totals[(r["scenario"], r["attachment_kb"], r["repeat"])] += r["cost_usd"] or 0.0
    return totals


def cumulative_cost_at(rows: Sequence[dict[str, Any]], turn: int, group: Callable[[dict], Any]) -> dict[Any, float]:
    """Coste acumulado medio por sesión hasta `turn`, por grupo."""
    per_session: dict[tuple, float] = defaultdict(float)
    owner: dict[tuple, Any] = {}
    for r in rows:
        if r["turn_index"] is not None and r["turn_index"] <= turn:
            key = (r["scenario"], r["attachment_kb"], r["repeat"])
            per_session[key] += r["cost_usd"] or 0.0
            owner[key] = group(r)
    grouped: dict[Any, list[float]] = defaultdict(list)
    for key, total in per_session.items():
        grouped[owner[key]].append(total)
    return {g: statistics.fmean(v) for g, v in grouped.items()}


def summary_table(rows: Sequence[dict[str, Any]]) -> str:
    body = []
    scenarios = [p for p in PROFILES if any(r["scenario"] == p for r in rows)]
    sizes = sorted({int(r["attachment_kb"]) for r in rows})
    for scenario in scenarios:
        for size in sizes:
            group = [r for r in rows if r["scenario"] == scenario and int(r["attachment_kb"]) == size]
            observed = _ok(group)
            cold = cold_rows(group)
            latencies = [r["latency_ms"] for r in _ok(cold)]
            costs = session_costs(cold)
            exact = sum(r["cache_hit_kind"] == "exact" for r in observed)
            semantic = sum(r["cache_hit_kind"] == "semantic" for r in observed)
            recall = _mean(r["memory_recall"] for r in observed if r["memory_recall"] is not None)
            body.append(
                [
                    scenario,
                    str(size),
                    f"{len({r['session_id'] for r in cold})}/{len({r['session_id'] for r in group})}",
                    _fmt(percentile(latencies, 0.5)),
                    _fmt(percentile(latencies, 0.95)),
                    _fmt(_mean(costs.values()), 4),
                    _pct(exact, len(observed)),
                    _pct(semantic, len(observed)),
                    _fmt(recall, 2),
                ]
            )
    return _table(
        ["Escenario", "Adjunto KB", "Sesiones frías", "Latencia P50 ms", "Latencia P95 ms", "Coste acum. USD/sesión",
         "Hit exacto", "Hit semántico", "Recall medio"],
        body,
    )  # fmt: skip


def latency_vs_tokens(rows: Sequence[dict[str, Any]]) -> str:
    observed = _ok(cold_rows(rows))
    stats = []
    for low, high in TOKEN_BINS:
        values = [r for r in observed if low <= r["tokens_in"] < high]
        latencies = [r["latency_ms"] for r in values]
        stats.append((low, high, len(values), percentile(latencies, 0.5), percentile(latencies, 0.95)))
    maximum = max((s[3] or 0 for s in stats), default=0)
    body = []
    for low, high, n, p50, p95 in stats:
        label = f"{low:,}–{high:,}".replace(",", " ") if high < 10**9 else f"≥ {low:,}".replace(",", " ")
        body.append([label, str(n), _fmt(p50), _fmt(p95), _bar(p50, maximum)])
    return _table(["tokens_in del turno", "Turnos", "P50 ms", "P95 ms", "P50 (barra)"], body)


def cost_vs_turn(rows: Sequence[dict[str, Any]]) -> str:
    rows = cold_rows(rows)
    sizes = sorted({int(r["attachment_kb"]) for r in rows})
    turns = [n for n in ALLOWED_N if any(r["turn_index"] == n for r in rows)]
    by_turn = {t: cumulative_cost_at(rows, t, lambda r: int(r["attachment_kb"])) for t in turns}
    maximum = max((v for d in by_turn.values() for v in d.values()), default=0)
    body = [[f"{kb} KB", *[_fmt(by_turn[t].get(kb), 4) for t in turns], _bar(by_turn[turns[-1]].get(kb), maximum)]
            for kb in sizes]  # fmt: skip
    return _table(["Adjunto", *[f"turno {t}" for t in turns], f"turno {turns[-1]} (barra)"], body)


def recall_vs_n(rows: Sequence[dict[str, Any]]) -> str:
    scenarios = [p for p in PROFILES if any(r["scenario"] == p for r in rows)]
    turns = [n for n in ALLOWED_N if any(r["turn_index"] == n for r in rows)]
    body = []
    for scenario in scenarios:
        cells = []
        for n in turns:
            values = [r["memory_recall"] for r in rows if r["scenario"] == scenario and r["turn_index"] == n
                      and r["memory_recall"] is not None]  # fmt: skip
            cells.append(_fmt(_mean(values), 2))
        body.append([scenario, *cells])
    overall = []
    for n in turns:
        values = [r["memory_recall"] for r in rows if r["turn_index"] == n and r["memory_recall"] is not None]
        overall.append(_fmt(_mean(values), 2))
    body.append(["**todos**", *overall])
    return _table(["Escenario", *[f"N={n}" for n in turns]], body)


def memory_notes(rows: Sequence[dict[str, Any]]) -> list[str]:
    """Observaciones de memoria al final de cada sesión (último turno medido)."""
    notes = []
    final = [r for r in _ok(rows) if r["turn_index"] == max(r2["turn_index"] for r2 in rows if r2["turn_index"])]
    stale_labels = (
        ("pivot", "Django (sustituido en el turno 5) sigue en la memoria"),
        ("contradiction", "el presupuesto de 30.000 EUR (sustituido en el turno 8) sigue en la memoria"),
    )
    for scenario, label in stale_labels:
        group = [r for r in final if r["scenario"] == scenario]
        if group:
            stale = sum((r["stale_facts_present"] or 0) > 0 for r in group)
            notes.append(f"- `{scenario}`: {label} en {stale} de {len(group)} sesiones ({_pct(stale, len(group))}).")
    atlas = [r for r in final if r["scenario"] == "growing" and r["memory_details"]]
    if atlas:
        kept = sum('"Atlas":[]' not in r["memory_details"] for r in atlas)
        notes.append(
            f"- `growing`: el nombre original (Atlas) sobrevive en memoria en {kept} de {len(atlas)} sesiones."
        )
    attached = [r for r in final if r["attachment_kb"] and r["attachment_fact_retained"] is not None]
    for kb in sorted({int(r["attachment_kb"]) for r in attached}):
        group = [r for r in attached if int(r["attachment_kb"]) == kb]
        kept = sum(r["attachment_fact_retained"] == 1 for r in group)
        notes.append(
            f"- Adjunto de {kb} KB: el hecho `Veridian` del turno 1 está en memoria al final "
            f"en {kept} de {len(group)} sesiones."
        )
    return notes


def budget_notes(rows: Sequence[dict[str, Any]]) -> list[str]:
    observed = _ok(cold_rows(rows))
    if not observed:
        return []
    lat_budget, cost_budget = observed[0]["latency_budget_ms"], observed[0]["cost_budget_usd"]
    lat_ok = sum(r["latency_budget_score"] == 1.0 for r in observed)
    cost_ok = sum(r["cost_budget_score"] == 1.0 for r in observed)
    total = len(observed)
    return [
        f"- Presupuesto de latencia {lat_budget:.0f} ms: cumplen {lat_ok} de {total} turnos ({_pct(lat_ok, total)}).",
        f"- Presupuesto de coste {cost_budget} USD/turno: cumplen {cost_ok} de {total} turnos "
        f"({_pct(cost_ok, total)}).",
    ]


def render(rows: Sequence[dict[str, Any]], source: str, analysis: str | None, note: str = "") -> str:
    observed = _ok(rows)
    sessions = {r["session_id"] for r in rows if r["session_id"]}
    models = sorted({r["model"] for r in observed if r["model"]})
    providers = ", ".join(models) or "n/d"
    errors = len(rows) - len(observed)
    run_ids = ", ".join(sorted({r["run_id"] for r in rows}))
    total_cost = sum(r["cost_usd"] or 0 for r in observed)
    parts = [
        "# Stress test del CAG: baseline de degradación",
        "",
        f"Fuente: `{source}` (ejecución {run_ids}). {len(rows)} filas (una por turno), {len(sessions)} sesiones, "
        f"{errors} turnos con error. Modelo: {providers} (un único proveedor). "
        f"Coste total medido: {total_cost:.2f} USD. {note}".rstrip(),
        "",
        "## 1. Escenario × tamaño de adjunto",
        "",
        _table_intro(),
        "",
        summary_table(rows),
        "",
        "## 2. Curvas",
        "",
        "**Latencia vs `tokens_in`** (todas las llamadas del turno):",
        "",
        latency_vs_tokens(rows),
        "",
        "**Coste acumulado por sesión vs turno** (USD, media por tamaño de adjunto):",
        "",
        cost_vs_turn(rows),
        "",
        "**Recall de memoria vs N** (fracción de hechos vigentes presentes en resumen, anclas o metadatos):",
        "",
        recall_vs_n(rows),
        "",
        "## 3. Observaciones de memoria y presupuestos",
        "",
        *memory_notes(rows),
        *budget_notes(rows),
        "",
        "## 4. Análisis",
        "",
        analysis.strip() if analysis else "_Pendiente: escribir `evals/stress/analysis.md` a partir de estas tablas._",
        "",
        "## 5. Límites",
        "",
        LIMITS,
        "",
        "## 6. Reproducir",
        "",
        REPRODUCE,
    ]
    return "\n".join(parts) + "\n"


def _table_intro() -> str:
    return (
        "Latencia, `tokens_in` y coste usan solo las sesiones frías (sin ningún acierto de caché; las repeticiones "
        "idénticas aciertan la caché de completions y miden la caché, no el CAG). Coste acumulado: media por sesión "
        "de 20 turnos. Hit exacto/semántico: fracción de todos los turnos con `cache_hit_kind` exact/semantic. "
        "Recall: media de todos los turnos con hechos que evaluar."
    )


LIMITS = """- El tope de texto de la API es `MAX_DESCRIPTION_CHARS` = 80 000 caracteres entre transcripción y adjuntos y
  se rechaza (413) en vez de truncar; no existe un `MAX_ATTACHMENT_CHARS` de 60 000. El PDF de 100 KB extrae
  73 238 caracteres: queda a 6 762 del tope.
- Las sesiones no pasan por la caché exacta ni la semántica del pipeline (su resultado depende del historial):
  solo por la caché de completions del wrapper (Redis del Compose). Por eso el hit semántico es 0 por construcción
  y el exacto solo aparece al repetir una sesión idéntica.
- El adjunto se envía solo en el turno 1; `latency_ms`, `tokens_in` y coste suman todas las llamadas del turno.
- Coincidencia exacta de hechos: una paráfrasis del modelo cuenta como olvido (falso negativo).
- Con `--workers` > 1 la latencia incluye la contención de la API del proveedor."""

REPRODUCE = """```sh
# desde la raíz del repositorio (Docker; estimador-cag/.env con la clave del proveedor)
docker compose up -d --build estimador-cag          # API + Redis + PostgreSQL del proyecto
docker compose -f docker-compose.verify.yml run --rm api-stress \
    --http http://host.docker.internal:8000 --scenarios growing,pivot,contradiction \
    --attachment-sizes 0,5,20,50,100 --repeats 3 --workers 4 --output evals/stress/results.csv
docker compose -f docker-compose.verify.yml run --rm --entrypoint python api-stress -m evals.stress.report
```

Para vaciar la caché antes de otra medición: `docker compose exec redis redis-cli FLUSHALL`.
Sin `--http` el runner usa la
aplicación en proceso. Pruebas: `docker compose -f docker-compose.verify.yml run --rm api-test`."""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.stress.report", description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", type=Path, default=HERE / "results.csv")
    parser.add_argument("--output", type=Path, default=HERE / "REPORT.md")
    parser.add_argument("--analysis", type=Path, default=HERE / "analysis.md")
    parser.add_argument("--note", default="", help="Texto libre para la cabecera (p. ej. workers usados).")
    args = parser.parse_args(argv)
    if not args.input.is_file():
        print(f"No existe {args.input}", file=sys.stderr)
        return 2
    rows = load_rows(args.input)
    if not rows:
        print("El CSV no tiene filas", file=sys.stderr)
        return 2
    analysis = args.analysis.read_text(encoding="utf-8") if args.analysis.is_file() else None
    try:
        source = args.input.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        source = args.input.name
    args.output.write_text(render(rows, source, analysis, args.note), encoding="utf-8")
    print(f"Reporte: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
