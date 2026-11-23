"""Logs estructurados por etapa del pipeline RAG (Sesión 9).

`log_stage` envuelve cada paso para que emita siempre el trío `rag_stage_started` / `rag_stage_completed` (con
`duration_ms`) / `rag_stage_failed`, correlacionado por el `request_id` de la petición (`X-Request-ID`). Solo se
registran metadatos operativos: nunca la transcripción, los prompts ni el texto de la excepción.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def current_request_id() -> str | None:
    """`request_id` vinculado por el middleware HTTP a los contextvars de structlog (o `None`)."""
    return structlog.contextvars.get_contextvars().get("request_id")


@contextmanager
def log_stage(stage: str, request_id: str | None = None, **context: Any) -> Iterator[None]:
    """Registra el ciclo de vida de una etapa; las excepciones se registran (solo su tipo) y se relanzan."""
    request_id = request_id or current_request_id()
    logger.info("rag_stage_started", stage=stage, request_id=request_id, **context)
    started = time.perf_counter()
    try:
        yield
    except Exception as exc:
        logger.error(
            "rag_stage_failed",
            stage=stage,
            request_id=request_id,
            duration_ms=_elapsed_ms(started),
            error_type=type(exc).__name__,
            **context,
        )
        raise
    logger.info("rag_stage_completed", stage=stage, request_id=request_id, duration_ms=_elapsed_ms(started), **context)


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
