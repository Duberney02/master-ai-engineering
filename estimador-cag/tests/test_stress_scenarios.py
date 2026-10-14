"""Escenarios multi-turno, fact-tracker y PDFs sintéticos del stress test."""

import pytest

from app.schemas import MAX_DESCRIPTION_CHARS, MIN_DESCRIPTION_CHARS
from evals.stress.fixtures.build_pdfs import FACTS, build_pdf, build_pdfs
from evals.stress.metrics import Snapshot
from evals.stress.scenarios import ALLOWED_N, PROFILES, FactTracker, build_scenario


@pytest.mark.parametrize("profile", PROFILES)
def test_every_scenario_has_twenty_valid_deterministic_turns(profile):
    scenario = build_scenario(profile)

    assert [t.turn_index for t in scenario.turns] == list(range(1, 21))
    assert all(len(t.transcript) >= MIN_DESCRIPTION_CHARS for t in scenario.turns)
    assert scenario.turns == build_scenario(profile).turns
    assert scenario.turns[-1].fact_to_remember is None


@pytest.mark.parametrize("n", ALLOWED_N)
def test_prefix_returns_the_first_n_turns(n):
    assert len(build_scenario("growing").prefix(n)) == n


@pytest.mark.parametrize("n", [0, 2, 7, 21])
def test_unsupported_n_is_rejected(n):
    with pytest.raises(ValueError):
        build_scenario("growing").prefix(n)


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError):
        build_scenario("otro")


def test_growing_names_the_project_in_turn_one_and_never_changes_it():
    scenario = build_scenario("growing")

    assert scenario.turns[0].fact_to_remember == "Atlas" and "Atlas" in scenario.turns[0].transcript
    assert all("Atlas" not in t.transcript for t in scenario.turns[1:])


def test_pivot_changes_the_stack_in_turn_five():
    scenario = build_scenario("pivot")

    assert "Django" in scenario.turns[1].transcript
    assert "NestJS" in scenario.turns[4].transcript and "abandonamos Django" in scenario.turns[4].transcript
    assert scenario.superseded == {"Django": 5}


def test_contradiction_sets_30k_in_turn_three_and_80k_in_turn_eight():
    scenario = build_scenario("contradiction")

    assert "30.000 EUR" in scenario.turns[2].transcript
    assert "80.000 EUR" in scenario.turns[7].transcript and "30.000" not in scenario.turns[7].transcript
    facts = {f.text: f for f in scenario.facts()}
    assert facts["30.000|30000|30 000"].superseded_at == 8 and facts["80.000|80000|80 000"].superseded_at is None


def test_tracker_only_evaluates_facts_from_earlier_turns():
    tracker = FactTracker(build_scenario("pivot"))

    checks = tracker.evaluate(Snapshot(turn_index=3, metadata={"project_name": "Helios"}))

    assert [c.fact.text for c in checks] == ["Helios", "Django"]
    assert [c.retained for c in checks] == [True, False]
    assert FactTracker.recall(checks) == 0.5


def test_tracker_separates_active_from_superseded_facts():
    tracker = FactTracker(build_scenario("pivot"))
    memory = Snapshot(turn_index=6, metadata={"project_name": "Helios", "mentioned_technologies": ["Django", "NestJS"]})

    checks = {c.fact.text: c for c in tracker.evaluate(memory)}

    assert checks["Django"].retained and not checks["Django"].active and checks["Django"].stale_present
    assert not checks["NestJS"].stale_present
    # Django ya no cuenta para el recall: la memoria acumula tecnologías (no las sustituye).
    assert all(c.fact.text != "Django" or not c.active for c in checks.values())


def test_recall_is_none_before_any_fact_exists():
    assert FactTracker.recall([]) is None


# --- PDFs sintéticos ---


def test_pdfs_are_deterministic_and_close_to_the_requested_size():
    first, second = build_pdf(5), build_pdf(5)

    assert first == second
    assert 5 * 1024 <= len(first) <= 6 * 1024


def test_build_pdfs_records_real_sizes_and_extracted_text(tmp_path):
    fixtures = build_pdfs(tmp_path, (0, 5, 20))

    assert sorted(fixtures) == [5, 20]  # 0 = sin adjunto: no genera archivo
    assert sorted(p.name for p in tmp_path.glob("*.pdf")) == ["adjunto_20kb.pdf", "adjunto_5kb.pdf"]
    small, large = fixtures[5], fixtures[20]
    assert small.size_bytes < large.size_bytes and small.extracted_chars < large.extracted_chars
    for fixture in fixtures.values():
        assert all(fixture.facts_extracted.values()) and set(fixture.facts_extracted) == set(FACTS)
        assert fixture.chars_to_description_limit == MAX_DESCRIPTION_CHARS - fixture.extracted_chars
        assert not fixture.over_limit
    assert (tmp_path / "manifest.json").is_file()
