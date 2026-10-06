"""Caché semántica de estimaciones sobre Redis Stack (RediSearch) con `redisvl`.

Una entrada solo se reutiliza si coinciden versión de prompt, tipo de proyecto, nivel de
detalle y formato (filtros de tipo tag) y la similitud coseno alcanza el umbral. Cualquier
fallo (Redis, índice, embeddings) se registra y se trata como un fallo de caché.
"""

import asyncio
import json
import re
from collections.abc import Callable
from functools import lru_cache

import structlog

from app.config import Settings
from app.schemas.project_estimation import EstimationRequest
from app.services.cache import CachedEstimation
from app.services.embeddings import Embedder, OpenAIEmbedder, embeddings_available

logger = structlog.get_logger(__name__)

ATTRIBUTES = ("prompt_version", "project_type", "detail_level", "output_format")


def semantic_text(request: EstimationRequest) -> str:
    """Texto que se embebe: la descripción más las referencias que calibran la estimación."""
    parts = [request.description]
    for project in request.reference_projects or []:
        parts.append(f"{project.name} ({project.actual_hours:g} h): {project.description}")
    return "\n".join(parts)


def attributes(request: EstimationRequest, prompt_version: str) -> dict[str, str]:
    return {
        "prompt_version": prompt_version,
        "project_type": request.project_type.value,
        "detail_level": request.detail_level.value,
        "output_format": request.output_format.value,
    }


def index_name(settings: Settings) -> str:
    """El modelo y las dimensiones forman parte del nombre: vectores incompatibles no se mezclan."""
    model = re.sub(r"[^a-z0-9]+", "_", settings.embedding_model.lower()).strip("_")
    return f"estimation_semantic_{model}_{settings.embedding_dimensions}"


@lru_cache
def _build_redisvl_cache(url: str, name: str, dimensions: int, ttl: int, timeout: float):
    # Import local: redisvl arranca varios módulos y solo hace falta con la caché activa.
    from redisvl.extensions.cache.llm import SemanticCache
    from redisvl.utils.vectorize import CustomTextVectorizer

    # Los vectores se calculan fuera y se pasan siempre explícitos; este vectorizador solo
    # fija las dimensiones del índice y no debe usarse.
    vectorizer = CustomTextVectorizer(embed=lambda _text: [0.0] * dimensions)
    return SemanticCache(
        name=name,
        ttl=ttl,
        vectorizer=vectorizer,
        redis_url=url,
        filterable_fields=[{"name": attribute, "type": "tag"} for attribute in ATTRIBUTES],
        connection_kwargs={"socket_timeout": timeout, "socket_connect_timeout": timeout},
    )


def _filter_expression(values: dict[str, str]):
    from redisvl.query.filter import Tag

    expression = None
    for attribute in ATTRIBUTES:
        condition = Tag(attribute) == values[attribute]
        expression = condition if expression is None else expression & condition
    return expression


class SemanticCache:
    def __init__(
        self,
        settings: Settings,
        embedder: Embedder | None = None,
        cache_factory: Callable[..., object] = _build_redisvl_cache,
    ):
        self.settings = settings
        self.embedder = embedder or OpenAIEmbedder(settings)
        self._cache_factory = cache_factory
        self._vectors: dict[str, list[float]] = {}

    async def _embed(self, text: str) -> list[float]:
        # Una misma solicitud embebe una vez aunque haga consulta y almacenamiento.
        if text not in self._vectors:
            self._vectors[text] = await self.embedder.embed(text)
        return self._vectors[text]

    def _too_long(self, request: EstimationRequest) -> bool:
        if len(semantic_text(request)) <= self.settings.semantic_cache_max_chars:
            return False
        logger.info("semantic_cache_skipped", reason="text_too_long")
        return True

    @property
    def enabled(self) -> bool:
        return (
            self.settings.semantic_cache_mode != "off"
            and bool(self.settings.redis_url)
            and embeddings_available(self.settings)
        )

    async def _cache(self):
        s = self.settings
        # La construcción de redisvl abre una conexión síncrona: fuera del event loop.
        return await asyncio.to_thread(
            self._cache_factory, s.redis_url, index_name(s), s.embedding_dimensions,
            s.semantic_cache_ttl, s.cache_timeout,
        )

    async def lookup(self, request: EstimationRequest, prompt_version: str) -> CachedEstimation | None:
        """Devuelve la entrada más parecida por encima del umbral (nunca en `log_only`)."""
        if not self.enabled or self._too_long(request):
            return None
        values = attributes(request, prompt_version)
        try:
            vector = await self._embed(semantic_text(request))
            cache = await self._cache()
            hits = await cache.acheck(
                vector=vector, num_results=1, filter_expression=_filter_expression(values),
                distance_threshold=1 - self.settings.semantic_cache_threshold,
            )
        except Exception as exc:
            logger.warning("semantic_cache_unavailable", operation="lookup", error_type=type(exc).__name__)
            return None
        if not hits:
            return None
        entry = CachedEstimation.parse(_loads(hits[0].get("response")))
        if entry is None:
            return None
        similarity = round(1 - float(hits[0].get("vector_distance", 1)), 4)
        if self.settings.semantic_cache_mode == "log_only":
            logger.info("semantic_cache_would_hit", similarity=similarity, **values)
            return None
        logger.info("semantic_cache_hit", similarity=similarity, **values)
        return entry

    async def store(self, request: EstimationRequest, prompt_version: str, entry: CachedEstimation) -> None:
        if not self.enabled or self._too_long(request):
            return
        values = attributes(request, prompt_version)
        try:
            vector = await self._embed(semantic_text(request))
            cache = await self._cache()
            await cache.astore(
                prompt=semantic_text(request), response=entry.model_dump_json(),
                vector=vector, filters=values,
            )
        except Exception as exc:
            logger.warning("semantic_cache_unavailable", operation="store", error_type=type(exc).__name__)


def _loads(raw: object):
    try:
        return json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
