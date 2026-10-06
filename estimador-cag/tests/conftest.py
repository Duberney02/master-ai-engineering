import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _hermetic_provider_env(monkeypatch):
    """Configuración mínima y ficticia del proveedor para todas las pruebas.

    `Settings` exige la clave del proveedor y las pruebas que arrancan la app (`TestClient`) la
    leen del entorno. Sin esto dependerían del `.env` local —con una clave real— y fallarían en
    CI. Las pruebas que necesitan otra configuración la fijan con `monkeypatch` o con `_env_file=None`.
    """
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")


def pytest_runtest_setup(item):
    get_settings.cache_clear()


def pytest_runtest_teardown(item, nextitem):
    get_settings.cache_clear()
