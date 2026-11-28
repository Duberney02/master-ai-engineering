"""Composition root: todas las fábricas de dependencias del servicio viven aquí.

Está por encima de las capas a propósito: puede importar de cualquiera porque su trabajo es cablearlas.
Solo lo importan `app/api/`, `app/main.py`, los scripts y las pruebas; ninguna capa lo importa (ver ARCHITECTURE.md).
Las pruebas sustituyen cualquiera de estas fábricas con `app.dependency_overrides`.
"""

from collections.abc import Callable
from functools import lru_cache

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.config import get_settings
from app.domain.acb import ActorCriticBoss
from app.domain.history import EstimationHistory
from app.domain.pipeline import EstimationPipeline
from app.domain.session_estimation import SessionEstimationService
from app.foundation.llm.runtime_config import RuntimeModelConfig, RuntimeRetrievalConfig, effective_settings
from app.foundation.llm.service import generate_from_messages
from app.foundation.persistence.database import SessionLocal, get_session
from app.generation.agentic.critic import CriticService
from app.generation.conversation.sessions import SessionStore
from app.generation.rag.chunking.base import Chunker
from app.generation.rag.chunking.registry import build_chunkers
from app.generation.rag.chunking.structural import JSONStructuralChunker
from app.generation.rag.corpus_expansion import CorpusExpansionService
from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.estimator import GroundedEstimator
from app.generation.rag.idempotency import IdempotencyStore
from app.generation.rag.retrieval.advanced_pipeline import AdvancedRetriever
from app.generation.rag.retrieval.reranker import CrossEncoderReranker, Reranker
from app.generation.rag.retriever import ChunkRetriever
from app.generation.rag.store.documents import DocumentStore
from app.generation.rag.task_hours import TaskHoursEstimator
from app.ingestion.catalog import DataCatalog, load_catalog
from app.ingestion.loaders.filesystem import FileSystemLoader
from app.ingestion.parsers.registry import ParserRegistry, default_registry


@lru_cache
def get_catalog() -> DataCatalog:
    """Carga y cachea el catálogo de fuentes.

    Se lee una vez por proceso: releerlo invalidaría las decisiones en las que se basa el pipeline en
    marcha, así que una nueva versión del catálogo exige reiniciar el proceso.
    """
    return load_catalog(get_settings().catalog_path)


@lru_cache
def get_filesystem_loader() -> FileSystemLoader:
    return FileSystemLoader(data_root=get_settings().ingestion_data_root)


@lru_cache
def get_parser_registry() -> ParserRegistry:
    """Registro con los parsers de la referencia (JSON y TXT); no hay parsers XLSX, DOCX ni PDF de ingesta."""
    return default_registry()


def build_pseudonymizer(session: AsyncSession):
    """Construye un `ConsistentPseudonymizer` respaldado por PostgreSQL.

    No es un singleton: el store envuelve una sesión, así que cada llamante (scripts, tareas en segundo
    plano, pruebas) aporta la suya. El analizador (singleton de `build_analyzer`) y la sal vienen de `Settings`.
    """
    from app.ingestion.pii import ConsistentPseudonymizer, PostgresMappingStore, build_analyzer

    settings = get_settings()
    return ConsistentPseudonymizer(
        analyzer=build_analyzer(),
        mapping_store=PostgresMappingStore(session),
        salt=settings.pseudonym_hash_salt,
        faker_locale=settings.pseudonym_faker_locale,
        language="es",
    )


def get_pipeline() -> EstimationPipeline:
    """Pipeline de estimación (caché, LLM, validación)."""
    return EstimationPipeline(get_settings())


def get_session_estimation_service() -> SessionEstimationService:
    """Servicio de estimación conversacional (memoria, audiencia, metadatos)."""
    return SessionEstimationService(get_settings())


def get_actor_critic_boss(
    service: SessionEstimationService = Depends(get_session_estimation_service),
) -> ActorCriticBoss:
    """Orquestador Actor–Critic–Boss sobre el servicio conversacional."""
    return ActorCriticBoss(service, CriticService(service.settings), service.settings.boss_max_iterations)


_history_instances: dict[str | None, EstimationHistory] = {}


def get_history() -> EstimationHistory:
    """Una instancia (y su pool) por URL de base de datos."""
    settings = get_settings()
    if settings.database_url not in _history_instances:
        _history_instances[settings.database_url] = EstimationHistory(settings)
    return _history_instances[settings.database_url]


async def close_history() -> None:
    """Libera los pools al apagar la aplicación."""
    instances = list(_history_instances.values())
    _history_instances.clear()
    for history in instances:
        await history.close()


_session_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    """Almacén único de sesiones del proceso; las pruebas lo sustituyen o lo reinician."""
    global _session_store
    if _session_store is None:
        settings = config.get_settings()
        _session_store = SessionStore(
            max_sessions=settings.session_max_count,
            ttl_seconds=settings.session_ttl_seconds,
            max_turns=settings.session_max_turns,
        )
    return _session_store


def reset_session_store() -> None:
    global _session_store
    _session_store = None


@lru_cache
def get_chunker() -> JSONStructuralChunker:
    return JSONStructuralChunker()


@lru_cache
def get_embedder() -> OpenAIEmbedder:
    return OpenAIEmbedder()


def get_document_store(
    session: AsyncSession = Depends(get_session),
    chunker: JSONStructuralChunker = Depends(get_chunker),
    embedder: OpenAIEmbedder = Depends(get_embedder),
) -> DocumentStore:
    """Almacén vectorial de la solicitud: la sesión async es la de la solicitud (una transacción por ingesta)."""
    return DocumentStore(session, chunker, embedder, ef_search=get_settings().hnsw_ef_search)


async def get_chunker_builder() -> Callable[[list[str]], list[Chunker]]:
    """Construye los chunkers pedidos por nombre; no hace llamadas a ninguna API (ver `chunking/registry.py`).

    Resuelve los modelos de los chunkers con LLM en el momento de la solicitud (overrides en runtime)."""
    settings = await effective_settings(get_settings())
    embedder = get_embedder()
    return lambda names: build_chunkers(names, settings, embedder)


def get_rag_embedder() -> OpenAIEmbedder | None:
    """Embedder de las consultas RAG (Sesión 9); `None` sin `OPENAI_API_KEY` (la API responde 500)."""
    return get_embedder() if get_settings().openai_api_key else None


def get_rag_session_factory() -> Callable[[], AsyncSession]:
    """Fábrica de sesiones de la recuperación RAG; sin `DATABASE_URL` la búsqueda falla al abrir la sesión (502)."""
    return SessionLocal


@lru_cache
def _cross_encoder(model_name: str) -> CrossEncoderReranker:
    """Un único cross-encoder por modelo y proceso: el modelo se carga una vez, en el primer reranking."""
    return CrossEncoderReranker(model_name)


def get_reranker() -> Reranker:
    """Reranker de la recuperación (Sesión 10). Crearlo es barato: los pesos se cargan en el primer uso, y con el
    reranking apagado nunca. Las pruebas lo sustituyen con `app.dependency_overrides` y no descargan pesos."""
    return _cross_encoder(get_settings().reranker_model)


def get_chunk_retriever(
    session_factory: Callable[[], AsyncSession] = Depends(get_rag_session_factory),
    embedder: OpenAIEmbedder | None = Depends(get_rag_embedder),
    reranker: Reranker = Depends(get_reranker),
) -> ChunkRetriever:
    settings = get_settings()
    return ChunkRetriever(
        session_factory,
        embedder,
        ef_search=settings.hnsw_ef_search,
        reranker=reranker,
        recall_top_k=settings.retrieval_recall_top_k,
        rerank_top_n=settings.rerank_top_n,
        rrf_k=settings.rrf_k,
    )


def get_advanced_retriever(
    session_factory: Callable[[], AsyncSession] = Depends(get_rag_session_factory),
    embedder: OpenAIEmbedder | None = Depends(get_rag_embedder),
    reranker: Reranker = Depends(get_reranker),
) -> AdvancedRetriever:
    """Recuperador avanzado multi-índice (Sesión 10): router, transformación de consulta y reranking inyectados."""
    return AdvancedRetriever(
        session_factory,
        embedder,
        generate=generate_from_messages,
        reranker=reranker,
        ef_search=get_settings().hnsw_ef_search,
    )


_idempotency_store: IdempotencyStore | None = None


def get_idempotency_store() -> IdempotencyStore:
    """Almacén único del proceso: Redis (cliente asíncrono) con `REDIS_URL`; si no, memoria con caducidad."""
    global _idempotency_store
    if _idempotency_store is None:
        settings = config.get_settings()
        redis_factory = None
        if settings.redis_url:

            def redis_factory() -> Redis:
                return Redis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    socket_timeout=settings.cache_timeout,
                    socket_connect_timeout=settings.cache_timeout,
                )

        _idempotency_store = IdempotencyStore(ttl=settings.idempotency_ttl, redis_factory=redis_factory)
    return _idempotency_store


def reset_idempotency_store() -> None:
    global _idempotency_store
    _idempotency_store = None


def get_runtime_retrieval_config() -> RuntimeRetrievalConfig:
    """Almacén de overrides de recuperación en runtime (Redis, hash aparte); sin estado, como el de modelos."""
    return RuntimeRetrievalConfig(get_settings())


def get_grounded_estimator(
    retriever: ChunkRetriever = Depends(get_chunk_retriever),
    idempotency: IdempotencyStore = Depends(get_idempotency_store),
    runtime_retrieval: RuntimeRetrievalConfig = Depends(get_runtime_retrieval_config),
) -> GroundedEstimator:
    """Orquestador RAG de la Sesión 9 (pipeline completo y etapas); recupera con los parámetros de runtime."""
    return GroundedEstimator(get_settings(), retriever, idempotency, runtime_retrieval=runtime_retrieval)


def get_task_hours_estimator(
    retriever: ChunkRetriever = Depends(get_chunk_retriever),
    runtime_retrieval: RuntimeRetrievalConfig = Depends(get_runtime_retrieval_config),
) -> TaskHoursEstimator:
    """Horas por tarea (Sesión 10): recuperador sobre `historical_task` y parámetros de runtime."""
    return TaskHoursEstimator(
        get_settings(), retriever, runtime_retrieval=runtime_retrieval, generate=generate_from_messages
    )


def get_corpus_expansion_service(
    session_factory: Callable[[], AsyncSession] = Depends(get_rag_session_factory),
    chunker: JSONStructuralChunker = Depends(get_chunker),
    embedder: OpenAIEmbedder | None = Depends(get_rag_embedder),
) -> CorpusExpansionService:
    """Expansión incremental del corpus (Sesión 11): sesiones propias, porque la tarea sobrevive a la solicitud."""
    return CorpusExpansionService(session_factory, chunker, embedder, ef_search=get_settings().hnsw_ef_search)


def get_runtime_config() -> RuntimeModelConfig:
    """Almacén de overrides de modelos en runtime (Redis); no guarda estado, cada operación abre su conexión."""
    return RuntimeModelConfig(get_settings())
