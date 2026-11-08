import pytest

from estimator_chat.support import MAX_TRANSCRIPT_BYTES, decode_transcript


def test_decode_transcript_reads_utf8_and_strips_the_bom():
    assert decode_transcript("Reunión de planificación".encode()) == "Reunión de planificación"
    assert decode_transcript(b"\xef\xbb\xbfhola") == "hola"


def test_decode_transcript_rejects_non_utf8_with_a_user_message():
    with pytest.raises(ValueError, match="UTF-8"):
        decode_transcript("Reunión".encode("latin-1"))


def test_decode_transcript_rejects_files_over_the_limit():
    with pytest.raises(ValueError, match="máximo de 400 KB"):
        decode_transcript(b"a" * (MAX_TRANSCRIPT_BYTES + 1))
    assert decode_transcript(b"a" * MAX_TRANSCRIPT_BYTES)
