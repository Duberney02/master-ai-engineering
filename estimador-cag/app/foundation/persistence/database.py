"""Motor asíncrono, fábrica de sesiones y dependencia de FastAPI para la persistencia de la ingesta.

Reutiliza `DATABASE_URL` (driver `asyncpg`), el mismo ajuste que usa el historial. El motor se crea
de forma perezosa: sin `DATABASE_URL` la aplicación arranca igualmente y solo la API de ingesta
responde 503.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

NOT_CONFIGURED = "Ingestion tracking is not configured"


@lru_cache
def create_engine_from_settings() -> AsyncEngine:
    """Motor global (singleton) construido con `Settings.database_url`."""
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return create_async_engine(url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(create_engine_from_settings(), expire_on_commit=False, autoflush=False)


def SessionLocal() -> AsyncSession:  # noqa: N802 - nombre de la referencia
    """Sesión nueva; el llamante la cierra. La usan las tareas en segundo plano."""
    return get_sessionmaker()()


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependencia de FastAPI: una sesión por solicitud, cerrada al terminar."""
    if not get_settings().database_url:
        raise HTTPException(503, NOT_CONFIGURED)
    async with SessionLocal() as session:
        yield session


async def close_engine() -> None:
    """Libera el pool al apagar la aplicación (sin efecto si nunca se creó)."""
    if create_engine_from_settings.cache_info().currsize:
        await create_engine_from_settings().dispose()
    get_sessionmaker.cache_clear()
    create_engine_from_settings.cache_clear()
