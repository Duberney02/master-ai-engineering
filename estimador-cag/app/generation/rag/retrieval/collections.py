"""Registro de colecciones del recuperador multi-índice (Sesión 10).

El corpus es heterogéneo (presupuestos históricos, transcripciones de reuniones, documentación técnica) y vive en tres
tablas. Este módulo es el ÚNICO sitio que conoce, por colección:

* el modelo ORM que la respalda,
* el `chunk_type` con el que se ingesta y la clave JSONB del id trazable del documento padre,
* cómo leer una fecha de su esquema de metadatos (divergente) para el *decay* temporal,
* los filtros duros que entiende (tecnologías, sectores, fecha mínima, versión) como predicados SQL, y
* los patrones de vocabulario deterministas del primer nivel del *router*.

Mantener ese conocimiento en un registro es lo que deja el resto del pipeline (router, recuperación, fusión) agnóstico
de la colección. `chunks` conserva su nombre: es la colección `budget` y su contrato con `POST /search` no cambia.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from sqlalchemy import Date, Integer, cast
from sqlalchemy.engine import Row

from app.foundation.persistence.models import Chunk, TechnicalDocChunk, TranscriptChunk
from app.generation.rag.schemas import Collection, RetrievedChunk

# `Collection` (conjunto cerrado de colecciones: destinos del *router* y claves del registro) vive en `schemas` porque
# es también un valor del contrato de la API; se reexporta desde aquí para quien trabaja con el registro.
__all__ = ["ALL_COLLECTIONS", "COLLECTIONS", "Collection", "CollectionSpec", "HardFilters", "match_rules", "spec_for"]


@dataclass(frozen=True)
class HardFilters:
    """Restricciones de metadatos aplicadas ANTES del ranking vectorial.

    Cada colección consume el subconjunto que entiende y ignora el resto. Un campo vacío o `None` significa «no
    restringir por este eje».
    """

    technologies: tuple[str, ...] = ()
    sectors: tuple[str, ...] = ()
    min_date: date | None = None  # presupuestos: año >= min_date.year; transcripciones: reunión >= min_date
    version: str | None = None  # solo documentación técnica


DateKind = Literal["year", "iso"]


@dataclass(frozen=True)
class CollectionSpec:
    """Todo lo que el pipeline necesita para tratar una colección de forma uniforme."""

    collection: Collection
    model: type
    chunk_type: str  # se estampa en cada chunk de la colección al ingestar
    source_id_key: str  # clave JSONB con el id trazable del documento padre
    date_key: str | None  # clave JSONB con la fecha del chunk (para el decay temporal)
    date_kind: DateKind | None  # "year" (entero) | "iso" (YYYY-MM-DD)
    rule_patterns: tuple[str, ...] = field(default_factory=tuple)

    def date_of(self, metadata: dict | None) -> date | None:
        """La fecha del chunk según el esquema de esta colección, o `None`."""
        if not self.date_key or self.date_kind is None:
            return None
        raw = (metadata or {}).get(self.date_key)
        if raw in (None, ""):
            return None
        try:
            if self.date_kind == "year":
                return date(int(raw), 1, 1)
            return date.fromisoformat(str(raw))
        except (ValueError, TypeError):
            return None

    def to_chunk(self, row: Row, *, distance: float, relevance_score: float | None = None) -> RetrievedChunk:
        """Una fila de esta colección como el contrato uniforme `RetrievedChunk`."""
        metadata = row.metadata_ or {}
        try:
            year = int(metadata.get("year") or 0)
        except (TypeError, ValueError):
            year = 0
        return RetrievedChunk(
            id=row.id,
            content=row.content,
            sector=str(metadata.get("client_sector") or "unknown"),
            project_year=year,
            chunk_type=row.chunk_type,
            distance=distance,
            budget_id=metadata.get("budget_id"),
            document_id=row.document_id,
            collection=self.collection.value,
            source_id=metadata.get(self.source_id_key),
            relevance_score=relevance_score,
            document_date=self.date_of(metadata),
            estimated_hours=metadata.get("estimated_hours"),
        )

    def hard_filter_clauses(self, filters: HardFilters) -> list:
        """Predicados SQL que incrustan `filters` en la consulta (solo los ejes que la colección entiende)."""
        metadata = self.model.metadata_
        clauses: list = []
        if self.collection is Collection.BUDGET:
            if filters.sectors:
                clauses.append(metadata["client_sector"].astext.in_(list(filters.sectors)))
            if filters.technologies:
                clauses.append(metadata["main_technology"].astext.in_(list(filters.technologies)))
            if filters.min_date is not None:
                clauses.append(cast(metadata["year"].astext, Integer) >= filters.min_date.year)
        elif self.collection is Collection.TRANSCRIPT:
            if filters.min_date is not None:
                clauses.append(cast(metadata["meeting_date"].astext, Date) >= filters.min_date)
        elif self.collection is Collection.TECHNICAL_DOC and filters.version is not None:
            clauses.append(metadata["version"].astext == filters.version)
        return clauses


# El orden del registro es el orden canónico de «buscar en todo» (respaldo del router).
COLLECTIONS: dict[Collection, CollectionSpec] = {
    Collection.BUDGET: CollectionSpec(
        collection=Collection.BUDGET,
        model=Chunk,
        chunk_type="budget_component",
        source_id_key="budget_id",
        date_key="year",
        date_kind="year",
        rule_patterns=(
            r"\bbudgets?\b",
            r"\bquotes?\b",
            r"\bquoted\b",
            r"\bestimat(?:e|ed|ion|es)\b",
            r"\bcosts?\b",
            r"\bhours?\b",
            r"\bhow much\b",
            r"\bprice[sd]?\b",
            r"\bpresupuestos?\b",
            r"\bcu[aá]nto cost[oó]\b",
        ),
    ),
    Collection.TRANSCRIPT: CollectionSpec(
        collection=Collection.TRANSCRIPT,
        model=TranscriptChunk,
        chunk_type="meeting_segment",
        source_id_key="transcript_id",
        date_key="meeting_date",
        date_kind="iso",
        rule_patterns=(
            r"\bmeetings?\b",
            r"\btranscripts?\b",
            r"\bcalls?\b",
            r"\bdiscuss(?:ed|ion)?\b",
            r"\bclient (?:said|asked|wants?|mentioned)\b",
            r"\bkick-?off\b",
            r"\bstand-?up\b",
            r"\breuni[oó]n(?:es)?\b",
            r"\btranscripci[oó]n(?:es)?\b",
        ),
    ),
    Collection.TECHNICAL_DOC: CollectionSpec(
        collection=Collection.TECHNICAL_DOC,
        model=TechnicalDocChunk,
        chunk_type="doc_section",
        source_id_key="doc_id",
        date_key=None,
        date_kind=None,
        rule_patterns=(
            r"\bdocument(?:ation|s)?\b",
            r"\bspec(?:ification)?s?\b",
            r"\bapi reference\b",
            r"\barchitecture\b",
            r"\bhow (?:do|to) (?:we|i) (?:implement|configure|integrate)\b",
            r"\brunbook\b",
            r"\bversion\b",
            r"\bdocumentaci[oó]n\b",
        ),
    ),
}

ALL_COLLECTIONS: tuple[Collection, ...] = tuple(COLLECTIONS)


def spec_for(collection: Collection) -> CollectionSpec:
    return COLLECTIONS[collection]


def match_rules(query_text: str) -> list[Collection]:
    """Nivel 1 del *router*: colecciones cuyo vocabulario aparece en la consulta, en orden del registro.

    Vacío = ninguna regla disparó (la cascada escala entonces al clasificador).
    """
    lowered = query_text.lower()
    return [
        collection
        for collection, spec in COLLECTIONS.items()
        if any(re.search(pattern, lowered) for pattern in spec.rule_patterns)
    ]
