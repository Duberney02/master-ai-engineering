"""Lectura de un flujo SSE ya completo (líneas de `response.text`) para comprobar el contrato de los endpoints."""

import json
from collections.abc import Iterable, Iterator


def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict]]:
    """Cede `(evento, datos)` por cada evento; ignora comentarios y une las líneas `data:` de un mismo evento."""
    event, data = "message", []
    for line in lines:
        if not line:
            if data:
                yield event, json.loads("\n".join(data))
            event, data = "message", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[6:] if line.startswith("data: ") else line[5:])
