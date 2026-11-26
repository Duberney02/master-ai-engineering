"""Parser SSE neutral para las pruebas: interpreta el cuerpo `text/event-stream` de los endpoints."""

import json
from collections.abc import Iterable, Iterator


def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict]]:
    """Cede `(evento, datos)` por cada bloque SSE; ignora comentarios y exige JSON objeto en `data`."""
    event, data = "message", []
    for line in lines:
        if not line:
            if data:
                value = json.loads("\n".join(data))
                if not isinstance(value, dict):
                    raise ValueError("Evento SSE inválido: data no es un objeto JSON.")
                yield event, value
            event, data = "message", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[6:] if line.startswith("data: ") else line[5:])
