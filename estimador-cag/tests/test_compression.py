"""Política de compresión: anclas fuera de la ventana, resumen acumulativo y degradación ante fallos."""

import pytest

from app.services.anchors import AnchorMatch, HeuristicAnchorDetector
from app.services.compression import CompressionPolicy
from app.services.llm_wrapper import Completion
from app.services.sessions import MAX_ANCHORS, ConversationHistory
from app.services.summarizer import LLMSummarizer
from tests._fakes import openai_settings


class FakeSummarizer:
    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[tuple[str, list[tuple[str, str]]]] = []

    async def summarize(self, previous, turns):
        self.calls.append((previous, list(turns)))
        result = self.results.pop(0) if self.results else f"resumen de {len(self.calls)}"
        if isinstance(result, Exception):
            raise result
        return result, [Completion(text=result, model="m", provider="openai")]


def history(max_turns=2) -> ConversationHistory:
    return ConversationHistory(max_turns)


def fill(h: ConversationHistory, *messages: str) -> None:
    for index, user in enumerate(messages, start=1):
        h.add_turn(user, f"a{index}")


# --- Estructura del historial ---


def test_turns_that_leave_the_window_are_queued_for_compression_in_order():
    h = history(2)
    fill(h, "u1", "u2", "u3", "u4")

    assert h.turns == [("u3", "a3"), ("u4", "a4")]
    assert h.drain_retired() == [("u1", "a1"), ("u2", "a2")]
    assert h.drain_retired() == []


def test_anchors_are_deduplicated_and_bounded_keeping_the_most_recent():
    from app.services.sessions import AnchorTurn

    h = history()
    for n in range(MAX_ANCHORS + 3):
        h.add_anchor(AnchorTurn(f"u{n}", f"a{n}", ("contract",)))
    h.add_anchor(AnchorTurn(f"u{MAX_ANCHORS + 2}", f"a{MAX_ANCHORS + 2}"))

    assert len(h.anchors) == MAX_ANCHORS
    assert h.anchors[0].user == "u3" and h.anchors[-1].user == f"u{MAX_ANCHORS + 2}"


# --- Política ---


async def test_without_retired_turns_the_policy_does_nothing():
    summarizer = FakeSummarizer()
    policy = CompressionPolicy(HeuristicAnchorDetector(), summarizer)
    h = history(3)
    fill(h, "u1", "u2")

    report = await policy.apply(h)

    assert report.retired == 0 and summarizer.calls == [] and h.summary == ""


async def test_retired_turn_without_commitments_is_summarized():
    summarizer = FakeSummarizer("Quieren un portal de pedidos.")
    policy = CompressionPolicy(HeuristicAnchorDetector(), summarizer)
    h = history(1)
    fill(h, "Queremos un portal de pedidos", "Añadid facturas")

    report = await policy.apply(h)

    assert summarizer.calls == [("", [("Queremos un portal de pedidos", "a1")])]
    assert h.summary == "Quieren un portal de pedidos."
    assert report.summary_updated and report.anchors == [] and len(report.completions) == 1


async def test_summary_accumulates_previous_summary_with_the_new_retired_turns():
    summarizer = FakeSummarizer("primero", "primero y segundo")
    policy = CompressionPolicy(HeuristicAnchorDetector(), summarizer)
    h = history(1)

    fill(h, "u1", "u2")
    await policy.apply(h)
    h.add_turn("u3", "a3")
    await policy.apply(h)

    assert summarizer.calls[1] == ("primero", [("u2", "a2")])
    assert h.summary == "primero y segundo"


async def test_commitment_turn_becomes_an_anchor_outside_the_window_and_is_not_summarized():
    summarizer = FakeSummarizer()
    policy = CompressionPolicy(HeuristicAnchorDetector(), summarizer)
    h = history(1)
    fill(h, "El presupuesto acordado es de 40.000 euros", "Seguimos con el diseño")

    report = await policy.apply(h)

    assert [(a.user, a.rules) for a in h.anchors] == [
        ("El presupuesto acordado es de 40.000 euros", ("agreed_budget",))
    ]
    assert report.anchors == h.anchors and summarizer.calls == [] and h.summary == ""


async def test_mixed_retirement_anchors_the_commitment_and_summarizes_the_rest():
    summarizer = FakeSummarizer("resumen")
    policy = CompressionPolicy(HeuristicAnchorDetector(), summarizer)
    h = history(1)
    fill(h, "Queremos una web", "Contrato firmado ayer", "Queremos pagos", "último")

    await policy.apply(h)

    assert [a.user for a in h.anchors] == ["Contrato firmado ayer"]
    assert summarizer.calls[0][1] == [("Queremos una web", "a1"), ("Queremos pagos", "a3")]


@pytest.mark.parametrize("failure", [RuntimeError("proveedor caído"), ""])
async def test_summarizer_failure_or_empty_result_keeps_the_previous_summary(failure):
    summarizer = FakeSummarizer("resumen previo", failure)
    policy = CompressionPolicy(HeuristicAnchorDetector(), summarizer)
    h = history(1)
    fill(h, "u1", "u2")
    await policy.apply(h)
    h.add_turn("u3", "a3")

    report = await policy.apply(h)

    assert h.summary == "resumen previo" and report.summary_failed and not report.summary_updated


async def test_detector_errors_never_break_the_policy():
    class Broken:
        async def detect(self, user, assistant):
            raise RuntimeError("boom")

    summarizer = FakeSummarizer("ok")
    policy = CompressionPolicy(Broken(), summarizer)
    h = history(1)
    fill(h, "u1", "u2")

    await policy.apply(h)

    assert h.summary == "ok" and h.anchors == []


async def test_anchor_detection_is_logged_with_rule_names_and_not_the_text(capsys):
    import structlog

    class Always:
        async def detect(self, user, assistant):
            return AnchorMatch(rules=("contract", "deadline"), source="heuristic")

    policy = CompressionPolicy(Always(), FakeSummarizer())
    h = history(1)
    fill(h, "SECRETO-DEL-CLIENTE", "u2")

    with structlog.testing.capture_logs() as logs:
        await policy.apply(h)

    event = next(entry for entry in logs if entry["event"] == "anchor_detected")
    assert event["anchor_rules"] == ["contract", "deadline"]
    assert "SECRETO-DEL-CLIENTE" not in str(logs)


# --- Resumidor LLM ---


async def test_llm_summarizer_uses_its_template_model_and_normalizes_the_result():
    seen = {}

    async def generate(messages, accept=None, **options):
        seen["messages"], seen["options"] = messages, options
        return Completion(text="Resumen <b>limpio</b>\n\n\n\nfin `x`", model="m", provider="openai")

    summarizer = LLMSummarizer(openai_settings(summary_model="barato"), generate=generate)

    summary, completions = await summarizer.summarize("previo", [("u1", "a1")])

    assert summary == "Resumen b limpio /b\n\nfin x"
    assert "previo" in seen["messages"][1]["content"] and "u1" in seen["messages"][1]["content"]
    assert seen["options"]["model"] == "barato" and len(completions) == 1
