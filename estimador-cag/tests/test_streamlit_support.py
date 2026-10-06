import pytest

from app.streamlit_support import (
    MAX_TRANSCRIPT_BYTES,
    decode_transcript,
    iter_sync,
    sync_secrets_to_env,
)


def test_sync_secrets_to_env_copies_known_keys():
    secrets = {"OPENAI_API_KEY": "sk-from-secrets", "SOME_OTHER_KEY": "ignored"}
    environ: dict = {}

    sync_secrets_to_env(secrets, environ)

    assert environ == {"OPENAI_API_KEY": "sk-from-secrets"}


def test_sync_secrets_to_env_does_not_override_existing_env():
    secrets = {"OPENAI_API_KEY": "sk-from-secrets"}
    environ = {"OPENAI_API_KEY": "sk-from-env"}

    sync_secrets_to_env(secrets, environ)

    assert environ["OPENAI_API_KEY"] == "sk-from-env"


def test_sync_secrets_to_env_handles_empty_secrets():
    environ: dict = {"PATH": "/usr/bin"}

    sync_secrets_to_env({}, environ)

    assert environ == {"PATH": "/usr/bin"}


async def _fake_stream():
    yield "Hola "
    yield "mundo"


def test_iter_sync_yields_chunks_in_order():
    assert list(iter_sync(_fake_stream())) == ["Hola ", "mundo"]


async def _empty_stream():
    return
    yield  # pragma: no cover - makes this an async generator


def test_iter_sync_empty_generator_yields_nothing():
    assert list(iter_sync(_empty_stream())) == []


def test_decode_transcript_accepts_utf8_with_or_without_bom():
    assert decode_transcript("Reunión: añadir facturación".encode("utf-8")) == "Reunión: añadir facturación"
    assert decode_transcript(b"\xef\xbb\xbfHola") == "Hola"


def test_decode_transcript_rejects_invalid_encoding_and_oversized_files():
    with pytest.raises(ValueError, match="UTF-8"):
        decode_transcript("Reunión".encode("latin-1"))
    with pytest.raises(ValueError, match="400 KB"):
        decode_transcript(b"x" * (MAX_TRANSCRIPT_BYTES + 1))
    assert len(decode_transcript(b"x" * MAX_TRANSCRIPT_BYTES)) == MAX_TRANSCRIPT_BYTES
