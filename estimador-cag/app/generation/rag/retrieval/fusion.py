"""Fusión de rankings (Sesión 10): Reciprocal Rank Fusion y *round-robin*.

RRF fusiona por POSICIÓN, no por puntuación, que es lo que hace falta cuando las ramas dan puntuaciones
incomparables: distancia coseno (menor es mejor) en la vectorial y `ts_rank_cd` (mayor es mejor) en la léxica.
Normalizar ambas a una escala común es delicado y depende del corpus; RRF solo confía en el orden de cada rama.

La puntuación de un documento es `sum(1 / (k + posición))` sobre cada ranking en el que aparece (posición desde 0). La
constante `k` amortigua las primeras posiciones: con `k` alto un documento debe puntuar bien en AMBAS ramas; con `k`
bajo un único primer puesto domina. 60 es el valor del artículo original (Cormack et al.).

*Round-robin* es la fusión de la DESCOMPOSICIÓN de consultas: cada subconsulta posee un tema distinto, así que el
consenso de RRF (lo que muchas ramas comparten sube) sería incorrecto; el primero de cada lista ocupa un hueco antes
que el segundo de ninguna, y la cobertura gana al acuerdo.

Funciones puras y síncronas: sin E/S, triviales de probar.
"""

from collections.abc import Callable, Hashable
from itertools import zip_longest
from typing import TypeVar

DEFAULT_RRF_K = 60

T = TypeVar("T")


def reciprocal_rank_fusion(rankings: list[list[int]], *, k: int = DEFAULT_RRF_K) -> list[tuple[int, float]]:
    """Fusiona rankings de ids en uno, de mejor a peor.

    Cada rama aporta su lista ya ordenada (vacía si no devolvió nada: no suma puntuación). Un id repetido dentro de
    un mismo ranking solo cuenta en su mejor posición. Devuelve `(id, puntuación)` ordenado por puntuación
    descendente; los empates se resuelven por id ascendente para que la salida sea determinista.
    """
    if k <= 0:
        raise ValueError("la constante de suavizado k de RRF debe ser positiva")

    scores: dict[int, float] = {}
    for ranking in rankings:
        seen: set[int] = set()
        for position, chunk_id in enumerate(ranking):
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + position)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def round_robin_merge(
    ranked_lists: list[list[T]], *, key: Callable[[T], Hashable] = lambda item: item  # type: ignore[assignment,return-value]
) -> list[T]:
    """Intercala varias listas ordenadas posición a posición, sin duplicados.

    Se conserva la primera aparición de cada elemento (por `key`). Entre colecciones los ids de chunk pueden
    coincidir (cada tabla tiene su secuencia), así que quien llama pasa una clave compuesta `(colección, id)`.
    """
    seen: set[Hashable] = set()
    merged: list[T] = []
    for column in zip_longest(*ranked_lists):
        for item in column:
            if item is None:
                continue
            identity = key(item)
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(item)
    return merged
