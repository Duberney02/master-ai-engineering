#!/usr/bin/env python3
"""Ingesta las colecciones nuevas del multi-índice (Sesión 10): transcripciones y documentación técnica.

El corpus de presupuestos se ingesta por HTTP con `scripts/ingest_corpus.py`; este script siembra las DOS colecciones
nuevas (`transcript_chunks` y `technical_doc_chunks`) directamente con la sesión async del proyecto y el mismo embedder.
Un chunk por segmento de transcripción y por sección de documento, cada uno con el esquema de metadatos de su colección
(transcripciones: `transcript_id`, participantes y `meeting_date`; documentación: `doc_id` y `version`), de modo que
el *routing*, los filtros duros y el *decay* temporal den resultados con sentido.

Idempotente: cada documento se identifica por `source_path` (`<fichero>::<id>`) y se omite si ya está ingestado, así que
repetirlo no duplica nada. Para retirarlo::

    DELETE FROM documents WHERE document_type IN ('meeting_transcript', 'technical_doc');

Se ejecuta dentro de Docker, con el stack levantado y `OPENAI_API_KEY` (embeddings reales)::

    docker compose run --rm estimador-cag python scripts/build_multi_index_corpus.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from s08_common import require_embedder  # importa antes que `app`: pone la raíz del servicio en sys.path
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.foundation.persistence.database import SessionLocal
from app.foundation.persistence.models import EMBEDDING_DIMENSIONS, Document
from app.generation.rag.chunking.base import count_tokens
from app.generation.rag.retrieval.collections import Collection, spec_for
from app.generation.rag.schemas import Chunk

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS_PATH = ROOT / "data" / "transcripts_sample.json"
DOCS_PATH = ROOT / "data" / "technical_docs_sample.json"


def _chunk(*, chunk_id: str, header: str, body: str, metadata: dict) -> Chunk:
    """Un chunk embebible: una cabecera contextual breve más el cuerpo."""
    text = f"{header}\n{body}".strip()
    return Chunk(chunk_id=chunk_id, text=text, metadata=metadata, token_count=count_tokens(text))


def transcript_chunks(transcript: dict) -> list[Chunk]:
    """Un chunk por segmento de la transcripción, con su fecha de reunión y participantes."""
    transcript_id = transcript["transcript_id"]
    header = f"Meeting: {transcript['project']} ({transcript['meeting_date']})"
    return [
        _chunk(
            chunk_id=f"{transcript_id}::{segment['segment_id']}",
            header=f"{header} — topic: {segment['topic']}",
            body=segment["text"],
            metadata={
                "transcript_id": transcript_id,
                "segment_id": segment["segment_id"],
                "project": transcript["project"],
                "meeting_date": transcript["meeting_date"],
                "speakers": segment.get("speakers", []),
                "topic": segment["topic"],
            },
        )
        for segment in transcript["segments"]
    ]


def doc_chunks(doc: dict) -> list[Chunk]:
    """Un chunk por sección del documento, con su versión."""
    doc_id = doc["doc_id"]
    header = f"Doc: {doc['title']} (version {doc['version']})"
    return [
        _chunk(
            chunk_id=f"{doc_id}::{section['section_id']}",
            header=f"{header} — {section['heading']}",
            body=section["text"],
            metadata={
                "doc_id": doc_id,
                "section_id": section["section_id"],
                "heading": section["heading"],
                "version": doc["version"],
                "component": doc.get("component", "unknown"),
            },
        )
        for section in doc["sections"]
    ]


@dataclass(frozen=True)
class CollectionPlan:
    label: str
    source_file: str
    document_type: str
    collection: Collection
    id_key: str
    build_chunks: Callable[[dict], list[Chunk]]


PLANS = (
    CollectionPlan(
        label="Transcripciones",
        source_file="data/transcripts_sample.json",
        document_type="meeting_transcript",
        collection=Collection.TRANSCRIPT,
        id_key="transcript_id",
        build_chunks=transcript_chunks,
    ),
    CollectionPlan(
        label="Documentación técnica",
        source_file="data/technical_docs_sample.json",
        document_type="technical_doc",
        collection=Collection.TECHNICAL_DOC,
        id_key="doc_id",
        build_chunks=doc_chunks,
    ),
)


async def _already_ingested(session: AsyncSession, source_path: str) -> bool:
    found = await session.execute(select(Document.id).where(Document.source_path == source_path))
    return found.scalar_one_or_none() is not None


async def ingest_collection(
    plan: CollectionPlan, items: list[dict], *, session_factory: Callable[[], AsyncSession], embedder
) -> tuple[int, int]:
    """Ingesta los documentos de una colección que aún no están; devuelve `(creados, omitidos)`.

    Cada documento se confirma en su propia transacción (documento y chunks juntos o nada). Si otra ejecución gana la
    carrera por el mismo `source_path` (índice único), el documento cuenta como omitido.
    """
    spec = spec_for(plan.collection)
    created = skipped = 0
    for item in items:
        document_key = item[plan.id_key]
        source_path = f"{plan.source_file}::{document_key}"
        async with session_factory() as session:
            if await _already_ingested(session, source_path):
                skipped += 1
                continue

        embedded = await embedder.embed_many(plan.build_chunks(item))
        if any(len(chunk.embedding) != EMBEDDING_DIMENSIONS for chunk in embedded):
            raise ValueError(f"el embedder devolvió vectores que no son de {EMBEDDING_DIMENSIONS} dimensiones")

        async with session_factory() as session:
            try:
                document = Document(
                    source_path=source_path,
                    document_type=plan.document_type,
                    metadata_={"source_id": document_key},
                )
                session.add(document)
                await session.flush()
                session.add_all(
                    spec.model(
                        document_id=document.id,
                        chunk_type=spec.chunk_type,
                        content=chunk.text,
                        embedding=chunk.embedding,
                        metadata_={**chunk.metadata, "chunk_id": chunk.chunk_id, "token_count": chunk.token_count},
                    )
                    for chunk in embedded
                )
                await session.commit()
            except IntegrityError:
                await session.rollback()
                skipped += 1
                continue
        created += 1
    return created, skipped


async def main() -> int:
    embedder = require_embedder()
    for plan in PLANS:
        items = json.loads((ROOT / plan.source_file).read_text(encoding="utf-8"))
        created, skipped = await ingest_collection(plan, items, session_factory=SessionLocal, embedder=embedder)
        print(f"{plan.label}: {len(items)} documentos — {created} ingestados, {skipped} ya presentes.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
