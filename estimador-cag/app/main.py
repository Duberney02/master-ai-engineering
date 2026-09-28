import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.dependencies import AppResources, build_resources
from app.observability import RequestContextMiddleware, configure_logging
from app.routers import estimations

logger = logging.getLogger(__name__)

ResourcesFactory = Callable[[Settings], AppResources]


def create_app(
    settings_provider: Callable[[], Settings] = get_settings,
    resources_factory: ResourcesFactory = build_resources,
) -> FastAPI:
    """Crea la aplicación. Los recursos (clientes de proveedores, Redis, wrapper y
    servicio) se construyen una vez en el arranque y se cierran al apagar; en pruebas
    se sustituyen pasando otra `resources_factory`."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings = settings_provider()
        configure_logging(settings.log_level, settings.resolved_log_format())
        resources = resources_factory(settings)
        app.state.resources = resources
        policy = resources.service.policy
        logger.info(
            "app_started",
            extra={
                "env": settings.app_env,
                "primary_model": str(policy.primary),
                "fallback_model": str(policy.fallback) if policy.fallback else None,
                "cache_enabled": resources.cache.enabled,
                "llm_timeout_s": settings.llm_timeout_seconds,
                "llm_max_retries": settings.llm_max_retries,
            },
        )
        try:
            yield
        finally:
            await resources.aclose()
            logger.info("app_stopped")

    app = FastAPI(
        title="Software Estimation CAG API",
        description=(
            "Genera estimaciones de proyectos de software a partir de transcripciones "
            "de reuniones con clientes, inyectando ejemplos históricos directamente en "
            "el contexto del LLM (Context-Augmented Generation). Incluye streaming SSE, "
            "fallback entre modelos y caché Redis de coincidencia exacta."
        ),
        version="2.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(estimations.router, prefix="/api/v1", tags=["estimations"])

    @app.get("/health", tags=["ops"])
    async def health() -> JSONResponse:
        resources: AppResources = app.state.resources
        policy = resources.service.policy
        redis_ok = await resources.cache.ping()
        # La API sigue sana sin Redis (modo degradado): la caché se informa aparte.
        return JSONResponse(
            content={
                "status": "healthy",
                "environment": resources.settings.app_env,
                "provider": policy.primary.provider,
                "model": policy.primary.name,
                "fallback_model": str(policy.fallback) if policy.fallback else None,
                "cache": {
                    "enabled": resources.cache.enabled,
                    "reachable": redis_ok,
                },
            }
        )

    return app


app = create_app()
