"""Clientes SSE síncronos del estimador; independientes de Streamlit y de claves de proveedores.

- `request_structured_estimation`: contrato estructurado (`/api/v1/estimate/stream`), que emite
  el resultado validado completo (`result`), sus métricas (`metadata`) y `done`.
- `stream_estimation`: flujo de transcripción (`/api/v1/transcription/estimate/stream`).
"""

import json
from collections.abc import Iterable, Iterator

import httpx
from pydantic import ValidationError

from app.schemas import EstimationRequest, EstimationResult, EstimationStreamMetadata

# Versiones que ofrece el formulario; el servidor valida y rechaza con 422 las que no tenga.
PROMPT_VERSIONS = ("v3", "v1", "v2")
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


def _guardrail_message(response: httpx.Response) -> str:
    """Mensaje del 400 de guardrails; el servidor lo redacta sin datos del usuario."""
    try:
        message = response.json().get("message")
    except (ValueError, AttributeError):
        message = None
    return message[:300] if isinstance(message, str) and message else "La API rechazó la solicitud (HTTP 400)."


def _events(url: str, body: dict, params: dict | None = None) -> Iterator[tuple[str, dict]]:
    """Cede los eventos SSE de la API traduciendo los fallos HTTP a `EstimationStreamError`."""
    try:
        with httpx.stream(
            "POST", url, params=params, json=body,
            headers={"Accept": "text/event-stream"}, timeout=_TIMEOUT,
        ) as response:
            if response.status_code == 400:
                response.read()
                raise EstimationStreamError(_guardrail_message(response))
            response.raise_for_status()
            yield from parse_sse(response.iter_lines())
    except httpx.HTTPStatusError as exc:
        raise EstimationStreamError(f"La API rechazó la solicitud (HTTP {exc.response.status_code}).") from None
    except httpx.HTTPError:
        raise EstimationStreamError("No se pudo conectar con la API del estimador.") from None


def _stream(url: str, body: dict, metrics: dict, params: dict | None = None) -> Iterator[str]:
    """Cede el texto de cada `token`; solo con `metadata` y `done` rellena `metrics`."""
    metrics.clear()
    completed, metadata = False, None
    for event, value in _events(url, body, params):
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
    if not completed or metadata is None:
        raise EstimationStreamError("La conexión terminó antes de completar la estimación.")
    metrics.update(metadata)


def request_structured_estimation(
    request: EstimationRequest, base_url: str, prompt_version: str = PROMPT_VERSIONS[0],
) -> tuple[EstimationResult, EstimationStreamMetadata]:
    """Pide una estimación y devuelve el resultado validado con las métricas de la llamada.

    Un resultado solo existe completo: ante cualquier fallo (HTTP, `error`, corte sin `done`,
    datos fuera de contrato) se lanza `EstimationStreamError` con un mensaje saneado.
    """
    result = metadata = None
    completed = False
    for event, value in _events(
        base_url.rstrip("/") + "/api/v1/estimate/stream", request.model_dump(mode="json"),
        {"prompt_version": prompt_version},
    ):
        try:
            if event == "result":
                result = EstimationResult.model_validate(value)
            elif event == "metadata":
                metadata = EstimationStreamMetadata.model_validate(value)
        except ValidationError:
            raise EstimationStreamError("La API devolvió datos inválidos.") from None
        if event == "error":
            raise EstimationStreamError("La API no pudo completar la estimación. Intenta de nuevo.")
        if event == "done":
            completed = True
            break
    if not completed or result is None or metadata is None:
        raise EstimationStreamError("La conexión terminó antes de completar la estimación.")
    return result, metadata


def stream_estimation(transcription: str, base_url: str, metrics: dict) -> Iterator[str]:
    yield from _stream(
        base_url.rstrip("/") + "/api/v1/transcription/estimate/stream",
        {"transcription": transcription}, metrics,
    )
