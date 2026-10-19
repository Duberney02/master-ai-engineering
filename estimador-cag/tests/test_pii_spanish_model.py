"""Analizador Presidio real con `es_core_news_md` (instalado en la imagen); detecta nombres hispanos y dominio."""

import pytest

from app.ingestion.pii import ConsistentPseudonymizer, InMemoryMappingStore, build_analyzer
from app.ingestion.pii.analyzer import build_analyzer as build_analyzer_from_module

TEXT = "Laura Fernández (laura.fernandez@acme.es) revisó BUDGET-2024-0001 del cliente CLI-0042."


@pytest.fixture(scope="module")
def analyzer():
    return build_analyzer()


def test_analyzer_is_a_singleton_wired_to_spanish(analyzer):
    assert build_analyzer_from_module() is analyzer
    assert analyzer.supported_languages == ["es"]


def test_spanish_model_detects_people_emails_and_domain_identifiers(analyzer):
    found = {r.entity_type: TEXT[r.start : r.end] for r in analyzer.analyze(text=TEXT, language="es")}

    assert "Laura Fernández" in found["PERSON"]
    assert found["EMAIL_ADDRESS"] == "laura.fernandez@acme.es"
    assert found["BUDGET_ID"] == "BUDGET-2024-0001" and found["CLIENT_CODE"] == "CLI-0042"


async def test_end_to_end_pseudonymization_is_consistent_and_hides_the_originals(analyzer):
    pseudonymizer = ConsistentPseudonymizer(
        analyzer=analyzer, mapping_store=InMemoryMappingStore(), salt="sal-de-prueba", faker_locale="es_ES"
    )

    first = await pseudonymizer.pseudonymize(TEXT)
    second = await pseudonymizer.pseudonymize(f"Otra vez {TEXT}")

    for original in ("Laura Fernández", "laura.fernandez@acme.es", "BUDGET-2024-0001", "CLI-0042"):
        assert original not in first.pseudonymized_text
    by_type = {m.entity_type: m.pseudonym for m in first.applied}
    assert by_type["BUDGET_ID"].startswith("BUDGET-") and by_type["CLIENT_CODE"].startswith("CLI-")
    assert {m.entity_type: m.pseudonym for m in second.applied} == by_type
    assert all(len(m.original_hash) == 64 for m in first.applied)


async def test_hash_depends_on_the_salt(analyzer):
    one = ConsistentPseudonymizer(analyzer=analyzer, mapping_store=InMemoryMappingStore(), salt="uno")
    two = ConsistentPseudonymizer(analyzer=analyzer, mapping_store=InMemoryMappingStore(), salt="dos")

    first = await one.pseudonymize("Cliente CLI-0042.")
    second = await two.pseudonymize("Cliente CLI-0042.")

    assert first.applied[0].original_hash != second.applied[0].original_hash
