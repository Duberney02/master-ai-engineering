"""Similitud coseno y percentiles con la biblioteca estándar (sin NumPy)."""

import math
from collections.abc import Sequence


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """dot(a, b) / (norm(a) * norm(b)). Falla con vectores de distinta dimensión o de norma cero."""
    if len(a) != len(b):
        raise ValueError(f"vectors must have the same dimension ({len(a)} != {len(b)})")
    dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(math.fsum(x * x for x in a))
    norm_b = math.sqrt(math.fsum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        raise ValueError("cosine similarity is undefined for a zero-norm vector")
    return dot / (norm_a * norm_b)


def percentile(values: Sequence[float], q: float) -> float:
    """Percentil `q` (0-100) por interpolación lineal; 0.0 si no hay valores."""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return float(ordered[low])
    return float(ordered[low] + (ordered[high] - ordered[low]) * (position - low))
