"""Identificación de modelos y política de selección (primario, fallback, lista permitida).

Un modelo se identifica siempre por **proveedor + nombre** (`ModelRef`), de modo que
las credenciales se eligen según el proveedor real de cada modelo y no según un
proveedor global.
"""

from dataclasses import dataclass
from typing import Literal

from app.llm.errors import ModelSelectionError

Provider = Literal["openai", "anthropic"]
PROVIDERS: tuple[Provider, ...] = ("openai", "anthropic")

_OPENAI_PREFIXES = ("gpt-", "chatgpt-", "o1", "o3", "o4", "ft:gpt-")
_ANTHROPIC_PREFIXES = ("claude-",)


class ModelResolutionError(ValueError):
    """No se puede determinar el proveedor de un nombre de modelo."""


@dataclass(frozen=True, order=True)
class ModelRef:
    provider: Provider
    name: str

    def __str__(self) -> str:
        return f"{self.provider}/{self.name}"


def parse_model_ref(value: str) -> ModelRef:
    """`openai/gpt-4o` → explícito; `gpt-4o` / `claude-haiku-4-5` → proveedor inferido."""
    value = value.strip()
    if "/" in value:
        prefix, name = value.split("/", 1)
        if prefix in PROVIDERS and name:
            return ModelRef(provider=prefix, name=name)  # type: ignore[arg-type]
    lowered = value.lower()
    if lowered.startswith(_OPENAI_PREFIXES):
        return ModelRef(provider="openai", name=value)
    if lowered.startswith(_ANTHROPIC_PREFIXES):
        return ModelRef(provider="anthropic", name=value)
    raise ModelResolutionError(
        f"cannot determine the provider of '{value}'; use 'openai/<model>' or 'anthropic/<model>'"
    )


@dataclass(frozen=True)
class ModelRoute:
    """Candidatos en orden: el primero se intenta siempre antes que los siguientes."""

    candidates: tuple[ModelRef, ...]

    def __post_init__(self) -> None:
        if not self.candidates:
            raise ValueError("a route needs at least one model")

    @property
    def primary(self) -> ModelRef:
        return self.candidates[0]

    def describe(self) -> list[str]:
        return [str(c) for c in self.candidates]


@dataclass(frozen=True)
class ModelPolicy:
    """Reglas de selección de modelo por solicitud.

    - Sin `model`: primario y, si está configurado, el secundario.
    - Con `model` y `allow_fallback=False` (por defecto): **exactamente** ese modelo.
    - Con `model` y `allow_fallback=True`: ese modelo y después el secundario configurado.
    - `allowed` (si no está vacío) restringe los modelos que se pueden pedir explícitamente.
    """

    primary: ModelRef
    fallback: ModelRef | None
    allowed: frozenset[ModelRef]
    available_providers: frozenset[str]

    def route_for(self, requested: str | None, allow_fallback: bool = False) -> ModelRoute:
        if requested is None:
            return self._with_fallback(self.primary)
        try:
            ref = parse_model_ref(requested)
        except ModelResolutionError:
            raise ModelSelectionError(
                "Cannot determine the provider of the requested model; "
                "use 'openai/<model>' or 'anthropic/<model>'"
            ) from None
        if self.allowed and ref not in self.allowed:
            raise ModelSelectionError("Requested model is not allowed")
        if ref.provider not in self.available_providers:
            raise ModelSelectionError("The provider of the requested model is not configured")
        if allow_fallback:
            return self._with_fallback(ref)
        return ModelRoute((ref,))

    def _with_fallback(self, first: ModelRef) -> ModelRoute:
        if self.fallback is None or self.fallback == first:
            return ModelRoute((first,))
        return ModelRoute((first, self.fallback))
