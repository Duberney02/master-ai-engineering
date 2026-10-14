from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.logging_config import configure_logging
from app.routers import estimations, history, project_estimations, prompts, sessions
from app.services.guardrails import GuardrailViolation
from app.services.history import close_history

logger = structlog.get_logger(__name__)


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
    yield
    await close_history()


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
app.include_router(estimations.router, prefix="/api/v1/transcription", tags=["transcription"])
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
