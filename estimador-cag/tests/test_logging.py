import json
import logging

import pytest
import structlog

from app.logging_config import configure_logging
from app.services.llm_service import generate_estimation
from tests._fakes import openai_response, openai_settings, patch_openai, patch_settings


@pytest.fixture(autouse=True)
def restore_logging():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    config = structlog.get_config().copy()
    names = ("openai", "anthropic", "httpx", "httpcore")
    levels = {name: logging.getLogger(name).level for name in names}
    yield
    for handler in root.handlers[:]:
        if handler not in handlers:
            handler.close()
    root.handlers = handlers
    root.setLevel(level)
    structlog.configure(**config)
    for name, original in levels.items():
        logging.getLogger(name).setLevel(original)


def test_structlog_production_json_keeps_typed_fields_and_context(capsys):
    configure_logging("production", "INFO")
    with structlog.contextvars.bound_contextvars(request_id="req-1"):
        structlog.get_logger("app.test").info(
            "llm_completed",
            model="demo",
            input_tokens=42,
            cost_usd=0.001,
            cache_hit=False,
            latency_ms=12,
        )
    event = json.loads(capsys.readouterr().err)
    assert event["event"] == "llm_completed"
    assert event["logger"] == "app.test" and event["level"] == "info"
    assert event["input_tokens"] == 42 and event["cost_usd"] == 0.001
    assert event["cache_hit"] is False and event["request_id"] == "req-1"
    assert event["timestamp"]
    assert "extra" not in event and "_record" not in event


def test_structlog_filters_sensitive_fields_and_exception_text(capsys):
    configure_logging("production", "INFO")
    try:
        raise RuntimeError("exception-secret")
    except RuntimeError:
        structlog.get_logger("app.test").error(
            "llm_call_failed",
            error_type="RuntimeError",
            exc_info=True,
            api_key="api-secret",
            transcription="private-transcript",
        )
    output = capsys.readouterr().err
    event = json.loads(output)
    assert event["error_type"] == "RuntimeError"
    assert all(secret not in output for secret in ("exception-secret", "api-secret", "private-transcript"))


def test_standard_logging_uses_same_json_renderer(capsys):
    configure_logging("production", "INFO")
    logging.getLogger("app.legacy").info("legacy_event", extra={"model": "demo", "api_key": "secret"})
    event = json.loads(capsys.readouterr().err)
    assert event["event"] == "legacy_event" and event["model"] == "demo"
    assert "api_key" not in event


def test_development_console_and_level_filter(capsys):
    configure_logging("development", "WARNING")
    logger = structlog.get_logger("app.test")
    logger.info("hidden_event")
    logger.warning("visible_event", provider="openai")
    output = capsys.readouterr().err
    assert "hidden_event" not in output
    assert "visible_event" in output and "provider=openai" in output
    assert not output.lstrip().startswith("{")


async def test_service_emits_structured_events_without_transcription(mocker, capsys):
    configure_logging("production", "INFO")
    patch_settings(mocker, openai_settings())
    patch_openai(mocker, openai_response("Estimación privada"))
    await generate_estimation("Transcripción privada que no debe aparecer en logs")
    output = capsys.readouterr().err
    events = [json.loads(line) for line in output.splitlines()]
    started = next(e for e in events if e["event"] == "estimation_started")
    completed = next(e for e in events if e["event"] == "llm_completed")
    assert started["preprocessing"] == "none"
    assert completed["input_tokens"] == 100 and completed["provider"] == "openai"
    assert "Transcripción privada" not in output and "Estimación privada" not in output
