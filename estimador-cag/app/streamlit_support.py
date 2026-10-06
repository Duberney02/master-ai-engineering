"""Utilidades sin dependencia de Streamlit que soportan `streamlit_app.py`."""

import asyncio
from collections.abc import AsyncIterator, Iterator, Mapping, MutableMapping

from app.prompts.loader import few_shot_examples  # noqa: F401  (se reexporta para el cliente Streamlit)

# Una transcripción de 80 000 caracteres ocupa como mucho ~320 KB en UTF-8.
MAX_TRANSCRIPT_BYTES = 400_000
_SECRET_ENV_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")


def decode_transcript(data: bytes) -> str:
    """Texto de un archivo .txt subido; lanza ValueError con un mensaje apto para el usuario."""
    if len(data) > MAX_TRANSCRIPT_BYTES:
        raise ValueError(f"El archivo supera el máximo de {MAX_TRANSCRIPT_BYTES // 1000} KB.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("El archivo debe estar codificado en UTF-8.") from None


def sync_secrets_to_env(secrets: Mapping[str, str], environ: MutableMapping[str, str]) -> None:
    """Copia las API keys conocidas de `secrets` a `environ` sin sobrescribir el entorno."""
    for key in _SECRET_ENV_KEYS:
        if key not in environ and key in secrets:
            environ[key] = secrets[key]


def iter_sync(async_gen: AsyncIterator[str]) -> Iterator[str]:
    """Consume un generador asíncrono en un loop propio, cediendo cada valor de forma síncrona."""
    loop = asyncio.new_event_loop()
    try:
        while True:
            try:
                yield loop.run_until_complete(async_gen.__anext__())
            except StopAsyncIteration:
                return
    finally:
        loop.close()
