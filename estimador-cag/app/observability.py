"""Logs estructurados e identificador de solicitud.

- `configure_logging`: formato legible en desarrollo y JSON (una línea por evento)
  en producción. Los campos se pasan con `extra={...}`.
- `RequestContextMiddleware`: middleware ASGI puro (compatible con streaming) que
  asigna/propaga `X-Request-ID`, registra inicio y fin de cada solicitud y deja el
  identificador en un `ContextVar` que añaden todos los logs.

Política: nunca se registran credenciales, transcripciones ni prompts; solo tamaños,
opciones, modelos, tokens, latencias, estados de caché y tipos de error.
"""

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}
_HANDLER_NAME = "estimador-cag"

logger = logging.getLogger("app.http")


def _fields(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS}


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        payload.update(_fields(record))
        if record.exc_info:
            # Solo el tipo: los mensajes de excepción de SDK pueden contener datos internos.
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(payload, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]
        fields = _fields(record)
        rid = fields.pop("request_id", None)
        extras = " ".join(f"{k}={v}" for k, v in fields.items())
        prefix = f"{ts} {record.levelname:<7} {record.name}"
        if rid:
            prefix += f" [{rid}]"
        return f"{prefix} {record.getMessage()}" + (f" {extras}" if extras else "")


def configure_logging(level: str, fmt: str) -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in list(root.handlers):
        if handler.get_name() == _HANDLER_NAME:
            root.removeHandler(handler)
    handler = logging.StreamHandler()
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(JsonFormatter() if fmt == "json" else ConsoleFormatter())
    handler.addFilter(_RequestIdFilter())
    root.addHandler(handler)
    # Los clientes HTTP de los SDK registran URLs y cabeceras en DEBUG.
    for noisy in ("httpx", "httpcore", "httpx2", "httpcore2", "openai", "anthropic", "redis"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def new_request_id(candidate: str | None = None) -> str:
    if candidate and _REQUEST_ID_RE.match(candidate):
        return candidate
    return uuid.uuid4().hex


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        raw = headers.get(b"x-request-id")
        request_id = new_request_id(raw.decode("latin-1") if raw else None)
        token = request_id_var.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        start = time.monotonic()
        status: dict[str, int] = {}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [
                    *message["headers"],
                    (b"x-request-id", request_id.encode("latin-1")),
                ]
            await send(message)

        logger.info("http_request_started", extra={"method": scope["method"], "path": scope["path"]})
        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException as exc:
            logger.error(
                "http_request_failed",
                extra={"path": scope["path"], "error_type": type(exc).__name__,
                       "duration_ms": int((time.monotonic() - start) * 1000)},
            )
            raise
        else:
            logger.info(
                "http_request_completed",
                extra={"method": scope["method"], "path": scope["path"],
                       "status": status.get("code"),
                       "duration_ms": int((time.monotonic() - start) * 1000)},
            )
        finally:
            request_id_var.reset(token)
