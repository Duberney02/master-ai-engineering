"""Registro de estrategias de chunking: nombre → fábrica, y cuáles son gratuitas o de pago.

Las de pago (llaman a un LLM o a embeddings durante el chunking) son opt-in: nunca se ejecutan salvo que se
pidan por nombre. Construir un chunker no hace llamadas a ninguna API.
"""

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from app.config import Settings
from app.generation.rag.chunking.base import Chunker
from app.generation.rag.chunking.strategies import (
    ContextualRetrievalChunker,
    FixedSizeChunker,
    HierarchicalChunker,
    PropositionalChunker,
    RecursiveChunker,
    SemanticChunker,
    SentenceWindowChunker,
)
from app.generation.rag.chunking.structural import JSONStructuralChunker
from app.generation.rag.embedding.embedder import OpenAIEmbedder

FREE_STRATEGIES = ("structural", "fixed_size", "recursive", "sentence_window", "hierarchical")
PAID_STRATEGIES = ("semantic", "propositional", "contextual_retrieval")
ALL_STRATEGIES = (*FREE_STRATEGIES, *PAID_STRATEGIES)

# Estrategias que necesitan una clave de proveedor y de cuál.
REQUIRED_KEYS = {
    "semantic": "OPENAI_API_KEY",
    "propositional": "OPENAI_API_KEY",
    "contextual_retrieval": "ANTHROPIC_API_KEY",
}


class UnknownStrategyError(KeyError):
    """El nombre no corresponde a ninguna estrategia registrada."""


class StrategyUnavailableError(RuntimeError):
    """La estrategia no puede construirse: falta la clave del proveedor o el modelo configurado no encaja."""

    def __init__(self, strategy: str, reason: str) -> None:
        super().__init__(reason)
        self.strategy = strategy
        self.reason = reason


def build_chunkers(names: list[str], settings: Settings, embedder: OpenAIEmbedder) -> list[Chunker]:
    """Instancia los chunkers pedidos. No se ejecuta ninguna llamada a una API."""
    unknown = [name for name in names if name not in ALL_STRATEGIES]
    if unknown:
        raise UnknownStrategyError(unknown[0])
    return [_build(name, settings, embedder) for name in dict.fromkeys(names)]


def _build(name: str, settings: Settings, embedder: OpenAIEmbedder) -> Chunker:
    key_name = REQUIRED_KEYS.get(name)
    if key_name == "OPENAI_API_KEY" and not settings.openai_api_key:
        raise StrategyUnavailableError(name, f"La estrategia '{name}' requiere OPENAI_API_KEY.")
    if key_name == "ANTHROPIC_API_KEY" and not settings.anthropic_api_key:
        raise StrategyUnavailableError(name, f"La estrategia '{name}' requiere ANTHROPIC_API_KEY.")
    match name:
        case "structural":
            return JSONStructuralChunker()
        case "fixed_size":
            return FixedSizeChunker()
        case "recursive":
            return RecursiveChunker()
        case "sentence_window":
            return SentenceWindowChunker()
        case "hierarchical":
            return HierarchicalChunker()
        case "semantic":
            return SemanticChunker(embedder)
        case "propositional":
            model = settings.propositional_chunker_model
            if model.startswith("claude"):
                raise StrategyUnavailableError(name, f"La estrategia '{name}' requiere un modelo de OpenAI ({model}).")
            client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout, max_retries=2)
            return PropositionalChunker(client, model, settings)
        case _:
            model = settings.contextual_chunker_model
            if not model.startswith("claude"):
                raise StrategyUnavailableError(
                    name, f"La estrategia '{name}' requiere un modelo de Anthropic ({model})."
                )
            client = AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=settings.llm_timeout, max_retries=2)
            return ContextualRetrievalChunker(client, model, settings)
