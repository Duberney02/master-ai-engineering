"""Costes, tokens y estado de caché en una y dos fases (servicio real + dobles)."""

import pytest

from app.llm.pricing import PricingTable
from app.services.estimation_service import GenerationOptions
from app.services.reporting import build_metadata, cache_summary
from tests._fakes import FakeProvider, FakeRedis, completion, make_resources, openai_settings

REQS = "### Requisitos funcionales\n- Pagos"
T = "Transcripción de una reunión con suficiente longitud para el test"
MINI_IN, MINI_OUT = 0.15, 0.60  # USD / millón de tokens (gpt-4o-mini)


def _cost(i, o):
    return (i * MINI_IN + o * MINI_OUT) / 1e6


def test_pricing_matches_exact_and_dated_snapshots_only():
    table = PricingTable()
    assert table.price_for("openai", "gpt-4o-mini-2024-07-18") == table.price_for("openai", "gpt-4o-mini")
    assert table.price_for("openai", "gpt-4o-mini") != table.price_for("openai", "gpt-4o")
    assert table.price_for("anthropic", "claude-haiku-4-5-20251001") is not None
    assert table.price_for("openai", "gpt-4o-mini-custom") is None
    assert table.cost("openai", "modelo-desconocido", 10, 10) is None  # desconocido ≠ 0
    assert table.cost("openai", "gpt-4o-mini", None, 10) is None


def test_pricing_overrides():
    table = PricingTable({"openai/gpt-5": {"input": 1.0, "output": 2.0}})
    assert table.cost("openai", "gpt-5", 1_000_000, 1_000_000) == 3.0


@pytest.mark.parametrize(
    "statuses, expected",
    [(["hit", "hit"], "hit"), (["shared"], "hit"), (["hit", "miss"], "partial"),
     (["miss", "miss"], "miss"), (["disabled"], "disabled"), (["error", "miss"], "error")],
)
def test_cache_summary(statuses, expected):
    assert cache_summary(statuses) == expected


async def test_single_phase_miss_then_hit():
    provider = FakeProvider("openai", [completion("## Estimación", input_tokens=1000, output_tokens=400)])
    resources = make_resources(openai_settings(cache_enabled=True), {"openai": provider}, FakeRedis())
    service = resources.service

    first = build_metadata(await service.generate(T), pricing_source="t")
    second = build_metadata(await service.generate(T), pricing_source="t")

    assert len(provider.calls) == 1
    assert first.cache.status == "miss"
    assert first.cost.incurred_usd == first.cost.original_generation_usd == pytest.approx(_cost(1000, 400))
    assert first.cost.saved_usd == 0.0
    assert first.estimated_cost_usd == first.cost.incurred_usd

    assert second.cache.status == "hit"
    assert second.cost.incurred_usd == 0.0 and second.estimated_cost_usd == 0.0
    assert second.cost.original_generation_usd == pytest.approx(_cost(1000, 400))
    assert second.cost.saved_usd == pytest.approx(_cost(1000, 400))
    assert (second.usage.input_tokens, second.usage.output_tokens) == (1000, 400)
    assert second.usage.incurred_total_tokens == 0
    assert second.usage.phases[0].attempts == 0


async def test_two_phase_reports_cache_per_phase():
    """Cambiar solo el formato de ejemplos reutiliza la extracción pero no la estimación."""
    provider = FakeProvider("openai", [
        completion(REQS, input_tokens=300, output_tokens=40),
        completion("## Estimación A", input_tokens=2000, output_tokens=900),
        completion("## Estimación B", input_tokens=2100, output_tokens=950),
    ])
    resources = make_resources(openai_settings(cache_enabled=True), {"openai": provider}, FakeRedis())
    service = resources.service

    await service.generate(T, GenerationOptions(preprocessing="two_phase"))
    result = await service.generate(T, GenerationOptions(preprocessing="two_phase", example_format="json"))
    meta = build_metadata(result, pricing_source="t")

    assert len(provider.calls) == 3  # la extracción no se repitió
    assert meta.cache.status == "partial"
    assert meta.cache.phases == {"preprocessing": "hit", "estimation": "miss"}
    pre, est = meta.usage.phases
    assert pre.cache == "hit" and pre.cost.incurred_usd == 0.0
    assert est.cache == "miss" and est.cost.incurred_usd == pytest.approx(_cost(2100, 950))
    assert meta.cost.incurred_usd == pytest.approx(_cost(2100, 950))
    assert meta.cost.saved_usd == pytest.approx(_cost(300, 40))
    assert meta.cost.original_generation_usd == pytest.approx(_cost(300, 40) + _cost(2100, 950))
    assert meta.usage.total_tokens == 300 + 40 + 2100 + 950
    assert meta.usage.incurred_total_tokens == 2100 + 950


async def test_unknown_values_propagate_as_null_not_zero():
    provider = FakeProvider("openai", [completion("## E", model="modelo-sin-tarifa", input_tokens=None)])
    resources = make_resources(openai_settings(), {"openai": provider})
    meta = build_metadata(await resources.service.generate(T), pricing_source="t")
    assert meta.usage.input_tokens is None and meta.usage.total_tokens is None
    assert meta.cost.incurred_usd is None and meta.estimated_cost_usd is None
    assert meta.cost.original_generation_usd is None
    assert meta.cache.status == "disabled"
