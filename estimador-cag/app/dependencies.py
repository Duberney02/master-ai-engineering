"""Composition root: todas las fábricas de dependencias del servicio viven aquí.

Está por encima de las capas a propósito: puede importar de cualquiera porque su trabajo es cablearlas.
Solo lo importan `app/api/`, `app/main.py`, los scripts y las pruebas; ninguna capa lo importa (ver ARCHITECTURE.md).
Las pruebas sustituyen cualquiera de estas fábricas con `app.dependency_overrides`.
"""

from functools import lru_cache

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.config import get_settings
from app.domain.acb import ActorCriticBoss
from app.domain.history import EstimationHistory
from app.domain.pipeline import EstimationPipeline
from app.domain.session_estimation import SessionEstimationService
from app.generation.agentic.critic import CriticService
from app.generation.conversation.sessions import SessionStore
from app.generation.rag.chunking.structural import JSONStructuralChunker
from app.generation.rag.embedding.embedder import OpenAIEmbedder
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
