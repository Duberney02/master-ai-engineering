"""Evaluación estructural de una estimación generada (sin llamadas al LLM).

Comprueba la respuesta contra el formato que exige el prompt en español:
encabezados obligatorios y su orden, la tabla `| # | Área | Tarea | Horas |`,
las líneas del Resumen (total, rango, equipo, duración), la coherencia
numérica entre la tabla y los totales declarados, y el motivo de finalización
del proveedor (respuestas truncadas).

Es puro texto → regex: no hace E/S y es barato de ejecutar dentro del endpoint.
"""

import re

from app.schemas.estimation import EstimationEvaluation

OK_FINISH_REASONS = {"stop", "end_turn", "stop_sequence"}
TRUNCATED_FINISH_REASONS = {"length", "max_tokens"}
# Tolerancia (en horas) al comparar el total declarado con la suma del desglose.
HOURS_TOLERANCE = 1.0

_FLAGS = re.MULTILINE | re.IGNORECASE

# Clave -> patrón del encabezado, en el orden en que el prompt exige las secciones.
SECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    "titulo": re.compile(r"^##\s+Estimaci[oó]n\s*:\s*\S", _FLAGS),
    "supuestos": re.compile(r"^###\s+Supuestos\b", _FLAGS),
    "requisitos_identificados": re.compile(r"^###\s+Requisitos\s+identificados\b", _FLAGS),
    "desglose_de_tareas": re.compile(r"^###\s+Desglose\s+de\s+tareas\b", _FLAGS),
    "resumen": re.compile(r"^###\s+Resumen\b", _FLAGS),
    "riesgos_e_incertidumbres": re.compile(r"^###\s+Riesgos\s+e\s+incertidumbres\b", _FLAGS),
    "preguntas_abiertas": re.compile(r"^###\s+Preguntas\s+abiertas\b", _FLAGS),
}

# Número con separador de miles (1.200 / 1,200) o decimal (12,5 / 12.5).
_NUM = r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)"
_LABEL_SEP = r"\s*\**\s*:?\s*\**\s*[~≈]?\s*"

_TABLE_HEADER_RE = re.compile(r"^\|\s*#\s*\|\s*[ÁA]rea\s*\|\s*Tarea\s*\|\s*Horas\s*\|\s*$", _FLAGS)
_SEPARATOR_RE = re.compile(r"^\|[\s:|-]+\|?\s*$")
_HOURS_CELL_RE = re.compile(rf"^\**\s*[~≈]?\s*{_NUM}(?:\s*[–—-]\s*{_NUM})?\s*(?:h|hs|horas)?\s*\**$", re.I)
_TOTAL_RE = re.compile(rf"Total\s+estimado{_LABEL_SEP}{_NUM}", re.I)
_RANGE_RE = re.compile(
    rf"Rango\s+recomendado{_LABEL_SEP}{_NUM}\s*(?:h|horas)?\s*[–—-]\s*{_NUM}", re.I
)
_TEAM_RE = re.compile(r"Equipo\s+recomendado\s*\**\s*:?\s*\**\s*\S", re.I)
_DURATION_RE = re.compile(r"Duraci[oó]n\s+aproximada\s*\**\s*:?\s*\**\s*\S", re.I)


def _to_number(raw: str) -> float:
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", raw):
        return float(re.sub(r"[.,]", "", raw))
    return float(raw.replace(",", "."))


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _parse_table(text: str) -> tuple[bool, list[tuple[float, float]], int]:
    """Devuelve (hay_encabezado, filas[(min, max)], filas_con_horas_no_interpretables)."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if _TABLE_HEADER_RE.match(line.strip())), None)
    if start is None:
        return False, [], 0

    rows: list[tuple[float, float]] = []
    unparsed = 0
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            break  # fin de la tabla
        if _SEPARATOR_RE.match(stripped):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 4 or not re.fullmatch(r"\**\d+\**", cells[0]):
            continue  # filas sin número de orden (p. ej. una fila "Total") no cuentan
        match = _HOURS_CELL_RE.match(cells[-1])
        if not match:
            unparsed += 1
            continue
        low = _to_number(match.group(1))
        high = _to_number(match.group(2)) if match.group(2) else low
        rows.append((low, high))
    return True, rows, unparsed


def evaluate_estimation(
    text: str,
    finish_reason: str,
    preprocessing_finish_reason: str | None = None,
) -> EstimationEvaluation:
    """Evalúa la estructura y la coherencia numérica de una estimación."""
    issues: list[str] = []

    # --- Secciones obligatorias y orden -------------------------------------
    positions: dict[str, int] = {}
    for key, pattern in SECTION_PATTERNS.items():
        match = pattern.search(text)
        if match:
            positions[key] = match.start()
    sections = {key: key in positions for key in SECTION_PATTERNS}
    ordered_positions = [positions[k] for k in SECTION_PATTERNS if k in positions]
    sections_in_order = bool(ordered_positions) and ordered_positions == sorted(ordered_positions)

    for key, present in sections.items():
        if not present:
            issues.append(f"Falta la sección obligatoria «{key}»")
    if positions and not sections_in_order:
        issues.append("Las secciones no siguen el orden exigido por el formato")

    # --- Tabla de desglose y suma de horas ----------------------------------
    has_table, rows, unparsed = _parse_table(text)
    if not has_table:
        issues.append("Falta la tabla de desglose con encabezado '| # | Área | Tarea | Horas |'")
    elif not rows:
        issues.append("La tabla de desglose no tiene filas con horas interpretables")
    if unparsed:
        issues.append(f"{unparsed} fila(s) de la tabla tienen un valor de horas no interpretable")
    sum_min = sum(low for low, _ in rows) if rows else None
    sum_max = sum(high for _, high in rows) if rows else None

    # --- Resumen: total, rango, equipo y duración ---------------------------
    total_match = _TOTAL_RE.search(text)
    declared_total = _to_number(total_match.group(1)) if total_match else None
    range_match = _RANGE_RE.search(text)
    range_min = _to_number(range_match.group(1)) if range_match else None
    range_max = _to_number(range_match.group(2)) if range_match else None
    has_team = bool(_TEAM_RE.search(text))
    has_duration = bool(_DURATION_RE.search(text))

    if declared_total is None:
        issues.append("Falta la línea 'Total estimado' en el Resumen")
    if range_min is None:
        issues.append("Falta la línea 'Rango recomendado' con formato X–Y horas")
    if not has_team:
        issues.append("Falta la línea 'Equipo recomendado' en el Resumen")
    if not has_duration:
        issues.append("Falta la línea 'Duración aproximada' en el Resumen")

    hours_match: bool | None = None
    if declared_total is not None and sum_min is not None and sum_max is not None:
        hours_match = sum_min - HOURS_TOLERANCE <= declared_total <= sum_max + HOURS_TOLERANCE
        if not hours_match:
            suma = _fmt(sum_min) if sum_min == sum_max else f"{_fmt(sum_min)}–{_fmt(sum_max)}"
            issues.append(
                f"Discrepancia numérica: el total declarado ({_fmt(declared_total)} h) no "
                f"coincide con la suma de la tabla ({suma} h)"
            )

    range_consistent: bool | None = None
    if declared_total is not None and range_min is not None and range_max is not None:
        range_consistent = range_min <= declared_total <= range_max
        if not range_consistent:
            issues.append(
                f"Discrepancia numérica: el total ({_fmt(declared_total)} h) queda fuera del "
                f"rango recomendado ({_fmt(range_min)}–{_fmt(range_max)} h)"
            )

    # --- Motivo de finalización ---------------------------------------------
    finish_reason_ok = finish_reason in OK_FINISH_REASONS
    truncated = finish_reason in TRUNCATED_FINISH_REASONS
    if truncated:
        issues.append(
            f"Respuesta truncada por el límite de tokens (finish_reason='{finish_reason}'); "
            "aumenta max_tokens"
        )
    elif not finish_reason_ok:
        issues.append(f"Finalización inesperada del proveedor (finish_reason='{finish_reason}')")
    if preprocessing_finish_reason in TRUNCATED_FINISH_REASONS:
        issues.append(
            "La extracción de requisitos (fase 1) se truncó; la estimación pudo partir de "
            "requisitos incompletos"
        )

    # --- Puntuación: fracción de comprobaciones superadas -------------------
    checks = [
        *sections.values(),
        sections_in_order,
        has_table,
        bool(rows),
        has_team,
        has_duration,
        hours_match is True,
        range_consistent is True,
        finish_reason_ok,
    ]
    score = round(sum(checks) / len(checks), 3)

    return EstimationEvaluation(
        sections=sections,
        sections_in_order=sections_in_order,
        has_breakdown_table=has_table,
        table_rows=len(rows),
        declared_total_hours=declared_total,
        sum_row_hours_min=sum_min,
        sum_row_hours_max=sum_max,
        hours_match=hours_match,
        range_min=range_min,
        range_max=range_max,
        range_consistent=range_consistent,
        has_team=has_team,
        has_duration=has_duration,
        finish_reason_ok=finish_reason_ok,
        truncated=truncated,
        score=score,
        issues=issues,
    )
