"""Extracción local de adjuntos PDF y Word (sin red)."""

import pytest
from fastapi import HTTPException

from app.services import attachments
from app.services.attachments import (
    AttachmentError,
    combine_text,
    extract_attachments,
    safe_filename,
)
from tests._documents import make_blank_pdf, make_docx, make_pdf


async def _extract(*files):
    return await extract_attachments(list(files))


async def test_pdf_text_is_extracted_with_its_separator():
    [pdf] = await _extract(("requisitos.pdf", make_pdf("Proyecto Orion con PostgreSQL")))

    assert pdf.filename == "requisitos.pdf"
    assert pdf.block == "--- attachment: requisitos.pdf ---\nProyecto Orion con PostgreSQL"


async def test_every_pdf_page_is_extracted_in_order():
    [pdf] = await _extract(("a.pdf", make_pdf("Pagina uno", "Pagina dos")))

    assert pdf.text.index("Pagina uno") < pdf.text.index("Pagina dos")


async def test_docx_paragraphs_and_tables_are_extracted_in_document_order():
    data = make_docx(["Alcance del portal", "Fin"], table=[["Rol", "Horas"], ["Backend", "120"]])

    [doc] = await _extract(("alcance.DOCX", data))

    assert doc.filename == "alcance.DOCX"
    assert doc.text.splitlines() == ["Alcance del portal", "Fin", "Rol | Horas", "Backend | 120"]


async def test_several_attachments_follow_the_transcript_in_the_order_received():
    extracted = await _extract(
        ("uno.pdf", make_pdf("primero")), ("dos.docx", make_docx(["segundo"])),
    )

    text = combine_text("  Transcripción de la reunión  ", extracted)

    assert text == (
        "Transcripción de la reunión\n\n"
        "--- attachment: uno.pdf ---\nprimero\n\n"
        "--- attachment: dos.docx ---\nsegundo"
    )


def test_combine_text_without_transcript_or_attachments():
    assert combine_text("", []) == ""
    assert combine_text("  solo texto ", []) == "solo texto"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("informe.pdf", "informe.pdf"),
        ("C:\\Users\\ana\\informe.pdf", "informe.pdf"),
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("a\nb\r\n--- attachment: fake.pdf ---.pdf", "a b - attachment: fake.pdf -.pdf"),
        ("<script>.pdf", "script .pdf"),
        ("", "attachment"),
        (None, "attachment"),
    ],
)
def test_filenames_are_reduced_to_a_safe_single_line(raw, expected):
    name = safe_filename(raw)

    assert name == expected
    assert "\n" not in name and "---" not in name


def test_long_filenames_are_truncated_keeping_the_extension():
    name = safe_filename("x" * 300 + ".pdf")

    assert len(name) == attachments.MAX_FILENAME_CHARS and name.endswith(".pdf")


async def test_forged_separator_in_the_filename_cannot_open_a_second_block():
    [pdf] = await _extract(("x\n--- attachment: fake.pdf ---\n.pdf", make_pdf("texto")))

    assert pdf.block.count("--- attachment:") == 1 and pdf.block.startswith("--- attachment: x")


@pytest.mark.parametrize("name", ["notas.txt", "datos.doc", "foto.png", "sinextension", "pdf"])
async def test_unsupported_extensions_are_rejected_with_415(name):
    with pytest.raises(AttachmentError) as exc:
        await _extract((name, b"contenido"))

    assert exc.value.status_code == 415


async def test_content_must_match_the_extension():
    with pytest.raises(AttachmentError) as pdf:
        await _extract(("falso.pdf", b"esto no es un pdf"))
    with pytest.raises(AttachmentError) as docx:
        await _extract(("falso.docx", make_pdf("texto")))
    with pytest.raises(AttachmentError) as zip_only:
        await _extract(("falso.docx", _zip_without_document()))

    assert pdf.value.status_code == docx.value.status_code == zip_only.value.status_code == 415


def _zip_without_document() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("otra.txt", "x")
    return buffer.getvalue()


async def test_pdf_without_extractable_text_is_422():
    with pytest.raises(AttachmentError) as exc:
        await _extract(("escaneado.pdf", make_blank_pdf()))

    assert exc.value.status_code == 422 and "escaneado.pdf" in exc.value.detail


async def test_corrupt_pdf_is_422_without_leaking_internals():
    with pytest.raises(AttachmentError) as exc:
        await _extract(("roto.pdf", b"%PDF-1.4\nbasura sin estructura"))

    assert exc.value.status_code == 422 and "Traceback" not in exc.value.detail


async def test_password_protected_pdf_is_422():
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secreto", algorithm="RC4-128")
    buffer = BytesIO()
    writer.write(buffer)

    with pytest.raises(AttachmentError) as exc:
        await _extract(("cifrado.pdf", buffer.getvalue()))

    assert exc.value.status_code == 422


async def test_empty_docx_is_422():
    with pytest.raises(AttachmentError) as exc:
        await _extract(("vacio.docx", make_docx([])))

    assert exc.value.status_code == 422


async def test_oversized_attachment_is_413(monkeypatch):
    monkeypatch.setattr(attachments, "MAX_ATTACHMENT_BYTES", 50)

    with pytest.raises(AttachmentError) as exc:
        await _extract(("grande.pdf", make_pdf("x" * 100)))

    assert exc.value.status_code == 413


async def test_too_many_attachments_is_413(monkeypatch):
    monkeypatch.setattr(attachments, "MAX_ATTACHMENTS", 1)
    pdf = make_pdf("texto")

    with pytest.raises(AttachmentError) as exc:
        await _extract(("a.pdf", pdf), ("b.pdf", pdf))

    assert exc.value.status_code == 413


async def test_pdf_page_limit_is_413(monkeypatch):
    monkeypatch.setattr(attachments, "MAX_PDF_PAGES", 1)

    with pytest.raises(AttachmentError) as exc:
        await _extract(("largo.pdf", make_pdf("uno", "dos")))

    assert exc.value.status_code == 413


async def test_docx_uncompressed_size_limit_is_413(monkeypatch):
    monkeypatch.setattr(attachments, "MAX_DOCX_UNCOMPRESSED_BYTES", 10)

    with pytest.raises(AttachmentError) as exc:
        await _extract(("bomba.docx", make_docx(["texto"])))

    assert exc.value.status_code == 413


def test_attachment_errors_are_http_exceptions():
    assert issubclass(AttachmentError, HTTPException)
