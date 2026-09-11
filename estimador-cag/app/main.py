import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import estimations

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.DEBUG),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info(
        "Starting estimador-cag env=%s provider=%s model=%s",
        settings.app_env,
        settings.llm_provider,
        settings.effective_model(),
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
