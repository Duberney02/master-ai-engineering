"""Contrato de un adaptador de proveedor.

Un adaptador solo traduce entre el SDK y los tipos normalizados, y convierte las
excepciones del SDK en `LLMError`. No reintenta, no hace fallback ni usa caché:
esa política vive en `app/llm/client.py`.
"""

from collections.abc import AsyncIterator
from typing import Any, Protocol

from app.llm.types import LLMRequest, ProviderCompletion, ProviderDelta, ProviderStreamEnd


class ProviderAdapter(Protocol):
    name: str

    def generation_params(self) -> dict[str, Any]:
        """Parámetros fijos del adaptador que afectan a la generación (entran en la clave de caché)."""
        ...

    async def complete(self, model: str, request: LLMRequest) -> ProviderCompletion: ...

    def stream(
        self, model: str, request: LLMRequest
    ) -> AsyncIterator[ProviderDelta | ProviderStreamEnd]:
        """Emite deltas de texto y, al final, exactamente un `ProviderStreamEnd`."""
        ...

    async def aclose(self) -> None: ...


def finish_reason_or_unknown(value: object) -> str:
    return value if isinstance(value, str) and value else "unknown"


def int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
