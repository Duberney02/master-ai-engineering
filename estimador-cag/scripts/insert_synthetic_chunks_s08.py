#!/usr/bin/env python3
"""Inserta chunks sintéticos para que el corpus sea lo bastante grande como para medir un índice vectorial.

Los vectores no se piden a ningún proveedor: cada uno es una mezcla convexa de embeddings REALES del corpus con un
ruido leve, renormalizada, de modo que conservan la geometría del espacio de embeddings. Se insertan por lotes bajo un
único documento (`document_type='synthetic_test'`, `chunk_type='synthetic'`), que se busca o se crea (idempotente)::

    docker compose run --rm estimador-cag python scripts/insert_synthetic_chunks_s08.py 30000

Limpieza: ``DELETE FROM documents WHERE document_type='synthetic_test';`` (o `sql_s08/99_revert_live_session.sql`).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

import numpy as np
from s08_common import Stopwatch, session_scope
from sqlalchemy import func, insert, select, text

# isort: split
from app.foundation.persistence.models import EMBEDDING_DIMENSIONS, Chunk, Document  # noqa: E402

SYNTHETIC_DOCUMENT_TYPE = "synthetic_test"
SYNTHETIC_CHUNK_TYPE = "synthetic"
SYNTHETIC_SOURCE = "synthetic://session-08"
BATCH_SIZE = 1000
NOISE = 0.05  # norma del ruido isotrópico añadido a cada mezcla
MIX = 3  # vectores reales que se mezclan en cada chunk sintético


async def _synthetic_document_id(session) -> int:
    found = await session.execute(select(Document.id).where(Document.source_path == SYNTHETIC_SOURCE))
    existing = found.scalar_one_or_none()
    if existing is not None:
        return existing
    document = Document(
        source_path=SYNTHETIC_SOURCE, document_type=SYNTHETIC_DOCUMENT_TYPE, metadata_={"synthetic": True}
    )
    session.add(document)
    await session.flush()
    return document.id


def mixed(base: np.ndarray, rng: np.random.Generator, size: int) -> tuple[list[list[float]], np.ndarray]:
    """Mezclas convexas de `MIX` vectores reales (pesos Dirichlet) más ruido leve, normalizadas a longitud 1.

    Una simple copia con ruido crearía clústeres casi idénticos (empates en el top-k y un grafo HNSW degenerado); la
    mezcla reparte los puntos de forma continua por el espacio que generan los embeddings reales.
    """
    picks = rng.integers(0, len(base), size=(size, MIX))
    weights = rng.dirichlet(np.ones(MIX), size=size).astype(np.float32)
    blended = np.einsum("nk,nkd->nd", weights, base[picks])
    blended += rng.normal(0.0, NOISE / np.sqrt(base.shape[1]), size=blended.shape).astype(np.float32)
    blended /= np.linalg.norm(blended, axis=1, keepdims=True)
    return blended.astype(np.float32).tolist(), picks[:, 0]


async def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inserta chunks sintéticos con embeddings derivados de los reales.")
    parser.add_argument("count", nargs="?", type=int, default=100, help="Chunks a insertar (por defecto 100).")
    count = parser.parse_args(argv).count
    if count < 1:
        sys.exit("ERROR: count debe ser ≥ 1.")

    rng = np.random.default_rng(8)
    async with session_scope() as session:
        base_rows = (
            await session.execute(
                select(Chunk.embedding).where(Chunk.embedding.is_not(None), Chunk.chunk_type != SYNTHETIC_CHUNK_TYPE)
            )
        ).scalars().all()
        if not base_rows:
            sys.exit("ERROR: no hay chunks reales con embedding; ingesta antes el corpus (`scripts/ingest_corpus.py`).")
        base = np.asarray(base_rows, dtype=np.float32)
        assert base.shape[1] == EMBEDDING_DIMENSIONS
        document_id = await _synthetic_document_id(session)
        await session.commit()

        inserted = 0
        with Stopwatch() as watch:
            while inserted < count:
                size = min(BATCH_SIZE, count - inserted)
                vectors, picks = mixed(base, rng, size)
                await session.execute(
                    insert(Chunk),
                    [
                        {
                            "document_id": document_id,
                            "chunk_type": SYNTHETIC_CHUNK_TYPE,
                            "content": f"Synthetic chunk {inserted + i + 1} (mezcla; base: chunk {int(picks[i])}).",
                            "embedding": vectors[i],
                            "metadata_": {"synthetic": True},
                        }
                        for i in range(size)
                    ],
                )
                await session.commit()
                inserted += size
                print(f"  {inserted}/{count}", end="\r", flush=True)

        # `ANALYZE` actualiza las estadísticas del planner; sin ellas puede ignorar el índice recién poblado.
        await session.execute(text("ANALYZE chunks"))
        total = (await session.execute(text("SELECT count(*) FROM chunks"))).scalar_one()
        synthetic = (
            await session.execute(
                select(func.count()).select_from(Chunk).where(Chunk.chunk_type == SYNTHETIC_CHUNK_TYPE)
            )
        ).scalar_one()
    print(f"Insertados {inserted} chunks en {watch.ms / 1000:.1f} s · sintéticos: {synthetic} · total: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
