from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app.api import config as runtime_config_api
from app.api import (
    estimate,
    estimate_stages,
    estimations,
    history,
    ingestion,
    project_estimations,
    prompts,
    retrieval,
    sessions,
)
from app.api.embeddings import router as embeddings_router
from app.api.rate_limiting import limiter, rate_limit_exceeded_handler
from app.api.request_id import request_id_middleware
from app.api.search import router as search_router
from app.config import get_settings
from app.dependencies import close_history
from app.foundation.guardrails.input import GuardrailViolation
from app.foundation.persistence.database import close_engine
from app.logging_config import configure_logging

logger = structlog.get_logger(__name__)


def _log_catalog() -> None:
    """Un catálogo malformado es un problema de despliegue: se registra al arrancar, no en la primera solicitud."""
    try:
        from app.dependencies import get_catalog

        catalog = get_catalog()
        logger.info(
            "catalog_loaded",
            version=catalog.version,
            sources_total=len(catalog.sources),
            sources_included=len(catalog.included_sources()),
        )
    except Exception as exc:
        logger.error("catalog_load_failed", error_type=type(exc).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.app_env, settings.log_level)
    logger.info(
        "application_started",
        environment=settings.app_env,
        provider=settings.llm_provider,
        model=settings.effective_model(),
    )
    _log_catalog()
    yield
    await close_history()
    await close_engine()


app = FastAPI(
    title="Software Estimation CAG API",
    description=(
        "Genera estimaciones de proyectos de software. `/api/v1/estimate` parte de una "
        "solicitud estructurada y prompts versionados; `/api/v1/transcription/*` parte de "
        "transcripciones de reuniones con ejemplos históricos en el contexto del LLM "
        "(Context-Augmented Generation)."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(project_estimations.router, prefix="/api/v1", tags=["estimations"])
app.include_router(prompts.router, prefix="/api/v1", tags=["prompts"])
app.include_router(history.router, prefix="/api/v1", tags=["history"])
app.include_router(sessions.router, prefix="/api/v1", tags=["sessions"])
app.include_router(ingestion.router, prefix="/api/v1")
app.include_router(estimations.router, prefix="/api/v1/transcription", tags=["transcription"])
app.include_router(embeddings_router, prefix="/embeddings")
app.include_router(search_router)
app.include_router(runtime_config_api.router)
# Sesión 9: RAG de estimación fundamentada, protegido por clave de API y limitado por clave.
app.include_router(retrieval.router)
app.include_router(estimate.router)
app.include_router(estimate_stages.router)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
# `X-Request-ID` en todas las respuestas y en los logs de la petición.
app.middleware("http")(request_id_middleware)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.exception_handler(GuardrailViolation)
async def guardrail_violation_handler(_request: Request, exc: GuardrailViolation) -> JSONResponse:
    return JSONResponse(status_code=400, content={"reason": exc.reason, "message": exc.message})


@app.get("/health", tags=["ops"])
async def health() -> JSONResponse:
    settings = get_settings()
    return JSONResponse(
        content={
            "status": "healthy",
            "environment": settings.app_env,
            "provider": settings.llm_provider,
            "model": settings.effective_model(),
        }
    )
