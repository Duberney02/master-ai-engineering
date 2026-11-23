"""Rate limiting por clave de API de los routers RAG de la Sesión 9 (slowapi, en memoria).

La identidad es la cabecera `X-API-Key`, no la IP: varios clientes tras un NAT no comparten cubo y una clave no
esquiva su límite rotando IPs. Sin clave se usa la IP del cliente. La clave no se guarda en claro en el limitador:
el cubo se identifica por un hash. Los límites se declaran por ruta (recuperación 120/min, estimación 10/min, etapas
30/min) y el handler responde 429 en JSON con `Retry-After`.

El almacén en memoria no se comparte entre workers: aceptable a escala de curso (ver README).
"""

import hashlib

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.security import API_KEY_HEADER

logger = structlog.get_logger(__name__)

RETRY_AFTER_SECONDS = 60
RETRIEVAL_LIMIT = "120/minute"
ESTIMATE_LIMIT = "10/minute"
STAGES_LIMIT = "30/minute"


def api_key_identifier(request: Request) -> str:
    """Cubo del limitador: hash de la clave de API o, sin ella, la IP del cliente."""
    key = request.headers.get(API_KEY_HEADER)
    if key:
        return "key:" + hashlib.sha256(key.encode()).hexdigest()[:32]
    return "ip:" + get_remote_address(request)


limiter = Limiter(key_func=api_key_identifier)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    limit = str(exc.limit.limit)
    logger.warning("rate_limit_exceeded", reason=limit)
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Límite de peticiones superado.",
            "limit": limit,
            "retry_after_seconds": RETRY_AFTER_SECONDS,
        },
        headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
    )
