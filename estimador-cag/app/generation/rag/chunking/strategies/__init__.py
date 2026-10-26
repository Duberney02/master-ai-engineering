"""Siete estrategias de chunking detrás de la interfaz `Chunker` (la estructural vive en `chunking/structural.py`)."""

from app.generation.rag.chunking.strategies.contextual_retrieval import ContextualRetrievalChunker
from app.generation.rag.chunking.strategies.fixed_size import FixedSizeChunker
from app.generation.rag.chunking.strategies.hierarchical import HierarchicalChunker
from app.generation.rag.chunking.strategies.propositional import PropositionalChunker
from app.generation.rag.chunking.strategies.recursive import RecursiveChunker
from app.generation.rag.chunking.strategies.semantic import SemanticChunker
from app.generation.rag.chunking.strategies.sentence_window import SentenceWindowChunker

__all__ = [
    "ContextualRetrievalChunker",
    "FixedSizeChunker",
    "HierarchicalChunker",
    "PropositionalChunker",
    "RecursiveChunker",
    "SemanticChunker",
    "SentenceWindowChunker",
]
