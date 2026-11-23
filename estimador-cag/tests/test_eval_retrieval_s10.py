"""`scripts/eval_retrieval_s10.py`: configuraciones como datos, precision@k, informe y una pasada real por el golden set.

La pasada completa corre el golden set por el pipeline REAL contra `api-db` con los tres corpus de ejemplo ingestados
(embedder, reranker y LLM falsos): comprueba la mecánica del script y el formato de la tabla, no la calidad de recuperación
(eso exige embeddings reales; ver el docstring del script). Se omite sin `TEST_DATABASE_URL`.
"""

import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.foundation.persistence.migrate import upgrade_to_head
from app.generation.rag.chunking.structural import JSONStructuralChunker
from app.generation.rag.retrieval.advanced_pipeline import AdvancedRetriever
from app.generation.rag.retrieval.collections import Collection
from app.generation.rag.schemas import IngestRequest, RetrievedChunk
from app.generation.rag.store.documents import DocumentStore
from tests._grounded import ScriptedGenerator
from tests._rag_fakes import FakeEmbedder

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import eval_retrieval_s10 as harness  # noqa: E402
from build_multi_index_corpus import PLANS, ingest_collection  # noqa: E402

URL = os.getenv("TEST_DATABASE_URL")
GOLDEN = json.loads(harness.GOLDEN_PATH.read_text(encoding="utf-8"))
QUERIES = GOLDEN["queries"]
BY_ID = {config.id: config for config in harness.CONFIGS}


def chunk(source_id: str | None, *, budget_id: str | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        id=1, content="x", chunk_type="x", distance=0.1, source_id=source_id, budget_id=budget_id
    )


# --- Configuraciones como datos ---------------------------------------------------------------------------------


def test_the_named_configurations_are_data_with_unique_ids():
    ids = [config.id for config in harness.CONFIGS]

    assert ids == list("ABCDEFGH") and len(set(ids)) == len(ids)
    assert all(config.label for config in harness.CONFIGS)


def test_each_configuration_toggles_exactly_the_stages_its_label_promises():
    def flags(config_id):
        stages = BY_ID[config_id].stages
        return (
            stages.search_mode,
            stages.rerank,
            stages.temporal_decay_enabled,
            stages.routing_enabled,
            stages.query_transform_enabled,
        )

    assert flags("A") == ("vector", False, False, False, False)
    assert flags("B") == ("hybrid", False, False, False, False)
    assert flags("C") == ("vector", True, False, False, False)
    assert flags("D") == ("hybrid", True, False, False, False)
    assert flags("E") == ("hybrid", True, True, False, False)
    assert flags("F") == ("hybrid", True, False, True, False)
    assert flags("G") == ("hybrid", True, False, False, True)
    assert flags("H") == ("hybrid", True, True, True, True)


def test_the_baselines_search_budgets_only_and_the_routing_rows_let_the_router_decide():
    assert [BY_ID[i].explicit for i in "ABCDEG"] == [[Collection.BUDGET]] * 6
    assert BY_ID["F"].explicit is None and BY_ID["H"].explicit is None


def test_every_configuration_uses_a_permissive_threshold_and_the_golden_k():
    assert {config.stages.distance_threshold for config in harness.CONFIGS} == {harness.NO_FLOOR_THRESHOLD}
    assert {config.stages.top_k for config in harness.CONFIGS} == {GOLDEN["k"]}


def test_selecting_configurations_by_id_and_rejecting_unknown_ones():
    assert [c.id for c in harness.select_configs(["D", "A"])] == ["D", "A"]
    assert harness.select_configs(None) == harness.CONFIGS
    with pytest.raises(SystemExit, match="Z"):
        harness.select_configs(["A", "Z"])


# --- Métrica ----------------------------------------------------------------------------------------------------


def test_a_chunk_is_relevant_when_its_source_id_is_in_the_annotated_set():
    relevant = {"BUD-1", "TR-2"}

    assert harness.precision_at_k([chunk("BUD-1"), chunk("BUD-9"), chunk("TR-2")], relevant, 3) == pytest.approx(2 / 3)
    assert harness.precision_at_k([chunk("BUD-9")], relevant, 5) == 0.0
    assert harness.precision_at_k([chunk("BUD-1")] * 5, relevant, 5) == 1.0


def test_the_metric_divides_by_k_even_when_fewer_chunks_come_back():
    assert harness.precision_at_k([chunk("BUD-1")], {"BUD-1"}, 5) == 0.2


def test_budget_id_is_the_fallback_identity_and_only_the_top_k_count():
    assert harness.precision_at_k([chunk(None, budget_id="BUD-1")], {"BUD-1"}, 1) == 1.0
    assert harness.precision_at_k([chunk("BUD-9"), chunk("BUD-1")], {"BUD-1"}, 1) == 0.0


def test_relevant_ids_fall_back_to_the_legacy_budget_field():
    assert harness.relevant_ids({"relevant_source_ids": ["A"], "relevant_budget_ids": ["B"]}) == {"A"}
    assert harness.relevant_ids({"relevant_budget_ids": ["B"]}) == {"B"}
    assert harness.relevant_ids({}) == set()


# --- Evaluación e informe (recuperador falso) ---------------------------------------------------------------


class ScriptedRetriever:
    """Devuelve siempre los mismos chunks y cuenta las búsquedas por configuración."""

    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.calls = 0

    async def search(self, query_text, *, stages, reference_date, explicit_collections=None, hard_filters=None):
        from app.generation.rag.retrieval.advanced_pipeline import AdvancedRetrievalOutcome
        from app.generation.rag.retrieval.router import RoutingDecision

        self.calls += 1
        return AdvancedRetrievalOutcome(
            chunks=self.chunks,
            routing=RoutingDecision([Collection.BUDGET], "explicit", "x"),
            technique="direct",
            subqueries=[],
            cardinality={},
            low_confidence=not self.chunks,
        )


async def test_evaluate_runs_a_warm_up_plus_the_measured_runs_for_every_query_and_config():
    retriever = ScriptedRetriever([chunk("BUD-2024-001")])
    configs = harness.select_configs(["A", "D"])

    results = await harness.evaluate(retriever, QUERIES[:2], configs, k=5, reference_date=date(2026, 1, 1), measured_runs=3)

    assert retriever.calls == 2 * 2 * (1 + 3)  # configs × consultas × (calentamiento + medidas)
    assert all(len(results[c.id].latencies_ms) == 2 * 3 for c in configs)  # el calentamiento no se mide
    assert results["A"].per_query["Q1"] == pytest.approx(0.2)  # BUD-2024-001 es relevante en Q1
    assert results["A"].per_query["Q2"] == 0.0


async def test_an_empty_result_is_flagged():
    results = await harness.evaluate(
        ScriptedRetriever([]), QUERIES[:1], harness.select_configs(["A"]), k=5, reference_date=date(2026, 1, 1), measured_runs=1
    )

    assert results["A"].empty is True and results["A"].precisions == [0.0]


async def test_the_report_has_one_row_per_configuration_and_a_per_query_breakdown():
    configs = harness.select_configs(["A", "B", "H"])
    results = await harness.evaluate(
        ScriptedRetriever([chunk("BUD-2024-001")]), QUERIES, configs, k=5, reference_date=date(2026, 1, 1), measured_runs=1
    )

    report = harness.format_report(results, configs, QUERIES, 5)

    assert "precision@5" in report and "Latencia (ms)" in report
    for config in configs:
        assert config.label in report
    summary, breakdown = report.split("### precision@5 por consulta")
    assert all(f"Q{i}" in breakdown for i in range(1, len(QUERIES) + 1))
    assert len([line for line in summary.splitlines() if line.startswith(("A ", "B ", "H "))]) == 3


# --- Pasada real por el golden set (api-db) ----------------------------------------------------------------


class OverlapReranker:
    """Cross-encoder falso: solapamiento de palabras entre consulta y documento."""

    async def score(self, query, documents):
        words = set(query.lower().split())
        return [float(len(words & set(document.lower().split()))) for document in documents]


@pytest.fixture
async def stack():
    if not URL or not URL.split("?")[0].endswith("test"):
        pytest.skip("TEST_DATABASE_URL no definida (o no termina en 'test')")
    os.environ["DATABASE_URL"] = URL
    await asyncio.to_thread(upgrade_to_head)
    engine = create_async_engine(URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE documents, chunks RESTART IDENTITY CASCADE"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    embedder = FakeEmbedder(1536)

    budgets = json.loads((ROOT / "data" / "budgets_sample.json").read_text(encoding="utf-8"))
    async with sessions() as session:
        store = DocumentStore(session, JSONStructuralChunker(), embedder, ef_search=40)
        for budget in budgets:
            await store.ingest(
                IngestRequest(
                    source_path=f"data/budgets_sample.json#{budget['budget_id']}",
                    document_type="historical_budget",
                    content=budget,
                )
            )
    for plan in PLANS:
        items = json.loads((ROOT / plan.source_file).read_text(encoding="utf-8"))
        await ingest_collection(plan, items, session_factory=sessions, embedder=embedder)

    yield sessions, embedder
    await engine.dispose()
    os.environ.pop("DATABASE_URL", None)


async def test_the_full_golden_set_runs_through_every_named_configuration_on_the_real_pipeline(stack):
    sessions, embedder = stack
    retriever = AdvancedRetriever(
        sessions,
        embedder,
        generate=ScriptedGenerator(),  # sin salidas previstas: clasificador y transformador fallan y degradan
        reranker=OverlapReranker(),
        ef_search=40,
    )

    results = await harness.evaluate(
        retriever, QUERIES, harness.CONFIGS, k=GOLDEN["k"], reference_date=date(2026, 6, 1), measured_runs=1
    )
    report = harness.format_report(results, harness.CONFIGS, QUERIES, GOLDEN["k"])

    assert all(len(result.precisions) == len(QUERIES) for result in results.values())
    assert not any(result.empty for result in results.values())  # los tres corpus están ingestados
    assert all(0.0 <= p <= 1.0 for result in results.values() for p in result.precisions)
    assert all(config.label in report for config in harness.CONFIGS)
    # Las consultas que cruzan colecciones solo pueden ganar puntos si se busca fuera de presupuestos.
    assert results["F"].per_query["Q8"] >= results["A"].per_query["Q8"] == 0.0
