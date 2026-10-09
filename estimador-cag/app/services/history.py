"""Historial persistente de estimaciones en PostgreSQL (SQLAlchemy asíncrono).

Es opcional y nunca condiciona la estimación: sin `DATABASE_URL` queda desactivado y un fallo
al guardar se registra (sin datos del usuario) y devuelve `None`. La lectura sí informa de la
indisponibilidad con `HistoryUnavailable`, que el router traduce a 503 saneado.
"""

import asyncio
from datetime import datetime, timezone

import structlog
from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, inspect, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import Settings, get_settings
from app.schemas import EstimationRequest, EstimationResult
from app.schemas.history import EXCERPT_CHARS, EstimationDetail, EstimationSummary
from app.services.pipeline import PipelineOutcome

logger = structlog.get_logger(__name__)

NOT_CONFIGURED = "History is not configured"
UNAVAILABLE = "History is unavailable"

# JSONB en PostgreSQL; JSON genérico en el resto (las pruebas usan SQLite).
_Json = JSON().with_variant(JSONB(), "postgresql")


class HistoryUnavailable(Exception):
    """El historial no está configurado o la base de datos no responde."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class Base(DeclarativeBase):
    pass


class EstimationRecord(Base):
    __tablename__ = "estimations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    description: Mapped[str] = mapped_column(Text)
    options: Mapped[dict] = mapped_column(_Json)
    result: Mapped[dict] = mapped_column(_Json)
    prompt_version: Mapped[str] = mapped_column(String(10))
    cached: Mapped[bool] = mapped_column(Boolean)
    cache_source: Mapped[str] = mapped_column(String(10))
    model: Mapped[str] = mapped_column(String(100), default="")
    provider: Mapped[str] = mapped_column(String(20), default="")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[dict | None] = mapped_column(_Json, nullable=True)
    # Conversación (sesión) de la que procede la estimación y metadatos del proyecto tras ese turno.
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    metadata_snapshot: Mapped[dict | None] = mapped_column(_Json, nullable=True)


def _add_missing_columns(connection) -> None:
    """`create_all` no altera tablas existentes: añade las columnas nuevas a una base anterior.

    Idempotente y solo aditivo (columnas nulas), válido en PostgreSQL y SQLite."""
    table = EstimationRecord.__table__
    existing = {column["name"] for column in inspect(connection).get_columns(table.name)}
    for column in table.columns:
        if column.name in existing:
            continue
        column_type = column.type.compile(dialect=connection.dialect)
        connection.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {column_type}"))
        if column.index:
            connection.execute(
                text(f"CREATE INDEX IF NOT EXISTS ix_{table.name}_{column.name} ON {table.name} ({column.name})")
            )


def _aware(value: datetime) -> datetime:
    """SQLite devuelve fechas sin zona horaria: se interpretan como UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _summary(record: EstimationRecord) -> EstimationSummary:
    result = EstimationResult.model_validate(record.result)
    return EstimationSummary(
        id=record.id,
        requested_at=_aware(record.requested_at),
        project_type=record.options["project_type"],
        detail_level=record.options["detail_level"],
        output_format=record.options["output_format"],
        prompt_version=record.prompt_version,
        cache_source=record.cache_source,
        confidence_pct=result.confidence_pct,
        total_cost_eur=result.total_cost_eur,
        total_duration_weeks=result.total_duration_weeks,
        out_of_scope=result.out_of_scope,
        description_excerpt=record.description[:EXCERPT_CHARS],
    )


def _detail(record: EstimationRecord) -> EstimationDetail:
    return EstimationDetail(
        id=record.id,
        requested_at=_aware(record.requested_at),
        completed_at=_aware(record.completed_at),
        description=record.description,
        options=record.options,
        result=record.result,
        prompt_version=record.prompt_version,
        cached=record.cached,
        cache_source=record.cache_source,
        model=record.model,
        provider=record.provider,
        metrics=record.metrics,
        conversation_id=record.conversation_id,
        metadata_snapshot=record.metadata_snapshot,
    )


class EstimationHistory:
    def __init__(self, settings: Settings, engine: AsyncEngine | None = None):
        self.settings = settings
        self._engine = engine
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return self._engine is not None or bool(self.settings.database_url)

    def _sessions(self) -> async_sessionmaker:
        if self._engine is None:
            self._engine = create_async_engine(self.settings.database_url, pool_pre_ping=True)
        return async_sessionmaker(self._engine, expire_on_commit=False)

    async def _ensure_schema(self) -> None:
        # `create_all` es idempotente; se ejecuta una vez por proceso y reintenta si falla.
        if self._schema_ready:
            return
        async with self._schema_lock:
            if not self._schema_ready:
                self._sessions()
                async with self._engine.begin() as connection:
                    await connection.run_sync(Base.metadata.create_all)
                    await connection.run_sync(_add_missing_columns)
                self._schema_ready = True

    async def save(
        self,
        request: EstimationRequest,
        outcome: PipelineOutcome,
        requested_at: datetime,
        *,
        conversation_id: str | None = None,
        metadata_snapshot: dict | None = None,
    ) -> int | None:
        """Guarda una estimación completada; devuelve su id, o `None` si no se pudo guardar.

        En una sesión, `conversation_id` y `metadata_snapshot` asocian la estimación con su conversación."""
        if not self.enabled:
            return None
        try:
            await self._ensure_schema()
            record = EstimationRecord(
                description=request.description,
                options=request.model_dump(mode="json", exclude={"description"}),
                result=outcome.result.model_dump(mode="json"),
                prompt_version=outcome.prompt_version,
                cached=outcome.cached,
                cache_source=outcome.cache_source,
                model=outcome.model,
                provider=outcome.provider,
                requested_at=requested_at,
                completed_at=datetime.now(timezone.utc),
                metrics=outcome.metrics().model_dump(mode="json"),
                conversation_id=conversation_id,
                metadata_snapshot=metadata_snapshot,
            )
            async with self._sessions()() as session:
                session.add(record)
                await session.commit()
                return record.id
        except Exception as exc:
            logger.warning("history_save_failed", error_type=type(exc).__name__)
            return None

    async def list_recent(self, limit: int) -> list[EstimationSummary]:
        statement = (
            select(EstimationRecord)
            .order_by(EstimationRecord.requested_at.desc(), EstimationRecord.id.desc())
            .limit(limit)
        )
        records = await self._read(statement)
        return [_summary(record) for record in records]

    async def get(self, estimation_id: int) -> EstimationDetail | None:
        records = await self._read(select(EstimationRecord).where(EstimationRecord.id == estimation_id))
        return _detail(records[0]) if records else None

    async def latest_for_conversation(self, conversation_id: str) -> EstimationDetail | None:
        """Última estimación asociada a una conversación (con su snapshot de metadatos), si existe."""
        records = await self._read(
            select(EstimationRecord)
            .where(EstimationRecord.conversation_id == conversation_id)
            .order_by(EstimationRecord.requested_at.desc(), EstimationRecord.id.desc())
            .limit(1)
        )
        return _detail(records[0]) if records else None

    async def _read(self, statement) -> list[EstimationRecord]:
        if not self.enabled:
            raise HistoryUnavailable(NOT_CONFIGURED)
        try:
            await self._ensure_schema()
            async with self._sessions()() as session:
                return list((await session.scalars(statement)).all())
        except Exception as exc:
            logger.warning("history_read_failed", error_type=type(exc).__name__)
            raise HistoryUnavailable(UNAVAILABLE) from None

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


_instances: dict[str | None, EstimationHistory] = {}


def get_history() -> EstimationHistory:
    """Dependencia de FastAPI: una instancia (y su pool) por URL; las pruebas la sustituyen."""
    settings = get_settings()
    if settings.database_url not in _instances:
        _instances[settings.database_url] = EstimationHistory(settings)
    return _instances[settings.database_url]


async def close_history() -> None:
    """Libera los pools al apagar la aplicación."""
    instances = list(_instances.values())
    _instances.clear()
    for history in instances:
        await history.close()
