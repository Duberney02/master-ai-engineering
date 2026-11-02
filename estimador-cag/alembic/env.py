"""Entorno de migraciones Alembic de la persistencia de la ingesta (sesión 6).

La URL de la base de datos se lee de `app.config.Settings` (no de `alembic.ini`) para que el
contenedor, el anfitrión y el CI usen la misma fuente de verdad. Es la URL asíncrona de la aplicación
(`postgresql+asyncpg://…`), por lo que las migraciones se ejecutan con un motor asíncrono. Las
migraciones se descubren importando `app.foundation.persistence.models`: solo gestionan las tablas de la ingesta
y del almacén vectorial (`documents`, `chunks`), no la tabla `estimations` del historial.
"""

import asyncio
from logging.config import fileConfig

import pgvector.sqlalchemy
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from alembic import context
from app.config import get_settings
from app.foundation.persistence.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

database_url = get_settings().database_url
if not database_url:
    raise RuntimeError("DATABASE_URL is not configured; cannot run migrations")
# `%` en la URL (contraseñas con escapes) se interpreta como interpolación en ConfigParser.
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

target_metadata = Base.metadata

# Índices HNSW de la migración 0003: son sobre una expresión (`embedding::halfvec(1536)`) con operator class, que
# `alembic check` no sabe comparar con el modelo; viven solo en la migración y se excluyen de la comparación.
MIGRATION_ONLY_INDEXES = frozenset({"chunks_embedding_halfvec_idx", "chunks_embedding_idx"})


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Solo se comparan las tablas del modelo (no `estimations`, del historial) y no los índices solo-migración."""
    if type_ == "table" and reflected and name not in target_metadata.tables:
        return False
    if type_ == "index" and name in MIGRATION_ONLY_INDEXES:
        return False
    if type_ == "index" and reflected and obj.table.name not in target_metadata.tables:
        return False
    return True


def run_migrations_offline() -> None:
    """Genera el SQL sin conexión (`alembic upgrade --sql`)."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        include_object=include_object,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    # Sin esto Alembic no reconoce `vector` al reflejar la base y `alembic check` ve diferencias fantasma.
    connection.dialect.ischema_names["vector"] = pgvector.sqlalchemy.Vector
    connection.dialect.ischema_names["halfvec"] = pgvector.sqlalchemy.HALFVEC
    context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Aplica las migraciones sobre una conexión asíncrona real."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
