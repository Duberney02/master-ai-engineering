"""Autenticación por clave de API de los routers RAG de la Sesión 9.

Dos claves independientes: quien tiene `RETRIEVAL_API_KEY` no puede llamar a `/v1/estimate/*` y viceversa. Se
comparan con `secrets.compare_digest` (tiempo constante), nunca con `==`, que filtra longitud y prefijo por tiempo.
Sin clave configurada, el router responde 401 a todo: un endpoint sin proteger no se habilita por omisión.
"""

import secrets

from fastapi import Header, HTTPException, status

from app.config import get_settings

API_KEY_HEADER = "X-API-Key"


def _verify(provided: str | None, expected: str | None) -> None:
    if not expected or not provided or not secrets.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clave de API ausente o no válida.",
            headers={"WWW-Authenticate": API_KEY_HEADER},
        )


async def require_retrieval_key(x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER)) -> None:
    """Protege `/v1/retrieval/*`."""
    _verify(x_api_key, get_settings().retrieval_api_key)


async def require_estimate_key(x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER)) -> None:
    """Protege `/v1/estimate/*` (pipeline completo y endpoints por etapa)."""
    _verify(x_api_key, get_settings().estimate_api_key)
