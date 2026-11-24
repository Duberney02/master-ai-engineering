"""Registro de colecciones y filtros duros (Sesión 10): mapeo, fecha por colección y predicados SQL."""

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.foundation.persistence.models import Chunk, TechnicalDocChunk, TranscriptChunk
from app.generation.rag.retrieval.collections import (
    ALL_COLLECTIONS,
    COLLECTIONS,
    Collection,
    HardFilters,
    match_rules,
    spec_for,
)


def _row(**extra) -> SimpleNamespace:
    base = {"id": 7, "document_id": 3, "chunk_type": "x", "content": "texto", "metadata_": {}}
    return SimpleNamespace(**{**base, **extra})


def _where(collection: Collection, filters: HardFilters) -> str:
    clauses = spec_for(collection).hard_filter_clauses(filters)
    return " AND ".join(str(c.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})) for c in clauses)


# --- Registro --------------------------------------------------------------------------------------------------


def test_the_registry_covers_the_three_collections_with_their_own_tables():
    assert ALL_COLLECTIONS == (Collection.BUDGET, Collection.TRANSCRIPT, Collection.TECHNICAL_DOC)
    assert spec_for(Collection.BUDGET).model is Chunk  # `chunks` conserva su nombre: es la colección budget
    assert spec_for(Collection.TRANSCRIPT).model is TranscriptChunk
    assert spec_for(Collection.TECHNICAL_DOC).model is TechnicalDocChunk
    assert {c.value for c in Collection} == {"budget", "transcript", "technical_doc"}


def test_each_collection_declares_its_chunk_type_and_traceable_id_key():
    assert [(s.chunk_type, s.source_id_key) for s in COLLECTIONS.values()] == [
        ("budget_component", "budget_id"),
        ("meeting_segment", "transcript_id"),
        ("doc_section", "doc_id"),
    ]


# --- Procedencia (to_chunk) -----------------------------------------------------------------------------------


def test_a_transcript_chunk_carries_its_collection_and_source_id():
    row = _row(metadata_={"transcript_id": "TR-2024-002", "meeting_date": "2024-03-15", "speakers": ["ana"]})

    chunk = spec_for(Collection.TRANSCRIPT).to_chunk(row, distance=0.25)

    assert chunk.collection == "transcript" and chunk.source_id == "TR-2024-002"
    assert chunk.document_date == date(2024, 3, 15) and chunk.distance == 0.25
    assert chunk.sector == "unknown" and chunk.project_year == 0 and chunk.budget_id is None


def test_a_budget_chunk_keeps_the_session_9_fields_and_adds_the_new_ones():
    row = _row(metadata_={"budget_id": "BUD-1", "client_sector": "finance", "year": 2022, "estimated_hours": 40})

    chunk = spec_for(Collection.BUDGET).to_chunk(row, distance=0.1, relevance_score=0.9)

    assert (chunk.collection, chunk.source_id, chunk.budget_id) == ("budget", "BUD-1", "BUD-1")
    assert (chunk.sector, chunk.project_year, chunk.estimated_hours) == ("finance", 2022, 40)
    assert chunk.document_date == date(2022, 1, 1) and chunk.relevance_score == 0.9
    assert chunk.document_id == 3


def test_a_technical_doc_chunk_has_a_source_id_and_no_date():
    chunk = spec_for(Collection.TECHNICAL_DOC).to_chunk(_row(metadata_={"doc_id": "DOC-1", "version": "2.1"}), distance=0.3)

    assert (chunk.collection, chunk.source_id, chunk.document_date) == ("technical_doc", "DOC-1", None)


@pytest.mark.parametrize(
    ("collection", "metadata", "expected"),
    [
        (Collection.BUDGET, {"year": 2021}, date(2021, 1, 1)),
        (Collection.BUDGET, {"year": "2021"}, date(2021, 1, 1)),
        (Collection.BUDGET, {"year": "n/a"}, None),
        (Collection.BUDGET, {}, None),
        (Collection.TRANSCRIPT, {"meeting_date": "2023-11-05"}, date(2023, 11, 5)),
        (Collection.TRANSCRIPT, {"meeting_date": "05/11/2023"}, None),
        (Collection.TRANSCRIPT, {"meeting_date": ""}, None),
        (Collection.TRANSCRIPT, {"year": 2023}, None),  # cada colección lee su propia clave de fecha
        (Collection.TECHNICAL_DOC, {"version": "3.0", "year": 2024}, None),
    ],
)
def test_the_date_is_read_from_each_collections_own_schema(collection, metadata, expected):
    assert spec_for(collection).date_of(metadata) == expected


def test_date_of_none_metadata_is_none():
    assert spec_for(Collection.BUDGET).date_of(None) is None


# --- Filtros duros ----------------------------------------------------------------------------------------------


def test_budget_hard_filters_map_sectors_technologies_and_year():
    where = _where(
        Collection.BUDGET,
        HardFilters(sectors=("finance",), technologies=("ruby_on_rails",), min_date=date(2023, 6, 1)),
    )

    assert "(chunks.metadata ->> 'client_sector') IN ('finance')" in where
    assert "(chunks.metadata ->> 'main_technology') IN ('ruby_on_rails')" in where
    assert "CAST((chunks.metadata ->> 'year') AS INTEGER) >= 2023" in where  # el año de min_date


def test_transcript_hard_filter_compares_the_meeting_date():
    where = _where(Collection.TRANSCRIPT, HardFilters(min_date=date(2024, 1, 1), sectors=("finance",)))

    assert "CAST((transcript_chunks.metadata ->> 'meeting_date') AS DATE) >= '2024-01-01'" in where
    assert "client_sector" not in where  # los sectores no se entienden en esta colección: se ignoran


def test_technical_doc_hard_filter_is_the_version():
    where = _where(Collection.TECHNICAL_DOC, HardFilters(version="2.1", min_date=date(2024, 1, 1), technologies=("x",)))

    assert where == "(technical_doc_chunks.metadata ->> 'version') = '2.1'"


def test_no_filters_emit_no_predicates_in_any_collection():
    for collection in Collection:
        assert spec_for(collection).hard_filter_clauses(HardFilters()) == []


# --- Reglas del router -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("How much did the marketplace budget cost?", [Collection.BUDGET]),
        ("What did the client say in the kickoff meeting?", [Collection.TRANSCRIPT]),
        ("Where is the API reference for the payments architecture?", [Collection.TECHNICAL_DOC]),
        ("budget and meeting notes", [Collection.BUDGET, Collection.TRANSCRIPT]),
        ("¿Cuánto costó el presupuesto de la reunión?", [Collection.BUDGET, Collection.TRANSCRIPT]),
        ("something unrelated", []),
    ],
)
def test_rules_match_the_vocabulary_of_each_collection_in_registry_order(query, expected):
    assert match_rules(query) == expected
