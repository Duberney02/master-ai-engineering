"""Núcleo de la ingesta: corpus de ejemplo, cargador, registro de parsers, orquestador, CLI y configuración."""

import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.ingestion.catalog.inspect import inspect_root
from app.ingestion.catalog.loader import load_catalog
from app.ingestion.documents.models import Document, DocumentMetadata
from app.ingestion.loaders.filesystem import FileSystemLoader
from app.ingestion.orchestrator import IngestionRejected, ingest_source
from app.ingestion.parsers import BudgetJsonParser, ParserRegistry, TranscriptTxtParser, default_registry

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "seed"


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, timeout=120)


# --- Corpus y catálogo ---


def test_seed_corpus_matches_the_reference():
    assert len(list((SEED / "budgets").glob("*.json"))) == 6
    assert len(list((SEED / "transcripts").glob("*.txt"))) == 3
    assert [p.name for p in SEED.glob("*.xlsx")] == ["rate_card_2024.xlsx"]


def test_shipped_catalog_has_exactly_the_three_reference_sources():
    catalog = load_catalog(ROOT / "data" / "catalog" / "catalog.yaml")

    assert {s.name: s.decision.value for s in catalog.sources} == {
        "presupuestos_json": "include",
        "transcripciones_txt": "review",
        "rate_card_xlsx": "exclude",
    }
    assert [s.name for s in catalog.included_sources()] == ["presupuestos_json"]
    assert catalog.find("rate_card_xlsx").decision_reason and catalog.find("nada") is None


def test_catalog_loader_cli_reports_version_and_sources():
    result = _cli("-m", "app.ingestion.catalog.loader", "data/catalog/catalog.yaml")

    assert result.returncode == 0, result.stderr
    assert "Sources total:  3" in result.stdout and "Sources included: 1" in result.stdout
    assert "presupuestos_json (json)" in result.stdout


def test_inspector_reports_only_observable_facts():
    facts = {f.folder.name: f for f in inspect_root(SEED)}

    assert facts["budgets"].file_count == 6 and facts["budgets"].formats_detected == {"json"}
    assert facts["transcripts"].file_count == 3 and facts["transcripts"].formats_detected == {"txt"}
    assert facts["seed"].formats_detected == {"xlsx"} and facts["seed"].file_count == 1
    assert all(f.latest_modified is not None for f in facts.values())


def test_inspector_cli_and_missing_folder(tmp_path):
    ok = _cli("-m", "app.ingestion.catalog.inspect", "data/seed")
    missing = _cli("-m", "app.ingestion.catalog.inspect", str(tmp_path / "no-existe"))

    assert ok.returncode == 0 and "budgets" in ok.stdout and "formats=json" in ok.stdout
    assert missing.returncode != 0


def test_inspector_does_not_modify_the_catalog():
    catalog_path = ROOT / "data" / "catalog" / "catalog.yaml"
    before = catalog_path.read_bytes()

    inspect_root(SEED)

    assert catalog_path.read_bytes() == before


# --- Cargador y registro ---


def test_loader_walks_in_order_and_filters_by_extension(tmp_path):
    (tmp_path / "src").mkdir()
    for name in ("b.json", "a.json", "c.txt", "d.JSON"):
        (tmp_path / "src" / name).write_text("{}", encoding="utf-8")

    blobs = list(FileSystemLoader(tmp_path).iter_blobs("src", {"json"}))

    assert [b.relative_path.replace("\\", "/") for b in blobs] == ["src/a.json", "src/b.json", "src/d.JSON"]
    assert blobs[0].bytes_ == b"{}"


def test_loader_accepts_a_single_file_location(tmp_path):
    (tmp_path / "tarifas.xlsx").write_bytes(b"x")

    assert [b.relative_path for b in FileSystemLoader(tmp_path).iter_blobs("tarifas.xlsx", {"xlsx"})] == ["tarifas.xlsx"]


def test_loader_raises_when_the_location_does_not_exist(tmp_path):
    with pytest.raises(FileNotFoundError, match="nowhere"):
        list(FileSystemLoader(tmp_path).iter_blobs("nowhere", {"json"}))


def test_default_registry_has_only_json_and_txt_parsers():
    registry = default_registry()

    assert registry.formats() == {"json", "txt"}
    assert isinstance(registry.get("json"), BudgetJsonParser) and isinstance(registry.get("txt"), TranscriptTxtParser)
    for unsupported in ("xlsx", "docx", "pdf", "csv"):
        with pytest.raises(KeyError):
            registry.get(unsupported)


def test_registry_rejects_a_duplicate_format():
    registry = ParserRegistry()
    registry.register(BudgetJsonParser())

    with pytest.raises(ValueError, match="json"):
        registry.register(BudgetJsonParser())


def test_document_models_forbid_extra_fields():
    meta = {"source_name": "s", "source_version": "1", "ingested_at": datetime.now(timezone.utc)}

    assert DocumentMetadata(**meta).sensitivity_access_level == "internal"
    with pytest.raises(ValidationError):
        DocumentMetadata(**meta, nope=1)
    with pytest.raises(ValidationError):
        Document(id="x", text="t", metadata=DocumentMetadata(**meta), nope=1)


# --- Orquestador ---


class RecordingJobs:
    def __init__(self):
        self.events: list[tuple] = []

    async def mark_running(self, job_id):
        self.events.append(("running",))

    async def mark_completed(self, job_id, *, documents_count):
        self.events.append(("completed", documents_count))

    async def mark_failed(self, job_id, *, error_message):
        self.events.append(("failed", error_message))


def _ingest(source_name, jobs, **overrides):
    kwargs = dict(
        catalog=load_catalog(ROOT / "data" / "catalog" / "catalog.yaml"),
        source_name=source_name,
        loader=FileSystemLoader(SEED),
        registry=default_registry(),
        jobs_repo=jobs,
        job_id=uuid.uuid4(),
    )
    return ingest_source(**{**kwargs, **overrides})


async def test_ingesting_the_budgets_yields_six_documents_and_completes():
    jobs = RecordingJobs()

    documents = await _ingest("presupuestos_json", jobs)

    assert jobs.events == [("running",), ("completed", 6)]
    assert len(documents) == 6 and len({d.id for d in documents}) == 6
    assert {d.metadata.source_name for d in documents} == {"presupuestos_json"}
    assert {d.metadata.source_version for d in documents} == {"1.0.0"}
    assert all(d.metadata.sensitivity_access_level == "confidential" for d in documents)
    assert "# Presupuesto BUDGET-2024-0001" in next(d.text for d in documents if "0001" in d.id)


async def test_ingestion_ids_are_stable_across_runs():
    first = await _ingest("presupuestos_json", RecordingJobs())
    second = await _ingest("presupuestos_json", RecordingJobs())

    assert [d.id for d in first] == [d.id for d in second]


@pytest.mark.parametrize("name", ["transcripciones_txt", "rate_card_xlsx", "no_existe"])
async def test_rejected_sources_never_start_the_job(name):
    jobs = RecordingJobs()

    with pytest.raises(IngestionRejected):
        await _ingest(name, jobs)

    assert jobs.events == []


async def test_failure_marks_the_job_failed_and_propagates(tmp_path):
    jobs = RecordingJobs()

    with pytest.raises(FileNotFoundError):
        await _ingest("presupuestos_json", jobs, loader=FileSystemLoader(tmp_path))

    assert jobs.events[0] == ("running",) and jobs.events[1][0] == "failed" and "budgets" in jobs.events[1][1]


async def test_ingestion_does_not_run_cleaning_or_pseudonymization(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("no debe invocarse desde el orquestador")

    monkeypatch.setattr("app.ingestion.cleaning.budget_records.clean_budget_records", boom)
    monkeypatch.setattr("app.ingestion.cleaning.policy.validate_with_policy", boom)
    monkeypatch.setattr("app.ingestion.pii.pseudonymizer.ConsistentPseudonymizer.pseudonymize", boom)

    assert len(await _ingest("presupuestos_json", RecordingJobs())) == 6


def test_the_legacy_transcript_is_parsed_by_blocks_and_tagged_ones_by_turns():
    from app.ingestion.parsers import ParseContext

    catalog = load_catalog(ROOT / "data" / "catalog" / "catalog.yaml")
    context = ParseContext(
        source=catalog.find("transcripciones_txt"), source_version="1.0.0", ingested_at=datetime.now(timezone.utc)
    )
    documents = [
        d
        for blob in FileSystemLoader(SEED).iter_blobs("transcripts", {"txt"})
        for d in TranscriptTxtParser().parse(blob, context)
    ]
    modes = {d.metadata.extra["format_mode"] for d in documents}
    legacy = [d for d in documents if d.metadata.extra["format_mode"] == "legacy"]

    assert modes == {"tagged", "legacy"}
    assert legacy and all("speaker" not in d.metadata.extra for d in legacy)
    assert all("speaker" in d.metadata.extra for d in documents if d.metadata.extra["format_mode"] == "tagged")


# --- Viabilidad CAG (CLI) ---


def test_architecture_cli_prints_the_reference_scenario():
    result = _cli("-m", "app.ingestion.architecture")

    assert result.returncode == 0, result.stderr
    assert "Viabilidad CAG: NO viable" in result.stdout
    assert "context_window" in result.stdout and "lost_in_the_middle" in result.stdout
    assert "Recomendación arquitectónica: RAG" in result.stdout


# --- Configuración ---


def test_ingestion_settings_defaults():
    settings = Settings(_env_file=None, openai_api_key="k")

    assert settings.catalog_path == Path("data/catalog/catalog.yaml")
    assert settings.ingestion_data_root == Path("data/seed")
    assert settings.presidio_spacy_model == "es_core_news_md"
    assert settings.pseudonym_faker_locale == "es_ES"
    assert settings.pseudonym_hash_salt == "change-me-in-prod"
    assert settings.max_attachment_chars == 60_000


def test_ingestion_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("CATALOG_PATH", "/tmp/otro.yaml")
    monkeypatch.setenv("INGESTION_DATA_ROOT", "/tmp/datos")
    monkeypatch.setenv("PRESIDIO_SPACY_MODEL", "es_core_news_sm")
    monkeypatch.setenv("PSEUDONYM_FAKER_LOCALE", "es_MX")
    monkeypatch.setenv("PSEUDONYM_HASH_SALT", "sal")
    monkeypatch.setenv("MAX_ATTACHMENT_CHARS", "1234")

    settings = Settings(_env_file=None)

    assert settings.catalog_path == Path("/tmp/otro.yaml") and settings.ingestion_data_root == Path("/tmp/datos")
    assert (settings.presidio_spacy_model, settings.pseudonym_faker_locale) == ("es_core_news_sm", "es_MX")
    assert (settings.pseudonym_hash_salt, settings.max_attachment_chars) == ("sal", 1234)


def test_max_attachment_chars_must_be_positive(monkeypatch):
    monkeypatch.setenv("MAX_ATTACHMENT_CHARS", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_budget_json_ids_are_deterministic_for_the_same_file():
    from app.ingestion.parsers import ParseContext

    catalog = load_catalog(ROOT / "data" / "catalog" / "catalog.yaml")
    context = ParseContext(
        source=catalog.find("presupuestos_json"), source_version="1.0.0", ingested_at=datetime.now(timezone.utc)
    )
    blob = next(FileSystemLoader(SEED).iter_blobs("budgets", {"json"}))

    first, second = list(BudgetJsonParser().parse(blob, context)), list(BudgetJsonParser().parse(blob, context))

    assert first[0].id == second[0].id == f"presupuestos_json:{json.loads(blob.bytes_)['budget_id']}:{blob.relative_path}"


async def test_ingestion_logs_carry_the_job_and_source_and_never_the_error_text(capsys, tmp_path):
    from app.logging_config import configure_logging

    configure_logging("development", "INFO")
    job_id = uuid.uuid4()
    await _ingest("presupuestos_json", RecordingJobs(), job_id=job_id)
    with pytest.raises(FileNotFoundError):
        await _ingest("presupuestos_json", RecordingJobs(), loader=FileSystemLoader(tmp_path), job_id=job_id)

    logs = capsys.readouterr().err
    assert f"job_id={job_id}" in logs and "source_name=presupuestos_json" in logs
    assert "documents_count=6" in logs and "error_type=FileNotFoundError" in logs
    assert str(tmp_path) not in logs
