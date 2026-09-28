"""Construcción, reutilización y cierre de recursos por proceso.

`build_resources` crea una sola vez (en el `lifespan` de FastAPI) los adaptadores de
proveedores, el cliente Redis, la caché, el wrapper LLM y el servicio de estimación.
Los endpoints los obtienen con `Depends(...)` desde `app.state`, de modo que las
pruebas pueden sustituirlos pasando otros recursos a `create_app` o con
`app.dependency_overrides`, sin parchear fábricas globales.
"""

import logging
from dataclasses import dataclass
from typing import Any

import redis.asyncio as redis_asyncio
from fastapi import Request

from app.cache.result_cache import RedisLike, ResultCache
from app.config import Settings
from app.llm.client import LLMClient
from app.llm.pricing import PricingTable
from app.llm.providers.anthropic_provider import AnthropicAdapter
from app.llm.providers.base import ProviderAdapter
from app.llm.providers.openai_provider import OpenAIAdapter
from app.llm.routing import ModelPolicy
from app.services.estimation_service import EstimationService

logger = logging.getLogger(__name__)


@dataclass
class AppResources:
    settings: Settings
    cache: ResultCache
    llm: LLMClient
    service: EstimationService

    async def aclose(self) -> None:
        await self.llm.aclose()
        await self.cache.aclose()


def build_providers(settings: Settings) -> dict[str, ProviderAdapter]:
    """Un adaptador (y un cliente HTTP) por proveedor con credenciales configuradas."""
    providers: dict[str, ProviderAdapter] = {}
    key = settings.api_key("openai")
    if key:
        providers["openai"] = OpenAIAdapter.from_api_key(key, settings.llm_timeout_seconds)
    key = settings.api_key("anthropic")
    if key:
        providers["anthropic"] = AnthropicAdapter.from_api_key(key, settings.llm_timeout_seconds)
    return providers


def build_redis(settings: Settings) -> RedisLike | None:
    if not settings.cache_enabled:
        return None
    # Sin reintentos internos y con timeouts cortos: si Redis no responde se sigue sin caché.
    return redis_asyncio.Redis.from_url(
        settings.redis_url,
        socket_timeout=settings.redis_timeout_seconds,
        socket_connect_timeout=settings.redis_timeout_seconds,
        retry_on_timeout=False,
        health_check_interval=30,
    )


def build_policy(settings: Settings) -> ModelPolicy:
    return ModelPolicy(
        primary=settings.primary_model(),
        fallback=settings.fallback_model(),
        allowed=settings.allowed_model_refs(),
        available_providers=settings.configured_providers(),
    )


def build_resources(
    settings: Settings,
    *,
    providers: dict[str, ProviderAdapter] | None = None,
    redis: RedisLike | None | Any = ...,
    sleep=None,
) -> AppResources:
    providers = providers if providers is not None else build_providers(settings)
    redis_client = build_redis(settings) if redis is ... else redis
    cache = ResultCache(
        redis_client,
        enabled=settings.cache_enabled,
        prefix=settings.cache_prefix,
        ttl_seconds=settings.cache_ttl_seconds,
        op_timeout=settings.redis_timeout_seconds,
        retry_after=settings.cache_retry_after_seconds,
    )
    llm_kwargs: dict[str, Any] = {}
    if sleep is not None:
        llm_kwargs["sleep"] = sleep
    llm = LLMClient(
        providers,
        cache,
        PricingTable(settings.pricing_overrides()),
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        backoff=settings.llm_retry_backoff_seconds,
        inflight_wait=settings.llm_inflight_wait_seconds,
        **llm_kwargs,
    )
    service = EstimationService(llm=llm, policy=build_policy(settings))
    return AppResources(settings=settings, cache=cache, llm=llm, service=service)


# --- Providers para Depends ---------------------------------------------------------


def get_resources(request: Request) -> AppResources:
    return request.app.state.resources


def get_estimation_service(request: Request) -> EstimationService:
    return get_resources(request).service


def get_app_settings(request: Request) -> Settings:
    return get_resources(request).settings


def get_request_id(request: Request) -> str | None:
    return request.scope.get("state", {}).get("request_id")
