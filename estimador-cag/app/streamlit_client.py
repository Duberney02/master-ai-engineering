"""Clientes SSE síncronos del estimador; independientes de Streamlit y de claves de proveedores.

- `stream_structured_estimation`: contrato estructurado (`/api/v1/estimate/stream`).
- `stream_estimation`: flujo de transcripción (`/api/v1/transcription/estimate/stream`).
"""

import json
from collections.abc import Iterable, Iterator

import httpx
from pydantic import ValidationError

from app.schemas import EstimationRequest, EstimationStreamMetadata

# Versiones que ofrece el formulario; el servidor valida y rechaza con 422 las que no tenga.
PROMPT_VERSIONS = ("v1", "v2")
_TIMEOUT = httpx.Timeout(600, connect=10)


class EstimationStreamError(Exception):
    pass


def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict]]:
    event, data = "message", []
    for line in lines:
        if not line:
            if data:
                try:
                    value = json.loads("\n".join(data))
                except ValueError:
                    raise EstimationStreamError("La API envió un evento inválido.") from None
                if not isinstance(value, dict):
                    raise EstimationStreamError("La API envió un evento inválido.")
                yield event, value
            event, data = "message", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[6:] if line.startswith("data: ") else line[5:])


def _stream(url: str, body: dict, metrics: dict, params: dict | None = None) -> Iterator[str]:
    """Cede el texto de cada `token`; solo con `metadata` y `done` rellena `metrics`."""
    metrics.clear()
    completed, metadata = False, None
    try:
        with httpx.stream(
            "POST", url, params=params, json=body,
            headers={"Accept": "text/event-stream"}, timeout=_TIMEOUT,
        ) as response:
            response.raise_for_status()
            for event, value in parse_sse(response.iter_lines()):
                if event == "token":
                    text = value.get("text")
                    if not isinstance(text, str):
                        raise EstimationStreamError("La API envió texto inválido.")
                    yield text
                elif event == "metadata":
                    metadata = value
                elif event == "error":
                    raise EstimationStreamError("La API no pudo completar la estimación. Intenta de nuevo.")
                elif event == "done":
                    completed = True
                    break
    except httpx.HTTPStatusError as exc:
        raise EstimationStreamError(f"La API rechazó la solicitud (HTTP {exc.response.status_code}).") from None
    except httpx.HTTPError:
        raise EstimationStreamError("No se pudo conectar con la API del estimador.") from None
    if not completed or metadata is None:
        raise EstimationStreamError("La conexión terminó antes de completar la estimación.")
    metrics.update(metadata)


def stream_structured_estimation(
    request: EstimationRequest, base_url: str, metrics: dict,
    prompt_version: str = PROMPT_VERSIONS[0],
) -> Iterator[str]:
    """Stream de una solicitud ya validada; `metrics` queda con un `EstimationStreamMetadata`."""
    raw: dict = {}
    metrics.clear()
    yield from _stream(
        base_url.rstrip("/") + "/api/v1/estimate/stream", request.model_dump(mode="json"),
        raw, params={"prompt_version": prompt_version},
    )
    try:
        metadata = EstimationStreamMetadata.model_validate(raw)
    except ValidationError:
        raise EstimationStreamError("La API devolvió métricas inválidas.") from None
    metrics.update(metadata.model_dump())


def stream_estimation(transcription: str, base_url: str, metrics: dict) -> Iterator[str]:
    yield from _stream(
        base_url.rstrip("/") + "/api/v1/transcription/estimate/stream",
        {"transcription": transcription}, metrics,
    )
