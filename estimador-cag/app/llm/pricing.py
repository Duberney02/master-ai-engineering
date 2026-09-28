"""Fuente única de precios para estimar costes (USD por millón de tokens).

Los valores son precios públicos de lista de cada proveedor y pueden quedar
desactualizados: se amplían o sustituyen sin tocar código con la variable
`LLM_PRICING_OVERRIDES`. Un modelo sin precio conocido produce coste `None`
(desconocido), nunca 0.

Coincidencia: exacta por `proveedor/modelo` o por instantánea fechada del mismo
modelo (`gpt-4o-mini-2024-07-18`, `claude-haiku-4-5-20251001`). `gpt-4o` NO
coincide con `gpt-4o-mini`.
"""

import re
from dataclasses import dataclass

PRICING_SOURCE = (
    "Tarifas públicas de lista de OpenAI y Anthropic (USD por millón de tokens, sin "
    "descuentos por batch ni por caché del proveedor); ampliables con LLM_PRICING_OVERRIDES"
)

# proveedor/modelo -> (entrada, salida) en USD por millón de tokens.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4.1": (2.00, 8.00),
    "openai/gpt-4.1-mini": (0.40, 1.60),
    "anthropic/claude-haiku-4-5": (1.00, 5.00),
    "anthropic/claude-sonnet-4-5": (3.00, 15.00),
}

_SNAPSHOT_SUFFIX = re.compile(r"^-(\d{4}-\d{2}-\d{2}|\d{8})$")


@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    output_per_mtok: float


class PricingTable:
    def __init__(self, overrides: dict[str, dict[str, float]] | None = None):
        prices = {k: Price(i, o) for k, (i, o) in DEFAULT_PRICES.items()}
        for key, value in (overrides or {}).items():
            prices[key] = Price(value["input"], value["output"])
        self._prices = prices
        self.source = PRICING_SOURCE

    def price_for(self, provider: str, model: str | None) -> Price | None:
        if not model:
            return None
        key = f"{provider}/{model}"
        if key in self._prices:
            return self._prices[key]
        for known, price in self._prices.items():
            if key.startswith(known) and _SNAPSHOT_SUFFIX.match(key[len(known):]):
                return price
        return None

    def cost(
        self,
        provider: str,
        model: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> float | None:
        """Coste estimado en USD; None si faltan tokens o tarifa."""
        price = self.price_for(provider, model)
        if price is None or input_tokens is None or output_tokens is None:
            return None
        usd = (input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok) / 1e6
        return round(usd, 8)
