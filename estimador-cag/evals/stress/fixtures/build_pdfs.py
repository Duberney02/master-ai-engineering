"""Genera PDFs sintéticos deterministas de tamaño aproximado 5, 20, 50 y 100 KB para el stress test.

    python -m evals.stress.fixtures.build_pdfs [--output-dir DIR] [--sizes 5,20,50,100]

Los archivos no se versionan (`fixtures/generated/` está en `.gitignore`): el runner los regenera en cada
ejecución. El contenido sale de un generador con semilla fija, sin compresión de flujos para que el tamaño
del archivo sea proporcional al texto, y con la fecha de creación fijada: dos ejecuciones producen los
mismos bytes. Cada PDF lleva tres hechos identificables (inicio, mitad y final del documento) que sirven
para comprobar qué parte del adjunto sobrevive. Tamaño 0 significa «sin adjunto» y no genera archivo.

El manifiesto (`manifest.json`) registra por archivo el tamaño real, los caracteres que extrae el extractor
de la aplicación (`app.foundation.attachments.extractor`) y su cercanía al límite de texto de la API
(`MAX_DESCRIPTION_CHARS`, 80 000 caracteres entre transcripción y adjuntos). Superarlo no trunca: la API
responde 413.
"""

import argparse
import asyncio
import json
import random
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF

from app.domain.schemas import MAX_DESCRIPTION_CHARS
from app.foundation.attachments.extractor import extract_attachments

DEFAULT_SIZES_KB = (5, 20, 50, 100)
GENERATED_DIR = Path(__file__).parent / "generated"
SEED = 20261014
_FIXED_DATE = datetime(2026, 1, 1, tzinfo=timezone.utc)

# Hechos identificables (distintos de los de los escenarios) y la parte del documento donde se colocan.
FACTS = {
    "head": ("Veridian", "El sistema debe integrarse con la pasarela de pagos Veridian desde la primera versión."),
    "middle": ("MID-2291", "El plazo contractual máximo es de catorce semanas según la cláusula MID-2291."),
    "tail": ("FIN-8830", "La penalización por retraso es del 2,5 por ciento semanal según el anexo FIN-8830."),
}

_SUBJECTS = ("El módulo", "El equipo", "La plataforma", "El cliente", "El servicio", "La integración", "El proceso")
_VERBS = (
    "deberá validar",
    "registrará",
    "notificará",
    "sincronizará",
    "documentará",
    "auditará",
    "priorizará",
    "conciliará",
)
_OBJECTS = (
    "los pedidos pendientes",
    "las facturas emitidas",
    "los datos de los usuarios",
    "los informes mensuales",
    "las incidencias abiertas",
    "el inventario disponible",
    "los permisos de acceso",
    "las tareas programadas",
)
_CONDITIONS = (
    "antes del cierre de cada jornada",
    "con un registro completo de cambios",
    "cumpliendo los requisitos de seguridad",
    "sin interrumpir el servicio",
    "según el calendario acordado",
    "con la aprobación del responsable",
)


@dataclass(frozen=True)
class AttachmentFixture:
    size_kb_target: int
    path: str
    size_bytes: int
    extracted_chars: int
    facts_extracted: dict[str, bool]
    chars_to_description_limit: int  # margen hasta MAX_DESCRIPTION_CHARS (antes de sumar la transcripción)

    @property
    def over_limit(self) -> bool:
        return self.chars_to_description_limit < 0


def _paragraph(rng: random.Random) -> str:
    sentences = (
        f"{rng.choice(_SUBJECTS)} {rng.choice(_VERBS)} {rng.choice(_OBJECTS)} {rng.choice(_CONDITIONS)}."
        for _ in range(4)
    )
    return " ".join(sentences)


def _render(paragraphs: Sequence[str], title: str) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_compression(False)
    pdf.set_creation_date(_FIXED_DATE)
    pdf.set_title(title)
    pdf.set_author("estimador-cag stress test")
    pdf.set_producer("fpdf2")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=10)
    for paragraph in paragraphs:
        pdf.multi_cell(0, 5, paragraph, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    return bytes(pdf.output())


def _document(count: int, rng_seed: int) -> list[str]:
    """`count` párrafos deterministas con los tres hechos en posiciones fijas del documento."""
    rng = random.Random(rng_seed)
    paragraphs = [_paragraph(rng) for _ in range(max(count, 3))]
    paragraphs[0] = f"{FACTS['head'][1]} {paragraphs[0]}"
    paragraphs[len(paragraphs) // 2] = f"{FACTS['middle'][1]} {paragraphs[len(paragraphs) // 2]}"
    paragraphs[-1] = f"{FACTS['tail'][1]} {paragraphs[-1]}"
    return paragraphs


def build_pdf(size_kb: int) -> bytes:
    """PDF de al menos `size_kb` KB y el menor posible (búsqueda binaria sobre el número de párrafos)."""
    target = size_kb * 1024
    title = f"Anexo tecnico sintetico {size_kb} KB"
    low, high = 3, 4
    while len(_render(_document(high, SEED + size_kb), title)) < target:
        low, high = high, high * 2
    while low < high:
        mid = (low + high) // 2
        if len(_render(_document(mid, SEED + size_kb), title)) >= target:
            high = mid
        else:
            low = mid + 1
    return _render(_document(low, SEED + size_kb), title)


def _extract(data: bytes, name: str):
    return asyncio.run(extract_attachments([(name, data)]))[0]


def build_pdfs(
    output_dir: Path = GENERATED_DIR, sizes_kb: Sequence[int] = DEFAULT_SIZES_KB
) -> dict[int, AttachmentFixture]:
    """Regenera los PDFs de `sizes_kb` (los tamaños 0 se ignoran) y escribe `manifest.json`."""
    output_dir.mkdir(parents=True, exist_ok=True)
    fixtures: dict[int, AttachmentFixture] = {}
    for size_kb in sorted({s for s in sizes_kb if s > 0}):
        data = build_pdf(size_kb)
        path = output_dir / f"adjunto_{size_kb}kb.pdf"
        path.write_bytes(data)
        text = _extract(data, path.name).text
        fixtures[size_kb] = AttachmentFixture(
            size_kb_target=size_kb,
            path=str(path),
            size_bytes=len(data),
            extracted_chars=len(text),
            facts_extracted={part: token in text for part, (token, _) in FACTS.items()},
            chars_to_description_limit=MAX_DESCRIPTION_CHARS - len(text),
        )
    manifest = {
        "seed": SEED,
        "max_description_chars": MAX_DESCRIPTION_CHARS,
        "facts": {part: token for part, (token, _) in FACTS.items()},
        "attachments": {str(kb): asdict(f) for kb, f in fixtures.items()},
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return fixtures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.stress.fixtures.build_pdfs", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--output-dir", type=Path, default=GENERATED_DIR)
    parser.add_argument("--sizes", default=",".join(map(str, DEFAULT_SIZES_KB)), help="KB separados por comas.")
    args = parser.parse_args(argv)
    try:
        sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    except ValueError:
        print("--sizes debe ser una lista de enteros", file=sys.stderr)
        return 2
    for kb, fixture in build_pdfs(args.output_dir, sizes).items():
        print(
            f"{kb:>4} KB -> {fixture.size_bytes:>7} bytes · {fixture.extracted_chars:>6} caracteres extraídos "
            f"· margen al límite {fixture.chars_to_description_limit}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
