"""Formateo de metadatos para la interfaz (funciones puras, sin Streamlit).

Los valores desconocidos (`null` en la API) se muestran como «desconocido»,
nunca como 0.
"""

from typing import Any

UNKNOWN = "desconocido"

PREPROCESSING_LABELS = {
    "none": "Ninguno",
    "inline_cleaning": "Limpieza en el prompt",
    "two_phase": "Dos fases (extracción + estimación)",
}
CACHE_LABELS = {
    "hit": "acierto",
    "shared": "compartido (petición idéntica en curso)",
    "partial": "parcial",
    "miss": "fallo",
    "disabled": "desactivada",
    "error": "no disponible",
}
TRUNCATED_FINISH_REASONS = {"length", "max_tokens"}


def fmt_int(value: Any) -> str:
    return UNKNOWN if value is None else str(value)


def fmt_usd(value: Any) -> str:
    if value is None:
        return UNKNOWN
    return f"${value:.6f}" if value < 0.01 else f"${value:.4f}"


def fmt_cache(value: Any) -> str:
    return CACHE_LABELS.get(value, UNKNOWN if value is None else str(value))


def summary_metrics(metadata: dict[str, Any]) -> list[tuple[str, str]]:
    usage = metadata.get("usage") or {}
    cost = metadata.get("cost") or {}
    cache = metadata.get("cache") or {}
    return [
        ("Modelo", metadata.get("model") or UNKNOWN),
        ("Proveedor", metadata.get("provider") or UNKNOWN),
        ("Tokens de entrada", fmt_int(usage.get("input_tokens"))),
        ("Tokens de salida", fmt_int(usage.get("output_tokens"))),
        ("Latencia (ms)", fmt_int(metadata.get("latency_ms"))),
        ("Finalización", metadata.get("finish_reason") or UNKNOWN),
        ("Caché", fmt_cache(cache.get("status"))),
        ("Coste de esta solicitud", fmt_usd(cost.get("incurred_usd"))),
    ]


def detail_lines(metadata: dict[str, Any]) -> list[str]:
    usage = metadata.get("usage") or {}
    cost = metadata.get("cost") or {}
    lines = [
        f"Tokens incurridos en esta solicitud: {fmt_int(usage.get('incurred_total_tokens'))}",
        f"Coste original de la generación: {fmt_usd(cost.get('original_generation_usd'))}",
        f"Ahorro por reutilización: {fmt_usd(cost.get('saved_usd'))}",
    ]
    if metadata.get("fallback_used"):
        lines.append("Se usó el modelo secundario (fallback)")
    for phase in usage.get("phases") or []:
        phase_cost = phase.get("cost") or {}
        lines.append(
            f"Fase {phase.get('phase')}: {phase.get('provider')}/{phase.get('model') or UNKNOWN} · "
            f"caché {fmt_cache(phase.get('cache'))} · tokens {fmt_int(phase.get('input_tokens'))}/"
            f"{fmt_int(phase.get('output_tokens'))} · {fmt_int(phase.get('latency_ms'))} ms · "
            f"coste incurrido {fmt_usd(phase_cost.get('incurred_usd'))}"
        )
    evaluation = metadata.get("evaluation")
    if evaluation:
        lines.append(f"Evaluación estructural: {evaluation.get('score')}")
    return lines


def is_truncated(metadata: dict[str, Any] | None) -> bool:
    if not metadata:
        return False
    evaluation = metadata.get("evaluation") or {}
    return bool(evaluation.get("truncated")) or metadata.get("finish_reason") in TRUNCATED_FINISH_REASONS
