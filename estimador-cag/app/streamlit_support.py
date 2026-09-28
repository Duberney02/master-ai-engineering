"""Utilidades sin dependencia de Streamlit que soportan `streamlit_app.py`."""

import asyncio
from collections.abc import AsyncIterator, Iterator, Mapping, MutableMapping

_SECRET_ENV_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")


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
