from app.streamlit_support import iter_sync, sync_secrets_to_env


def test_sync_secrets_to_env_copies_known_keys():
    secrets = {"OPENAI_API_KEY": "sk-from-secrets", "SOME_OTHER_KEY": "ignored"}
    environ: dict = {}

    sync_secrets_to_env(secrets, environ)

    assert environ == {"OPENAI_API_KEY": "sk-from-secrets"}


def test_sync_secrets_to_env_does_not_override_existing_env():
    secrets = {"OPENAI_API_KEY": "sk-from-secrets"}
    environ = {"OPENAI_API_KEY": "sk-from-env"}

    sync_secrets_to_env(secrets, environ)

    assert environ["OPENAI_API_KEY"] == "sk-from-env"


def test_sync_secrets_to_env_handles_empty_secrets():
    environ: dict = {"PATH": "/usr/bin"}

    sync_secrets_to_env({}, environ)

    assert environ == {"PATH": "/usr/bin"}


async def _fake_stream():
    yield "Hola "
    yield "mundo"


def test_iter_sync_yields_chunks_in_order():
    assert list(iter_sync(_fake_stream())) == ["Hola ", "mundo"]


async def _empty_stream():
    return
    yield  # pragma: no cover - makes this an async generator


def test_iter_sync_empty_generator_yields_nothing():
    assert list(iter_sync(_empty_stream())) == []
