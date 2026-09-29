"""Configuración común para structlog y registros de la biblioteca estándar."""

import logging

import structlog

# Solo metadatos operativos: nunca prompts, credenciales ni excepciones crudas.
SAFE_FIELDS = frozenset({
    "event", "timestamp", "level", "logger", "environment", "provider", "model",
    "input_tokens", "output_tokens", "total_tokens", "cost_usd", "latency_ms",
    "finish_reason", "cache_hit", "error_type", "preprocessing", "example_format",
    "num_examples", "use_examples", "max_tokens", "transcription_chars", "request_id",
})


def _operational_fields(logger, method_name, event_dict):
    return {key: value for key, value in event_dict.items() if key in SAFE_FIELDS}


def configure_logging(environment: str, level: str) -> None:
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    renderer = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if environment == "production"
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.stdlib.ExtraAdder(allow=SAFE_FIELDS),
            *shared,
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _operational_fields,
            renderer,
        ],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        handlers=[handler],
        force=True,
    )
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    # Los mensajes de transporte/SDK pueden contener datos de solicitudes.
    for name in ("openai", "anthropic", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
