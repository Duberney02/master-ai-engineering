"""Identificador de correlación por petición (`X-Request-ID`).

Reutiliza el valor de la petición si es un identificador razonable (evita inyectar texto arbitrario en los logs) o
genera un UUID. Lo vincula a los contextvars de structlog durante la petición —así lo llevan todos los logs, también
los de cada etapa del pipeline RAG— y lo devuelve en la cabecera de la respuesta.
"""

import re
from uuid import uuid4

import structlog
from fastapi import Request

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def resolve_request_id(value: str | None) -> str:
    return value if value and _VALID_REQUEST_ID.match(value) else str(uuid4())


async def request_id_middleware(request: Request, call_next):
    request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
    request.state.request_id = request_id
    with structlog.contextvars.bound_contextvars(request_id=request_id):
        response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response
