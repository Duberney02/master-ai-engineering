"""Dobles de prueba del pipeline RAG: embedder determinista y clientes de LLM falsos."""

import hashlib
import math
from types import SimpleNamespace

from app.generation.rag.schemas import Budget, BudgetComponent, Chunk, ClientMetadata, EmbeddedChunk

DIMENSIONS = 32


def vector_for(text: str, dimensions: int = DIMENSIONS) -> list[float]:
    """Bolsa de palabras con hashing: textos que comparten palabras tienen coseno alto."""
    vector = [0.0] * dimensions
    for word in text.lower().split():
        digest = hashlib.sha256(word.strip(".,:;[]|").encode()).digest()
        vector[digest[0] % dimensions] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class FakeEmbedder:
    """Mismo contrato que `OpenAIEmbedder`, sin red."""

    def __init__(self, dimensions: int = DIMENSIONS) -> None:
        self.dimensions = dimensions
        self.text_calls: list[list[str]] = []
        self.chunk_calls = 0

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed_texts([text]))[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.text_calls.append(list(texts))
        return [vector_for(text, self.dimensions) for text in texts]

    async def embed_many(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        self.chunk_calls += 1
        return [
            EmbeddedChunk(**chunk.model_dump(), embedding=vector_for(chunk.text, self.dimensions)) for chunk in chunks
        ]


def make_budget(budget_id: str = "B-1", descriptions: list[str] | None = None, sector: str = "finance") -> Budget:
    descriptions = descriptions or ["First sentence about OAuth. Second sentence about tokens. Third about limits."]
    return Budget(
        budget_id=budget_id,
        client_metadata=ClientMetadata(name="Acme", sector=sector, country="ES"),
        project_summary="Mobile banking API",
        main_technology="ruby_on_rails",
        year=2024,
        total_estimated_hours=100,
        components=[
            BudgetComponent(
                component_id=f"C-{i}",
                name=f"Component {i}",
                description=text,
                tech_stack=["postgresql"],
                estimated_hours=10 + i,
                complexity="medium",
            )
            for i, text in enumerate(descriptions, start=1)
        ],
    )


class FakeOpenAIClient:
    """`AsyncOpenAI` mínimo: `beta.chat.completions.parse` devuelve proposiciones fijas (o falla)."""

    def __init__(self, propositions: list[str] | None = None, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._propositions = propositions
        self._error = error
        self.beta = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=self._parse)))

    async def _parse(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        parsed = SimpleNamespace(propositions=self._propositions or [])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
            usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=100),
        )


class FakeAnthropicClient:
    """`AsyncAnthropic` mínimo: `messages.create` devuelve un contexto fijo con uso de caché."""

    def __init__(self, context: str = "Situates the component in the budget.", error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self._context = context
        self._error = error
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        first = len(self.calls) == 1
        usage = SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=2000 if first else 0,
            cache_read_input_tokens=0 if first else 2000,
        )
        return SimpleNamespace(content=[SimpleNamespace(text=self._context)], usage=usage)
