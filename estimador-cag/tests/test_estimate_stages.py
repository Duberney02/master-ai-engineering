"""`/v1/estimate/stages/*`: cadena completa sin estado, señales de fundamentación y errores por etapa."""

from structlog.testing import capture_logs

from app.generation.rag.schemas import Estimate
from tests._grounded import (
    BRIEF,
    ESTIMATE_KEY,
    SECRET,
    TRANSCRIPT,
    FakeRetriever,
    ScriptedGenerator,
    api_client,
    build_estimator,
    estimate_payload,
    failing_retriever,
    incoherent_insufficient,
    make_chunk,
)

HEADERS = {"X-API-Key": ESTIMATE_KEY}
STAGES = "/v1/estimate/stages"


def test_chaining_the_four_stages_yields_the_full_pipeline_estimate(monkeypatch):
    generator = ScriptedGenerator(BRIEF, estimate_payload(source_ids=(1, 2)))
    retriever = FakeRetriever([make_chunk(1), make_chunk(2, 0.3)])
    client = api_client(monkeypatch, build_estimator(generator, retriever))

    reformulated = client.post(f"{STAGES}/reformulate", json={"transcript": TRANSCRIPT}, headers=HEADERS)
    assert reformulated.status_code == 200
    brief = reformulated.json()
    assert brief["query"]["sector"] == "finance" and "for finance" in brief["search_text"]

    retrieved = client.post(
        f"{STAGES}/retrieve", json={"query_text": brief["search_text"], "sectors": ["finance"]}, headers=HEADERS
    )
    assert retrieved.status_code == 200 and retrieved.json()["low_confidence"] is False
    assert retriever.calls[0]["query_text"] == brief["search_text"]

    assembled = client.post(
        f"{STAGES}/assemble", json={"chunks": retrieved.json()["chunks"], "query": brief["query"]}, headers=HEADERS
    )
    assert assembled.status_code == 200
    context = assembled.json()
    assert context["dropped_count"] == 0 and context["token_count"] > 0
    assert '<source id="1"' in context["context_block"] and len(context["kept_chunks"]) == 2

    generated = client.post(
        f"{STAGES}/generate",
        json={"context_block": context["context_block"], "query": brief["query"], "kept_chunks": context["kept_chunks"]},
        headers=HEADERS,
    )
    assert generated.status_code == 200
    result = generated.json()
    assert Estimate.model_validate(result["estimate"]).confidence == "high"  # misma forma que from-transcript
    assert result["fabricated_source_ids"] == [] and result["coherent"] is True


def test_assemble_truncates_to_the_requested_budget(monkeypatch):
    client = api_client(monkeypatch)
    chunks = [make_chunk(i, content="token " * 200).model_dump() for i in range(1, 4)]

    result = client.post(f"{STAGES}/assemble", json={"chunks": chunks, "max_context_tokens": 300}, headers=HEADERS).json()

    assert [chunk["id"] for chunk in result["kept_chunks"]] == [1] and result["dropped_count"] == 2


def test_generate_reports_fabricated_ids_without_retrying(monkeypatch):
    generator = ScriptedGenerator(estimate_payload(source_ids=(1, 999)))
    client = api_client(monkeypatch, build_estimator(generator))

    result = client.post(
        f"{STAGES}/generate",
        json={"context_block": "<source id=\"1\">x</source>", "query": BRIEF, "kept_chunks": [make_chunk(1).model_dump()]},
        headers=HEADERS,
    ).json()

    assert result["fabricated_source_ids"] == [999] and len(generator.calls) == 1
    assert result["estimate"]["confidence"] == "high"  # sin rebaja: la etapa solo informa


def test_generate_reports_incoherence(monkeypatch):
    client = api_client(monkeypatch, build_estimator(ScriptedGenerator(incoherent_insufficient())))

    result = client.post(f"{STAGES}/generate", json={"context_block": "ctx", "query": BRIEF}, headers=HEADERS).json()

    assert result["coherent"] is False


def test_reformulation_failure_is_a_502_and_logged(monkeypatch):
    client = api_client(monkeypatch, build_estimator(ScriptedGenerator(RuntimeError(SECRET), RuntimeError(SECRET))))

    with capture_logs() as logs:
        response = client.post(
            f"{STAGES}/reformulate", json={"transcript": TRANSCRIPT}, headers={**HEADERS, "X-Request-ID": "stage-1"}
        )

    assert response.status_code == 502 and SECRET not in response.text
    assert response.json() == {"detail": "No se pudo reformular la transcripción."}
    failed = [log for log in logs if log["event"] == "rag_stage_failed"]
    assert failed and failed[0]["stage"] == "reformulation" and failed[0]["request_id"] == "stage-1"
    assert isinstance(failed[0]["duration_ms"], int)


def test_generation_failure_is_a_502(monkeypatch):
    client = api_client(monkeypatch, build_estimator(ScriptedGenerator(RuntimeError(SECRET))))

    response = client.post(f"{STAGES}/generate", json={"context_block": "ctx", "query": BRIEF}, headers=HEADERS)

    assert response.status_code == 502 and SECRET not in response.text


def test_retrieve_stage_shares_the_retrieval_contract(monkeypatch):
    client = api_client(monkeypatch, build_estimator(retriever=failing_retriever()))

    response = client.post(f"{STAGES}/retrieve", json={"query_text": "payments"}, headers=HEADERS)

    assert response.status_code == 502 and SECRET not in response.text


def test_invalid_stage_input_is_422(monkeypatch):
    client = api_client(monkeypatch)

    assert client.post(f"{STAGES}/reformulate", json={"transcript": "corta"}, headers=HEADERS).status_code == 422
    assert client.post(f"{STAGES}/retrieve", json={"query_text": ""}, headers=HEADERS).status_code == 422
    assert client.post(f"{STAGES}/assemble", json={"chunks": [{"id": "x"}]}, headers=HEADERS).status_code == 422
    assert client.post(f"{STAGES}/generate", json={"context_block": "", "query": BRIEF}, headers=HEADERS).status_code == 422
