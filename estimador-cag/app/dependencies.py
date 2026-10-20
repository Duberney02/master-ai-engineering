"""Dependencias compartidas de la ingesta: catálogo, cargador, registro de parsers y seudonimizador."""

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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
