"""Extracción local de texto de adjuntos PDF y Word (.docx).

Los documentos se leen en el propio servicio (pypdf y python-docx) y su texto se incorpora a la
transcripción con un separador `--- attachment: <nombre> ---`; los archivos nunca se envían al
proveedor del LLM. El texto resultante pasa por los mismos guardrails y límites que una transcripción
pegada. Los errores son `HTTPException` con mensajes saneados que no incluyen contenido del archivo.

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

logger = structlog.get_logger(__name__)

MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 200
# Tope del tamaño descomprimido de un .docx (defensa frente a «zip bombs»).
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_FILENAME_CHARS = 100

_SEPARATOR = "--- attachment: {name} ---"
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
        return f"{_SEPARATOR.format(name=self.filename)}\n{self.text}"


def safe_filename(name: str | None) -> str:
    """Nombre base en una sola línea: sin rutas, caracteres de control ni series `---` que puedan
    imitar un separador."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = _UNSAFE_NAME_CHARS.sub(" ", base)
    base = _DASH_RUNS.sub("-", _SPACES.sub(" ", base)).strip()
    if len(base) > MAX_FILENAME_CHARS:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: MAX_FILENAME_CHARS - len(ext) - 1] + dot + ext) if dot and len(ext) < 10 else base[:MAX_FILENAME_CHARS]
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
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
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


def _extract(filename: str, data: bytes) -> ExtractedAttachment:
    extension = "." + filename.rpartition(".")[2].lower() if "." in filename else ""
    extractor = _EXTRACTORS.get(extension)
    if extractor is None:
        raise AttachmentError(415, "Solo se admiten adjuntos PDF (.pdf) y Word (.docx).")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise AttachmentError(413, f"Cada adjunto puede pesar como máximo {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB.")
    text = _normalize(extractor(data))
    if not text:
        raise AttachmentError(422, f"No se pudo extraer texto de «{filename}» (¿está escaneado o vacío?).")
    return ExtractedAttachment(filename=filename, text=text)


async def extract_attachments(files: list[tuple[str | None, bytes]]) -> list[ExtractedAttachment]:
    """Extrae el texto de cada `(nombre, contenido)` en orden, sin bloquear el bucle de eventos."""
    if len(files) > MAX_ATTACHMENTS:
        raise AttachmentError(413, f"Se admiten como máximo {MAX_ATTACHMENTS} adjuntos por solicitud.")
    extracted = []
    for name, data in files:
        extracted.append(await asyncio.to_thread(_extract, safe_filename(name), data))
    return extracted


def combine_text(transcript: str, attachments: list[ExtractedAttachment]) -> str:
    """Transcripción seguida de cada adjunto precedido de su separador, en el orden recibido."""
    parts = [transcript.strip(), *(attachment.block for attachment in attachments)]
    return "\n\n".join(part for part in parts if part)
