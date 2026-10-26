"""Repositorio de mappings de seudónimos.

`lookup_or_create` es la operación que llama el seudonimizador por cada entidad detectada y debe
ser idempotente bajo concurrencia: dos llamadas paralelas con el mismo `(entity_type, original_hash)`
convergen en el mismo seudónimo; si no, el corpus tendría dos seudónimos para la misma persona.

Se apoya en la restricción UNIQUE de PostgreSQL: primero se inserta con `ON CONFLICT DO NOTHING` y,
si hubo conflicto, se lee la fila ganadora. Es más barato que SELECT-luego-INSERT y no necesita bloqueos.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.foundation.persistence.models import PseudonymMappingRow


@dataclass(frozen=True)
class Mapping:
    """Vista en memoria de una fila; los repositorios no filtran tipos de SQLAlchemy."""

    entity_type: str
    original_hash: str
    pseudonym: str
    created_at: datetime


class MappingsRepository:
    """Envoltorio fino sobre la tabla `pseudonym_mappings`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lookup(self, entity_type: str, original_hash: str) -> Mapping | None:
        row = (
            await self._session.execute(
                select(PseudonymMappingRow).where(
                    PseudonymMappingRow.entity_type == entity_type,
                    PseudonymMappingRow.original_hash == original_hash,
                )
            )
        ).scalar_one_or_none()
        return _to_mapping(row) if row is not None else None

    async def lookup_or_create(
        self,
        entity_type: str,
        original_hash: str,
        new_pseudonym_factory: Callable[[], str],
    ) -> Mapping:
        """Devuelve el mapping existente o inserta uno nuevo.

        `new_pseudonym_factory` solo se invoca cuando no hay mapping previo: generar un valor con
        Faker es barato, pero inútil si ya existe.
        """
        existing = await self.lookup(entity_type, original_hash)
        if existing is not None:
            return existing

        statement = (
            pg_insert(PseudonymMappingRow)
            .values(entity_type=entity_type, original_hash=original_hash, pseudonym=new_pseudonym_factory())
            .on_conflict_do_nothing(index_elements=["entity_type", "original_hash"])
            .returning(PseudonymMappingRow)
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        await self._session.commit()

        if row is not None:
            return _to_mapping(row)

        # Otro escritor ganó la carrera: se lee la fila ganadora.
        winner = await self.lookup(entity_type, original_hash)
        assert winner is not None, "la restricción única garantiza que existe una fila ganadora"
        return winner

    async def forget(self, entity_type: str, original_hash: str) -> bool:
        """Elimina un mapping; devuelve si existía."""
        deleted = await self._session.execute(
            delete(PseudonymMappingRow).where(
                PseudonymMappingRow.entity_type == entity_type,
                PseudonymMappingRow.original_hash == original_hash,
            )
        )
        await self._session.commit()
        return deleted.rowcount > 0


def _to_mapping(row: PseudonymMappingRow) -> Mapping:
    return Mapping(
        entity_type=row.entity_type,
        original_hash=row.original_hash,
        pseudonym=row.pseudonym,
        created_at=row.created_at,
    )
