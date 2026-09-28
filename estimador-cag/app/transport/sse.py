"""Server-Sent Events: serialización y latido.

Cada evento se envía como:

    event: <tipo>
    data: <JSON>

El JSON se serializa con `ensure_ascii=False`; si contuviera saltos de línea se
divide en varias líneas `data:` (el cliente las une con `\\n`, como exige la
especificación SSE), de modo que el contenido multilínea nunca rompe el framing.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # desactiva el buffering de proxies tipo nginx
    "Connection": "keep-alive",
}
HEARTBEAT = ": keep-alive\n\n"
# Solo CR/LF delimitan líneas en SSE (no U+2028 ni otros separadores Unicode).
_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def format_sse(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    lines = _LINE_BREAK.split(payload)
    return f"event: {event}\n" + "".join(f"data: {line}\n" for line in lines) + "\n"


async def with_heartbeat(source: AsyncIterator[str], interval: float) -> AsyncIterator[str]:
    """Reenvía `source` e intercala comentarios SSE si pasa `interval` sin datos
    (evita que proxies o el cliente cierren la conexión durante esperas largas,
    p. ej. la extracción de la fase 1). Cierra `source` siempre."""
    pending: asyncio.Task | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(anext(source))
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield HEARTBEAT
                continue
            task, pending = pending, None
            try:
                chunk = task.result()
            except StopAsyncIteration:
                return
            yield chunk
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            try:
                await pending
            except (asyncio.CancelledError, StopAsyncIteration, Exception):  # noqa: BLE001
                pass
        aclose = getattr(source, "aclose", None)
        if aclose is not None:
            await aclose()
