"""Decodificador SSE incremental conforme a la especificación WHATWG.

- Las líneas terminan en CRLF, LF o CR (también partidos entre fragmentos de red).
- Varias líneas `data:` de un evento se unen con `\\n`.
- Tras `campo:` se elimina UN solo espacio; el resto de espacios se conserva.
- Las líneas que empiezan por `:` son comentarios (latidos) y se ignoran.
- Un evento solo se despacha al recibir la línea en blanco que lo cierra: si la
  conexión se corta antes, el evento incompleto se descarta (nunca se da por bueno).
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class SSEEvent:
    event: str
    data: str
    id: str | None = None


class SSEDecoder:
    def __init__(self) -> None:
        self._buffer = ""
        self._pending_cr = False
        self._event = ""
        self._data: list[str] = []
        self._id: str | None = None
        self._has_data = False

    def feed(self, chunk: str) -> list[SSEEvent]:
        events: list[SSEEvent] = []
        for char in chunk:
            if self._pending_cr:
                self._pending_cr = False
                if char == "\n":
                    continue  # CRLF ya procesado en el CR
            if char == "\r":
                self._pending_cr = True
                self._line(self._buffer, events)
                self._buffer = ""
            elif char == "\n":
                self._line(self._buffer, events)
                self._buffer = ""
            else:
                self._buffer += char
        return events

    def _line(self, line: str, events: list[SSEEvent]) -> None:
        if line == "":
            if self._has_data:
                events.append(SSEEvent(self._event or "message", "\n".join(self._data), self._id))
            self._event, self._data, self._has_data = "", [], False
            return
        if line.startswith(":"):
            return
        field, sep, value = line.partition(":")
        if sep and value.startswith(" "):
            value = value[1:]
        if field == "event":
            self._event = value
        elif field == "data":
            self._data.append(value)
            self._has_data = True
        elif field == "id" and "\0" not in value:
            self._id = value
        # `retry` y campos desconocidos se ignoran


def iter_sse(chunks: Iterable[str]) -> Iterator[SSEEvent]:
    decoder = SSEDecoder()
    for chunk in chunks:
        yield from decoder.feed(chunk)
