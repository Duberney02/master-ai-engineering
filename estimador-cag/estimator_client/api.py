"""Cliente síncrono de la API del estimador (Streamlit ejecuta scripts síncronos).

Distingue explícitamente:
- `ApiConnectionError`: la API no es accesible (conexión rechazada, DNS, timeout).
- `ApiValidationError`: 422, la solicitud no pasó la validación (antes del stream).
- `ApiServerError`: cualquier otro estado HTTP de error antes del stream.
- Dentro de un stream, `StreamOutcome.status`:
  `completed` (llegó `done`), `error` (llegó `error`) o `interrupted` (la conexión se
  cerró o expiró sin `done` ni `error`). Solo `completed` es una estimación válida.
"""

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from estimator_client.config import ClientSettings
from estimator_client.sse import SSEDecoder

STREAM_PATH = "/api/v1/estimate/stream"
ESTIMATE_PATH = "/api/v1/estimate"
CONTEXT_PATH = "/api/v1/context"


class ApiError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ApiConnectionError(ApiError):
    pass


class ApiValidationError(ApiError):
    def __init__(self, message: str, details: list[str]):
        super().__init__(message)
        self.details = details


class ApiServerError(ApiError):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


StreamStatus = Literal["pending", "completed", "error", "interrupted"]


@dataclass
class StreamOutcome:
    status: StreamStatus = "pending"
    text: str = ""
    extracted_requirements: str | None = None
    extraction_cache: str | None = None
    metadata: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    interruption_reason: str | None = None
    request_id: str | None = None
    events: list[str] = field(default_factory=list)

    @property
    def completed(self) -> bool:
        return self.status == "completed"


class EstimateStream:
    """Stream abierto (estado 200 confirmado). Consumir `text_chunks()` una vez."""

    def __init__(self, response: httpx.Response):
        self._response = response
        self.outcome = StreamOutcome(request_id=response.headers.get("x-request-id"))

    def text_chunks(self) -> Iterator[str]:
        """Emite el texto de la estimación a medida que llega; nunca lanza excepciones.
        El resultado final (completado, error o interrupción) queda en `outcome`."""
        outcome = self.outcome
        decoder = SSEDecoder()
        try:
            for chunk in self._response.iter_text():
                for event in decoder.feed(chunk):
                    outcome.events.append(event.event)
                    try:
                        data = json.loads(event.data) if event.data else {}
                    except ValueError:
                        outcome.status = "error"
                        outcome.error = {"code": "invalid_event", "message": "Evento SSE inválido"}
                        return
                    if event.event == "start":
                        outcome.request_id = data.get("request_id") or outcome.request_id
                    elif event.event == "extraction":
                        outcome.extracted_requirements = data.get("text")
                        outcome.extraction_cache = data.get("cache")
                    elif event.event == "delta":
                        text = data.get("text", "")
                        outcome.text += text
                        yield text
                    elif event.event == "metadata":
                        outcome.metadata = data
                    elif event.event == "done":
                        outcome.status = "completed"
                        return
                    elif event.event == "error":
                        outcome.status = "error"
                        outcome.error = data
                        return
            outcome.status = "interrupted"
            outcome.interruption_reason = "La conexión se cerró antes de completar la estimación"
        except httpx.TimeoutException:
            outcome.status = "interrupted"
            outcome.interruption_reason = "Tiempo de espera agotado mientras se recibía la respuesta"
        except httpx.HTTPError:
            outcome.status = "interrupted"
            outcome.interruption_reason = "Se perdió la conexión con la API durante la generación"
        finally:
            if outcome.status == "pending":
                outcome.status = "interrupted"
                outcome.interruption_reason = "Generación cancelada por el usuario"
            self._response.close()


class EstimatorApiClient:
    def __init__(self, http: httpx.Client):
        self._http = http

    @classmethod
    def from_settings(cls, settings: ClientSettings) -> "EstimatorApiClient":
        timeout = httpx.Timeout(settings.read_timeout, connect=settings.connect_timeout)
        return cls(httpx.Client(base_url=settings.base_url, timeout=timeout))

    @property
    def base_url(self) -> str:
        return str(self._http.base_url)

    def close(self) -> None:
        self._http.close()

    # --- endpoints -------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return self._json("GET", "/health")

    def context(self, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        query = {k: _query_value(v) for k, v in (params or {}).items()}
        return self._json("GET", CONTEXT_PATH, params=query)

    def estimate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._json("POST", ESTIMATE_PATH, json=dict(payload))

    def open_stream(self, payload: Mapping[str, Any]) -> EstimateStream:
        """Abre el stream SSE. Los errores previos al stream (conexión, 422, 5xx) se
        lanzan aquí, antes de mostrar ningún contenido."""
        request = self._http.build_request(
            "POST", STREAM_PATH, json=dict(payload), headers={"Accept": "text/event-stream"}
        )
        try:
            response = self._http.send(request, stream=True)
        except httpx.TimeoutException:
            raise ApiConnectionError(f"La API no respondió a tiempo ({self.base_url})") from None
        except httpx.HTTPError:
            raise ApiConnectionError(f"No se pudo conectar con la API en {self.base_url}") from None
        if response.status_code != 200:
            try:
                response.read()
                _raise_for_status(response)
            finally:
                response.close()
        if not response.headers.get("content-type", "").startswith("text/event-stream"):
            response.close()
            raise ApiServerError("La API no devolvió un stream SSE", response.status_code)
        return EstimateStream(response)

    # --- internos -------------------------------------------------------------------

    def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise ApiConnectionError(f"La API no respondió a tiempo ({self.base_url})") from None
        except httpx.HTTPError:
            raise ApiConnectionError(f"No se pudo conectar con la API en {self.base_url}") from None
        _raise_for_status(response)
        try:
            return response.json()
        except ValueError:
            raise ApiServerError("Respuesta no válida de la API", response.status_code) from None


def _query_value(value: Any) -> Any:
    return str(value).lower() if isinstance(value, bool) else value


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    if response.status_code == 422:
        raise ApiValidationError("La solicitud no es válida", _validation_details(detail))
    message = detail if isinstance(detail, str) else f"Error de la API (HTTP {response.status_code})"
    raise ApiServerError(message, response.status_code)


def _validation_details(detail: Any) -> list[str]:
    if isinstance(detail, str):
        return [detail]
    if isinstance(detail, list):
        out = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(p) for p in item.get("loc", []) if p != "body")
                out.append(f"{loc}: {item.get('msg', '')}".strip(": "))
        return out
    return []


def build_client() -> EstimatorApiClient:
    """Punto de construcción usado por la app (sustituible en pruebas)."""
    return EstimatorApiClient.from_settings(ClientSettings.from_env())
