"""Migraciones `0004` (columna léxica) y `0005` (multi-índice) contra PostgreSQL real (Sesión 10).

Se omiten sin `TEST_DATABASE_URL`; `api-test` la define con la base efímera `api-db`.
"""

import asyncio
import os

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.foundation.persistence.migrate import ALEMBIC_INI, upgrade_to_head
from app.foundation.persistence.models import Chunk, Document, TechnicalDocChunk, TranscriptChunk

URL = os.getenv("TEST_DATABASE_URL")
pytestmark = [
    pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL no definida"),
    pytest.mark.skipif(
        bool(URL) and not URL.split("?")[0].endswith("test"), reason="la base de pruebas debe terminar en 'test'"
    ),
]

NEW_TABLES = ("transcript_chunks", "technical_doc_chunks")


@pytest.fixture
async def engine(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", URL)
    await asyncio.to_thread(upgrade_to_head)
    engine = create_async_engine(URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE documents, chunks RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


def _config() -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))
    return config


async def _indexes(engine, table: str) -> dict[str, str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = :t"), {"t": table}
        )
        return dict(rows.all())


async def _tables(engine) -> set[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        return set(rows.scalars())


async def test_content_tsv_is_a_generated_column_with_a_gin_index(engine):
    async with engine.connect() as connection:
        generated = (
            await connection.execute(
                text(
                    "SELECT is_generated FROM information_schema.columns "
                    "WHERE table_name = 'chunks' AND column_name = 'content_tsv'"
                )
            )
        ).scalar_one()
    indexes = await _indexes(engine, "chunks")

    assert generated == "ALWAYS"
    assert "gin" in indexes["ix_chunks_content_tsv"].lower()
    # `/search` no cambia: el índice HNSW de la Sesión 8 sigue ahí y `chunks` conserva su nombre.
    assert "chunks_embedding_halfvec_idx" in indexes


async def test_inserting_a_chunk_computes_content_tsv_without_the_application(engine):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        document = Document(source_path="test/tsv.json", document_type="historical_budget", metadata_={})
        session.add(document)
        await session.flush()
        session.add(Chunk(document_id=document.id, chunk_type="budget_component", content="Stripe Connect payouts"))
        await session.commit()
        matches = (
            await session.execute(
                text("SELECT count(*) FROM chunks WHERE content_tsv @@ plainto_tsquery('english', 'payout')")
            )
        ).scalar_one()

    assert matches == 1  # el stemming de `english` casa «payouts» con «payout»


async def test_the_transcript_and_technical_doc_tables_mirror_the_chunks_columns(engine):
    assert set(NEW_TABLES) <= await _tables(engine)
    async with engine.connect() as connection:
        columns = {
            table: (
                await connection.execute(
                    text(
                        "SELECT column_name, format_type(a.atttypid, a.atttypmod) FROM information_schema.columns c "
                        "JOIN pg_attribute a ON a.attrelid = c.table_name::regclass AND a.attname = c.column_name "
                        "WHERE c.table_name = :t"
                    ),
                    {"t": table},
                )
            ).all()
            for table in ("chunks", *NEW_TABLES)
        }
        cascade = (
            await connection.execute(
                text(
                    "SELECT count(*) FROM information_schema.referential_constraints rc "
                    "JOIN information_schema.table_constraints tc ON tc.constraint_name = rc.constraint_name "
                    "WHERE tc.table_name = ANY(:tables) AND rc.delete_rule = 'CASCADE'"
                ),
                {"tables": list(NEW_TABLES)},
            )
        ).scalar_one()

    assert set(columns["transcript_chunks"]) == set(columns["technical_doc_chunks"]) == set(columns["chunks"])
    assert cascade == 2
    for table in NEW_TABLES:
        indexes = await _indexes(engine, table)
        assert {f"ix_{table}_metadata_gin", f"ix_{table}_content_tsv"} <= set(indexes)
        assert f"{table}_embedding_halfvec_idx" in indexes  # el HNSW de las tablas nuevas es de la Sesión 11


async def test_deleting_a_document_cascades_to_the_new_collections(engine):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        document = Document(source_path="test/tr.json", document_type="meeting_transcript", metadata_={})
        session.add(document)
        await session.flush()
        session.add(TranscriptChunk(document_id=document.id, chunk_type="meeting_segment", content="kick-off notes"))
        session.add(TechnicalDocChunk(document_id=document.id, chunk_type="doc_section", content="payments api"))
        await session.commit()
        await session.execute(text("DELETE FROM documents WHERE id = :id"), {"id": document.id})
        await session.commit()
        remaining = [
            (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() for table in NEW_TABLES
        ]

    assert remaining == [0, 0]


async def test_migrations_are_reversible_and_alembic_check_is_clean(engine):
    config = _config()

    await asyncio.to_thread(command.check, config)
    await asyncio.to_thread(command.downgrade, config, "0003_hnsw_indexes")  # incluye la 0006 (HNSW multi-índice)
    assert not set(NEW_TABLES) & await _tables(engine)
    assert "ix_chunks_content_tsv" not in await _indexes(engine, "chunks")
    await asyncio.to_thread(command.upgrade, config, "head")
    assert set(NEW_TABLES) <= await _tables(engine)
    assert "ix_chunks_content_tsv" in await _indexes(engine, "chunks")
    await asyncio.to_thread(command.check, config)


# --- Sesión 11: HNSW en todas las colecciones (migración 0006) --------------------------------------------------

HNSW_INDEXES = {
    "chunks": "chunks_embedding_halfvec_idx",
    "transcript_chunks": "transcript_chunks_embedding_halfvec_idx",
    "technical_doc_chunks": "technical_doc_chunks_embedding_halfvec_idx",
}


async def test_every_collection_has_the_same_hnsw_halfvec_index(engine):
    for table, name in HNSW_INDEXES.items():
        definition = (await _indexes(engine, table))[name].lower()

        assert "using hnsw" in definition
        assert "(embedding)::halfvec(1536)" in definition and "halfvec_cosine_ops" in definition
        assert "m='16'" in definition.replace(" ", "") and "ef_construction='128'" in definition.replace(" ", "")


async def test_the_vector_query_uses_the_hnsw_index_on_the_new_collections(engine):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        document = Document(source_path="test/hnsw.json", document_type="meeting_transcript", metadata_={})
        session.add(document)
        await session.flush()
        for index in range(30):
            vector = [0.0] * 1536
            vector[index] = 1.0
            session.add(
                TranscriptChunk(document_id=document.id, chunk_type="meeting_segment", content=f"n{index}", embedding=vector)
            )
            session.add(
                TechnicalDocChunk(document_id=document.id, chunk_type="doc_section", content=f"d{index}", embedding=vector)
            )
        await session.commit()
        await session.execute(text("ANALYZE transcript_chunks, technical_doc_chunks"))
        # Con 30 filas el planificador preferiría el *scan*: se le prohíbe para comprobar que el índice ES utilizable
        # con la expresión de la consulta (`models.halfvec_embedding()`).
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        vector = "[" + ",".join(["1"] + ["0"] * 1535) + "]"
        for table, name in list(HNSW_INDEXES.items())[1:]:
            plan = " ".join(
                (
                    await session.execute(
                        text(
                            f"EXPLAIN SELECT id FROM {table} "
                            f"ORDER BY embedding::halfvec(1536) <=> CAST(:q AS halfvec(1536)) LIMIT 5"
                        ),
                        {"q": vector},
                    )
                ).scalars()
            )

            assert name in plan, plan


async def test_chunks_inserted_after_the_index_exists_are_searchable_without_reindexing(engine):
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        document = Document(source_path="test/late.json", document_type="technical_doc", metadata_={})
        session.add(document)
        await session.flush()
        late = [0.0] * 1536
        late[7] = 1.0
        session.add(TechnicalDocChunk(document_id=document.id, chunk_type="doc_section", content="late", embedding=late))
        await session.commit()
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        nearest = (
            await session.execute(
                text(
                    "SELECT content FROM technical_doc_chunks "
                    "ORDER BY embedding::halfvec(1536) <=> CAST(:q AS halfvec(1536)) LIMIT 1"
                ),
                {"q": "[" + ",".join("1" if i == 7 else "0" for i in range(1536)) + "]"},
            )
        ).scalar_one()

    assert nearest == "late"


async def test_the_hnsw_migration_is_reversible_and_alembic_check_stays_clean(engine):
    config = _config()

    await asyncio.to_thread(command.downgrade, config, "0005_multi_index_chunks")
    for table in ("transcript_chunks", "technical_doc_chunks"):
        assert HNSW_INDEXES[table] not in await _indexes(engine, table)
    assert HNSW_INDEXES["chunks"] in await _indexes(engine, "chunks")  # el de `chunks` no es de esta migración
    await asyncio.to_thread(command.upgrade, config, "head")
    for table, name in HNSW_INDEXES.items():
        assert name in await _indexes(engine, table)
    await asyncio.to_thread(command.check, config)
