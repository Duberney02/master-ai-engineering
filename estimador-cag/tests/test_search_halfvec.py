"""`/search` alineado con el índice HNSW halfvec: expresión del ORDER BY y `SET LOCAL hnsw.ef_search` (sin base real)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.generation.rag.store.documents import DocumentStore, search_statement
from tests._fakes import openai_settings
from tests._rag_fakes import FakeEmbedder

DIMENSIONS = 1536


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_search_orders_by_the_exact_index_expression():
    sql = _sql(search_statement([0.1] * DIMENSIONS, 5))

    assert "CAST(chunks.embedding AS HALFVEC(1536)) <=>" in sql
    assert "ORDER BY distance" in sql and "LIMIT" in sql
    assert "chunks.embedding <=>" not in sql  # la expresión sin castear NO usa el índice halfvec


def _session(rows=()):
    result = MagicMock()
    result.all.return_value = list(rows)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


async def test_search_sets_ef_search_locally_before_the_query():
    session = _session()
    store = DocumentStore(session, chunker=MagicMock(), embedder=FakeEmbedder(DIMENSIONS), ef_search=80)

    response = await store.search("oauth", 3)

    first, second = (call.args[0] for call in session.execute.await_args_list)
    assert str(first) == "SET LOCAL hnsw.ef_search = 80"
    assert "HALFVEC" in _sql(second)
    assert response.results == [] and response.k == 3


async def test_search_falls_back_to_the_setting(mocker):
    mocker.patch("app.generation.rag.store.documents.get_settings", return_value=openai_settings(hnsw_ef_search=120))
    session = _session()

    await DocumentStore(session, chunker=MagicMock(), embedder=FakeEmbedder(DIMENSIONS)).search("oauth", 1)

    assert str(session.execute.await_args_list[0].args[0]) == "SET LOCAL hnsw.ef_search = 120"


def test_hnsw_ef_search_setting_is_validated():
    assert openai_settings().hnsw_ef_search == 40
    assert openai_settings(hnsw_ef_search=1000).hnsw_ef_search == 1000
    for invalid in (0, 1001, -5):
        with pytest.raises(ValidationError):
            openai_settings(hnsw_ef_search=invalid)
