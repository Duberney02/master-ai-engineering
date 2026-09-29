"""Cliente SSE síncrono; independiente de Streamlit y de claves de proveedores."""

import json
from collections.abc import Iterable, Iterator

import httpx


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


def stream_estimation(transcription: str, base_url: str, metrics: dict) -> Iterator[str]:
    metrics.clear()
    completed, metadata = False, None
    try:
        with httpx.stream(
            "POST", base_url.rstrip("/") + "/api/v1/estimate/stream",
            json={"transcription": transcription}, headers={"Accept": "text/event-stream"},
            timeout=httpx.Timeout(600, connect=10),
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
