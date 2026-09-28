"""Interfaz Streamlit: consume la API por HTTP y no importa ni ejecuta el backend."""

import ast
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from app.llm.errors import LLMUnavailableError
from estimator_client import api
from tests._fakes import (
    FakeProvider,
    FakeRedis,
    StreamScript,
    make_client,
    make_resources,
    openai_settings,
)

ROOT = Path(__file__).resolve().parent.parent
APP_PATH = str(ROOT / "streamlit_app.py")
T1 = "Transcripción de prueba suficientemente larga para pasar validación"
T2 = "Segunda transcripción suficientemente larga para el test"


class _SharedHttpClient(api.EstimatorApiClient):
    def close(self) -> None:  # el TestClient se comparte entre reruns
        pass


@pytest.fixture
def provider():
    return FakeProvider("openai", [])


@pytest.fixture
def api_server(provider, mocker):
    """API real (FastAPI + servicio + wrapper + caché) con proveedor y Redis falsos."""
    resources = make_resources(openai_settings(cache_enabled=True), {"openai": provider}, FakeRedis())
    with make_client(resources) as http:
        mocker.patch.object(api, "build_client", return_value=_SharedHttpClient(http))
        yield http


def _run() -> AppTest:
    return AppTest.from_file(APP_PATH, default_timeout=10).run()


def test_empty_chat_shows_no_messages_and_server_context(api_server):
    at = _run()
    assert at.exception == []
    assert len(at.chat_message) == 0
    assert any("Senior Software Estimation Architect" in ta.value for ta in at.sidebar.text_area)
    assert "Plataforma de Gestión de Inventario" in " ".join(m.value for m in at.sidebar.markdown)


def test_sending_message_streams_estimation_and_shows_metrics(api_server, provider):
    provider.outcomes = [StreamScript(["## Estimación: Demo\n", "\n- línea"], input_tokens=111, output_tokens=22)]
    at = _run()
    at.chat_input[0].set_value(T1).run()

    assert at.exception == []
    assert len(at.chat_message) == 2
    assert at.chat_message[0].markdown[0].value == T1
    assert "Estimación: Demo" in at.chat_message[1].markdown[0].value
    assert not at.error and not at.warning
    metrics = {m.label: m.value for m in at.sidebar.metric}
    assert metrics["Tokens de entrada"] == "111"
    assert metrics["Tokens de salida"] == "22"
    assert metrics["Caché"] == "fallo"
    assert metrics["Modelo"] == "gpt-4o-mini"


def test_history_persists_and_second_identical_request_uses_cache(api_server, provider):
    provider.outcomes = [StreamScript(["Respuesta 1"]), StreamScript(["Respuesta 2"])]
    at = _run()
    at.chat_input[0].set_value(T1).run()
    at.chat_input[0].set_value(T2).run()
    at.chat_input[0].set_value(T1).run()

    assert at.exception == []
    assert len(at.chat_message) == 6
    assert at.chat_message[1].markdown[0].value == "Respuesta 1"
    assert at.chat_message[3].markdown[0].value == "Respuesta 2"
    assert at.chat_message[5].markdown[0].value == "Respuesta 1"
    assert len(provider.calls) == 2
    metrics = {m.label: m.value for m in at.sidebar.metric}
    assert metrics["Caché"] == "acierto"
    assert metrics["Coste de esta solicitud"] == "$0.000000"


def test_validation_error_is_shown_and_not_presented_as_estimation(api_server, provider):
    at = _run()
    at.chat_input[0].set_value("corta").run()
    assert at.exception == []
    assert any("Solicitud no válida" in e.value for e in at.error)
    assert provider.calls == []
    assert {m.label for m in at.sidebar.metric} == set()  # no hay métricas de éxito


def test_error_mid_stream_is_flagged_as_partial(api_server, provider):
    provider.outcomes = [StreamScript(["## Parcial"], error=LLMUnavailableError(), error_after=1)]
    at = _run()
    at.chat_input[0].set_value(T1).run()
    assert at.exception == []
    errors = " ".join(e.value for e in at.error)
    assert "Error durante la generación" in errors and "respuesta parcial" in errors
    assert st_last_metadata(at) is None


def st_last_metadata(at):
    return at.session_state["last_metadata"]


def test_connection_error_is_reported(mocker):
    def refuse(request):
        raise httpx.ConnectError("refused")

    client = _SharedHttpClient(httpx.Client(base_url="http://api:8000", transport=httpx.MockTransport(refuse)))
    mocker.patch.object(api, "build_client", return_value=client)
    at = _run()
    at.chat_input[0].set_value(T1).run()
    assert at.exception == []
    assert any("No se pudo contactar con la API" in e.value for e in at.error)
    assert any("No se pudo conectar" in e.value for e in at.sidebar.error)


# --------------------------------------------------------------------------- aislamiento


CLIENT_FILES = [ROOT / "streamlit_app.py", *sorted((ROOT / "estimator_client").glob("*.py"))]
FORBIDDEN = ("app", "openai", "anthropic", "redis", "pydantic_settings", "fastapi")


@pytest.mark.parametrize("path", CLIENT_FILES, ids=lambda p: p.name)
def test_client_code_does_not_import_backend_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            roots = [(node.module or "").split(".")[0]]
        else:
            continue
        assert not set(roots) & set(FORBIDDEN), f"{path.name} importa {roots}"


def test_client_runs_without_backend_packages_or_credentials():
    """En un proceso aparte se bloquea cualquier import del backend, SDK o Redis y se
    eliminan las claves del entorno: el script de Streamlit debe funcionar igual."""
    code = f"""
import sys, importlib.abc, os
for k in list(os.environ):
    if k.endswith("_API_KEY") or k.startswith("REDIS"):
        del os.environ[k]
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in {FORBIDDEN!r}:
            raise ImportError("blocked: " + name)
sys.meta_path.insert(0, Block())
import httpx
from estimator_client import api
def handler(request):
    raise httpx.ConnectError("no server")
api.build_client = lambda: api.EstimatorApiClient(httpx.Client(base_url="http://api:8000", transport=httpx.MockTransport(handler)))
from streamlit.testing.v1 import AppTest
at = AppTest.from_file({APP_PATH!r}, default_timeout=20).run()
assert not at.exception, at.exception
assert not [m for m in sys.modules if m.split(".")[0] in {FORBIDDEN!r}]
print("OK")
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            cwd=ROOT, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "OK" in result.stdout
