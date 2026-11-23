"""Reranker con cross-encoder (Sesión 10): reordena candidatos con un modelo que ve consulta y documento JUNTOS.

Un bi-encoder (el embedding) codifica consulta y documento por separado, así que la «relevancia» es el coseno de dos
vectores calculados sin que ninguno vea al otro: rápido, pero pierde relevancia fina. Un cross-encoder pasa el PAR
`(consulta, documento)` por el modelo y devuelve una única puntuación: mucho más preciso y demasiado lento para todo el
corpus. De ahí *recall-then-rerank*: las ramas vectorial y léxica recuperan un conjunto amplio de forma barata y el
cross-encoder solo repuntúa ese conjunto.

Este módulo es el envoltorio (carga del modelo y puntuación de pares); no decide el ancho del recall ni el corte final.

* **Carga diferida.** Importar el módulo no importa `torch` ni descarga pesos: el modelo se carga en el primer uso,
  protegido por un *lock* para que dos primeras llamadas concurrentes no lo carguen dos veces. Con el reranking
  apagado nunca se carga.
* **Sin bloquear el event loop.** La carga y la inferencia son síncronas y pesadas: se ejecutan en un hilo
  (`asyncio.to_thread`).
* **Falsificable.** `Reranker` es un protocolo: las pruebas inyectan un reranker falso desde `app/dependencies.py` y
  ningún test descarga pesos.
"""

import asyncio
import threading
import time
from collections.abc import Callable, Sequence
from typing import Protocol, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")


class Reranker(Protocol):
    """Contrato mínimo del reranker: puntuaciones por documento, en el orden de entrada (mayor es mejor)."""

    async def score(self, query: str, documents: Sequence[str]) -> list[float]: ...


class CrossEncoderReranker:
    """Cross-encoder de `sentence-transformers` con carga diferida; una instancia posee un modelo cargado."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model = None  # sentence_transformers.CrossEncoder, cargado bajo demanda
        self._load_lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _ensure_loaded(self):
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:  # otro hilo ganó la carrera
                return self._model
            # Import local: el grafo de imports (arranque de la app y tests) queda libre de torch hasta que se
            # reordena de verdad.
            from sentence_transformers import CrossEncoder

            started = time.perf_counter()
            self._model = CrossEncoder(self._model_name)
            logger.info(
                "reranker_loaded", model=self._model_name, load_ms=round((time.perf_counter() - started) * 1000)
            )
            return self._model

    async def load(self) -> None:
        """Carga el modelo ya (calentamiento y scripts de evaluación)."""
        await asyncio.to_thread(self._ensure_loaded)

    def _score_sync(self, query: str, documents: Sequence[str]) -> list[float]:
        model = self._ensure_loaded()
        started = time.perf_counter()
        scores = model.predict([(query, document) for document in documents])
        logger.info(
            "reranker_scored",
            model=self._model_name,
            pairs=len(documents),
            score_ms=round((time.perf_counter() - started) * 1000),
        )
        return [float(score) for score in scores]

    async def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        return await asyncio.to_thread(self._score_sync, query, documents)


async def rerank_with_scores(
    reranker: Reranker,
    query: str,
    candidates: Sequence[T],
    *,
    top_n: int,
    text_of: Callable[[T], str] = lambda candidate: candidate.content,  # type: ignore[attr-defined]
) -> list[tuple[T, float]]:
    """`(candidato, puntuación)` de los `top_n` mejores según el reranker.

    La puntuación cruda del cross-encoder se expone para que una etapa posterior (el *decay* temporal) vuelva a
    ponderar los finalistas con un número de relevancia real y no solo por posición. Estable ante empates: Python
    ordena de forma estable y los candidatos conservan su orden de recall.
    """
    if not candidates:
        return []
    scores = await reranker.score(query, [text_of(candidate) for candidate in candidates])
    ranked = sorted(zip(candidates, scores, strict=True), key=lambda pair: pair[1], reverse=True)
    return [(candidate, float(score)) for candidate, score in ranked[:top_n]]
