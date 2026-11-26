"""Cancela trabajo REST cuando el transporte ASGI detecta la desconexión."""

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from fastapi import HTTPException, Request

T = TypeVar("T")


async def _wait_for_disconnect(request: Request) -> None:
    while (await request.receive())["type"] != "http.disconnect":
        pass


async def complete_while_connected(request: Request, operation: Coroutine[Any, Any, T]) -> T:
    """Ejecuta la operación tras leerse el cuerpo y espera su limpieza al cancelar."""
    work = asyncio.create_task(operation)
    disconnect = asyncio.create_task(_wait_for_disconnect(request))
    try:
        await asyncio.wait((work, disconnect), return_when=asyncio.FIRST_COMPLETED)
        if work.done():
            return await work
        await disconnect
        raise HTTPException(status_code=499, detail="La solicitud se canceló.")
    finally:
        for task in (disconnect, work):
            if not task.done():
                task.cancel()
        await asyncio.gather(disconnect, work, return_exceptions=True)
