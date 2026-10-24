"""Precios de referencia de las estrategias que llaman a un LLM o a embeddings durante el chunking.

VARÍAN CON EL TIEMPO: son estimaciones para comparar estrategias, no la factura. Un precio configurado en
`Settings.model_prices` tiene prioridad sobre esta tabla; un modelo sin precio conocido cuesta 0 y se registra.
"""

import structlog

from app.config import Settings

logger = structlog.get_logger(__name__)

# USD por millón de tokens: (entrada, salida).
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-5": (3.00, 15.00),
}

# Con prompt caching de Anthropic, escribir en caché cuesta 1,25× la entrada y leer de ella 0,10×.
CACHE_WRITE_FACTOR = 1.25
CACHE_READ_FACTOR = 0.10

EMBEDDING_PRICE_PER_MILLION_USD = 0.02


def model_prices(settings: Settings, model: str) -> tuple[float, float] | None:
    configured = settings.model_prices.get(model)
    if configured is not None:
        return configured.input, configured.output
    return DEFAULT_PRICES.get(model)


def llm_cost_usd(
    settings: Settings,
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    prices = model_prices(settings, model)
    if prices is None:
        logger.warning("chunking_price_unknown", model=model)
        return 0.0
    price_in, price_out = prices
    return (
        input_tokens * price_in
        + output_tokens * price_out
        + cache_write_tokens * price_in * CACHE_WRITE_FACTOR
        + cache_read_tokens * price_in * CACHE_READ_FACTOR
    ) / 1_000_000


def embedding_cost_usd(total_tokens: int) -> float:
    return total_tokens / 1_000_000 * EMBEDDING_PRICE_PER_MILLION_USD
