"""Dobles de prueba del RAG de estimación fundamentada (Sesión 9): generador guionizado, retriever falso y clientes."""

import json

from fastapi.testclient import TestClient

from app.config import get_settings
from app.dependencies import get_grounded_estimator
from app.foundation.llm.wrapper import Completion
from app.generation.rag.errors import EmbedderUnavailableError, RetrievalError
from app.generation.rag.estimator import GroundedEstimator
from app.generation.rag.idempotency import IdempotencyStore
from app.generation.rag.schemas import RetrievalResult, RetrievedChunk
from app.main import app
from tests._fakes import openai_settings

RETRIEVAL_KEY = "retrieval-key-123"
ESTIMATE_KEY = "estimate-key-456"
SECRET = "sk-provider-secret-detail"

TRANSCRIPT = (
    "Cliente: queremos una plataforma de pagos B2B para bancos alemanes, con onboarding KYC, integración con SAP y "
    "cumplimiento PSD2. Hablamos también del tiempo y del fútbol, pero lo importante es el marketplace de pagos."
)

BRIEF = {
    "function": "B2B payments marketplace with KYC onboarding",
    "technologies": ["stripe", "sap"],
    "sector": "finance",
    "scale": "large",
    "country": "DE",
    "regulations": ["PSD2"],
    "constraints": [],
}


def make_chunk(chunk_id: int, distance: float = 0.2, content: str | None = None, **extra) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        content=content or f"[Project: payments] Component {chunk_id}: KYC onboarding. Estimated hours: 40",
        sector=extra.pop("sector", "finance"),
        project_year=extra.pop("project_year", 2024),
        chunk_type=extra.pop("chunk_type", "budget_component"),
        distance=distance,
        budget_id=extra.pop("budget_id", f"BUD-{chunk_id}"),
        document_id=extra.pop("document_id", chunk_id + 100),
        **extra,
    )


def line_task(name: str = "Onboarding KYC", days: float | None = 12, chunk_ids=(1,), **overrides) -> dict:
    """Tarea con atribución por línea (Sesión 11): fundamentada si cita chunks; si no, `grounded=false` sin horas."""
    grounded = bool(chunk_ids)
    task = {
        "name": name,
        "description": None,
        "engineer_days": days if grounded else None,
        "grounded": grounded,
        "sources": [
            {"chunk_id": cid, "document_id": cid + 100, "evidence": "KYC onboarding. Estimated hours: 40"}
            for cid in chunk_ids
        ],
    }
    task.update(overrides)
    return task


def estimate_payload(source_ids=(1,), confidence: str = "high", **overrides) -> dict:
    payload = {
        "total_engineer_days": 12,
        "duration_weeks": 4,
        "modules": [
            {
                "name": "Pagos",
                "description": "Marketplace de pagos",
                "tasks": [line_task(chunk_ids=tuple(source_ids[:1]) or (1,))],
            }
        ],
        "sources": [{"source_id": sid, "relevance": "primary", "used_for": "horas de KYC"} for sid in source_ids],
        "assumptions": [{"description": "Integración SAP estándar", "impact": "medium", "rationale": "sin precedente"}],
        "confidence": confidence,
        "reasoning": "Derivado de las fuentes recuperadas.",
        "insufficient_context_explanation": None,
    }
    payload.update(overrides)
    return payload


def incoherent_insufficient() -> dict:
    return estimate_payload(source_ids=(), confidence="insufficient", insufficient_context_explanation="Falta contexto")


class ScriptedGenerator:
    """Mismo contrato que `generate_from_messages`: cada llamada consume un resultado (dict/str o excepción)."""

    def __init__(self, *outcomes) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []

    async def __call__(self, messages, accept=None, **options) -> Completion:
        self.calls.append({"messages": messages, **options})
        if not self._outcomes:
            raise AssertionError("llamada al LLM no prevista")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        text = outcome if isinstance(outcome, str) else json.dumps(outcome)
        return Completion(text=text, model="gpt-4o-mini", provider="openai")

    def user_messages(self) -> list[str]:
        return [call["messages"][-1]["content"] for call in self.calls]


class FakeRetriever:
    """Sustituye a `ChunkRetriever`: devuelve un resultado fijo (o falla) y registra las búsquedas."""

    def __init__(self, chunks: list[RetrievedChunk] | None = None, error: Exception | None = None) -> None:
        self.chunks = chunks if chunks is not None else [make_chunk(1), make_chunk(2, 0.3)]
        self.error = error
        self.calls: list[dict] = []

    async def search(
        self, query_text, *, top_k, distance_threshold, filters, search_mode="vector", rerank=False, rerank_top_n=None
    ) -> RetrievalResult:
        self.calls.append(
            {
                "query_text": query_text,
                "top_k": top_k,
                "distance_threshold": distance_threshold,
                "filters": filters,
                "search_mode": search_mode,
                "rerank": rerank,
            }
        )
        if self.error:
            raise self.error
        return RetrievalResult(chunks=self.chunks, low_confidence=not self.chunks, candidates_evaluated=25)


def failing_retriever(kind: str = "provider") -> FakeRetriever:
    if kind == "embedder":
        return FakeRetriever(error=EmbedderUnavailableError("no key"))
    return FakeRetriever(error=RetrievalError(SECRET))


def build_estimator(generator=None, retriever=None, store=None, runtime_retrieval=None, **settings) -> GroundedEstimator:
    return GroundedEstimator(
        openai_settings(**settings),
        retriever or FakeRetriever(),
        store or IdempotencyStore(ttl=60),
        generate=generator or ScriptedGenerator(),
        runtime_retrieval=runtime_retrieval,
    )


def configure_keys(monkeypatch, retrieval: str | None = RETRIEVAL_KEY, estimate: str | None = ESTIMATE_KEY) -> None:
    for name, value in (("RETRIEVAL_API_KEY", retrieval), ("ESTIMATE_API_KEY", estimate)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    get_settings.cache_clear()


def api_client(monkeypatch, estimator: GroundedEstimator | None = None, **keys) -> TestClient:
    """`TestClient` con claves configuradas y el orquestador sustituido (las pruebas limpian los overrides)."""
    configure_keys(monkeypatch, **keys)
    holder = {"estimator": estimator or build_estimator()}
    app.dependency_overrides[get_grounded_estimator] = lambda: holder["estimator"]
    client = TestClient(app)
    client.holder = holder
    return client
