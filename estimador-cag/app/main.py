import structlog
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routers import estimations
from app.logging_config import configure_logging

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


app = FastAPI(
    title="Software Estimation CAG API",
    description=(
        "Genera estimaciones de proyectos de software a partir de transcripciones "
        "de reuniones con clientes, inyectando ejemplos históricos directamente en "
        "el contexto del LLM (Context-Augmented Generation)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(estimations.router, prefix="/api/v1", tags=["estimations"])
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


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
