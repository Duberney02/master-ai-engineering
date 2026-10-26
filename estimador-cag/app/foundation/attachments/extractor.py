"""Extracción local de texto de adjuntos PDF y Word (.docx).

Los documentos se leen en el propio servicio (pypdf y python-docx) y su texto se incorpora a la
transcripción entre un separador `--- attachment: <nombre> ---` y un cierre `--- end attachment ---`;
los archivos nunca se envían al proveedor del LLM. El texto resultante pasa por los mismos guardrails y
límites que una transcripción pegada. Los errores son `HTTPException` con mensajes saneados que no
incluyen contenido del archivo.

El texto de cada adjunto se recorta a `MAX_ATTACHMENT_CHARS`. Un documento ilegible (corrupto, cifrado,
con todas sus páginas ilegibles) es un error 422; uno que se abre pero no contiene texto (por ejemplo,
un PDF escaneado) se omite sin error.

La extracción es síncrona y puede tardar, por lo que se ejecuta fuera del bucle de eventos.
"""

import asyncio
import io
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass

import structlog
from fastapi import HTTPException

from app.config import get_settings

logger = structlog.get_logger(__name__)

MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 200
# Tope del tamaño descomprimido de un .docx (defensa frente a «zip bombs»).
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_FILENAME_CHARS = 100

_SEPARATOR = "--- attachment: {name} ---"
_END_SEPARATOR = "--- end attachment ---"
_UNSAFE_NAME_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f  <>]")
_DASH_RUNS = re.compile(r"-{3,}")
_BLANK_LINES = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t]+")


class AttachmentError(HTTPException):
    """Adjunto rechazado; `detail` es un mensaje en español sin datos del archivo."""


@dataclass(frozen=True)
class ExtractedAttachment:
    filename: str
    text: str

    @property
    def block(self) -> str:
        return f"{_SEPARATOR.format(name=self.filename)}\n{self.text}\n{_END_SEPARATOR}"


def safe_filename(name: str | None) -> str:
    """Nombre base en una sola línea: sin rutas, caracteres de control ni series `---` que puedan
    imitar un separador."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = _UNSAFE_NAME_CHARS.sub(" ", base)
    base = _DASH_RUNS.sub("-", _SPACES.sub(" ", base)).strip()
    if len(base) > MAX_FILENAME_CHARS:
        stem, dot, ext = base.rpartition(".")
        keeps_extension = dot and len(ext) < 10
        base = (stem[: MAX_FILENAME_CHARS - len(ext) - 1] + dot + ext) if keeps_extension else base[:MAX_FILENAME_CHARS]
    return base or "attachment"


def _normalize(text: str) -> str:
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = (_SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    if b"%PDF-" not in data[:1024]:
        raise AttachmentError(415, "El contenido del archivo no corresponde a un PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise AttachmentError(422, "El PDF está protegido con contraseña.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise AttachmentError(413, f"El PDF supera el máximo de {MAX_PDF_PAGES} páginas.")
        pages = []
        failed_pages = 0
        for number, page in enumerate(reader.pages, start=1):
            try:
                pages.append(page.extract_text() or "")
            except Exception as exc:
                failed_pages += 1
                logger.warning("pdf_page_extract_failed", page=number, error_type=type(exc).__name__)
        if failed_pages and not pages:
            raise AttachmentError(422, "No se pudo leer el PDF.")
        return "\n\n".join(pages)
    except AttachmentError:
        raise
    except Exception as exc:
        logger.warning("pdf_extraction_failed", error_type=type(exc).__name__)
        raise AttachmentError(422, "No se pudo leer el PDF.") from None


def _extract_docx(data: bytes) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise AttachmentError(415, "El contenido del archivo no corresponde a un documento Word (.docx).")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if "word/document.xml" not in archive.namelist():
                raise AttachmentError(415, "El contenido del archivo no corresponde a un documento Word (.docx).")
            if sum(info.file_size for info in archive.infolist()) > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise AttachmentError(413, "El documento Word es demasiado grande.")
        blocks: list[str] = []
        for item in Document(io.BytesIO(data)).iter_inner_content():
            if isinstance(item, Paragraph):
                blocks.append(item.text)
            elif isinstance(item, Table):
                blocks.extend(" | ".join(cell.text for cell in row.cells) for row in item.rows)
        return "\n".join(blocks)
    except AttachmentError:
        raise
    except Exception as exc:
        logger.warning("docx_extraction_failed", error_type=type(exc).__name__)
        raise AttachmentError(422, "No se pudo leer el documento Word.") from None


_EXTRACTORS: dict[str, Callable[[bytes], str]] = {".pdf": _extract_pdf, ".docx": _extract_docx}
SUPPORTED_EXTENSIONS = tuple(_EXTRACTORS)


def _extract(filename: str, data: bytes, max_chars: int) -> ExtractedAttachment | None:
    extension = "." + filename.rpartition(".")[2].lower() if "." in filename else ""
    extractor = _EXTRACTORS.get(extension)
    if extractor is None:
        raise AttachmentError(415, "Solo se admiten adjuntos PDF (.pdf) y Word (.docx).")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise AttachmentError(413, f"Cada adjunto puede pesar como máximo {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB.")
    text = _normalize(extractor(data))
    if not text:
        # Se abrió correctamente pero no hay texto (¿escaneado o vacío?): no es un error, se omite.
        logger.info("attachment_without_text")
        return None
    if len(text) > max_chars:
        logger.info("attachment_truncated", original_chars=len(text), kept_chars=max_chars)
        text = text[:max_chars]
    return ExtractedAttachment(filename=filename, text=text)


async def extract_attachments(
    files: list[tuple[str | None, bytes]], *, max_chars: int | None = None
) -> list[ExtractedAttachment]:
    """Extrae el texto de cada `(nombre, contenido)` en orden, sin bloquear el bucle de eventos.

    Recorta cada texto a `max_chars` (por defecto `MAX_ATTACHMENT_CHARS`) y omite los adjuntos sin texto."""
    if len(files) > MAX_ATTACHMENTS:
        raise AttachmentError(413, f"Se admiten como máximo {MAX_ATTACHMENTS} adjuntos por solicitud.")
    limit = get_settings().max_attachment_chars if max_chars is None else max_chars
    extracted = []
    for name, data in files:
        attachment = await asyncio.to_thread(_extract, safe_filename(name), data, limit)
        if attachment is not None:
            extracted.append(attachment)
    return extracted


def combine_text(transcript: str, attachments: list[ExtractedAttachment]) -> str:
    """Transcripción seguida de cada adjunto precedido de su separador, en el orden recibido."""
    parts = [transcript.strip(), *(attachment.block for attachment in attachments)]
    return "\n\n".join(part for part in parts if part)
