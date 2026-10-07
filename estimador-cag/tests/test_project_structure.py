"""Valida que la estructura de carpetas y archivos del proyecto es la esperada.

Si alguien borra o mueve un módulo clave (por ejemplo al refactorizar), este
test falla de inmediato en local y en CI, antes de que el resto de la suite
intente importar algo que ya no existe.
"""

from pathlib import Path

import pytest

# Rutas relativas a la raíz de estimador-cag/ que deben existir siempre.
REQUIRED_PATHS = [
    "app/__init__.py",
    "app/main.py",
    "app/config.py",
    "app/routers/__init__.py",
    "app/routers/estimations.py",
    "app/routers/project_estimations.py",
    "app/routers/history.py",
    "app/routers/prompts.py",
    "app/services/__init__.py",
    "app/services/llm_service.py",
    "app/services/evaluation.py",
    "app/schemas/estimation.py",
    "app/schemas/project_estimation.py",
    "app/schemas/history.py",
    "app/services/history.py",
    "app/services/sessions.py",
    "app/services/attachments.py",
    "app/services/session_estimation.py",
    "app/schemas/sessions.py",
    "app/routers/sessions.py",
    "app/prompts/estimation/project_metadata.j2",
    "app/prompts/sessions/metadata_system.j2",
    "app/prompts/sessions/metadata_user.j2",
    "app/prompts/loader.py",
    "app/prompts/estimation/v1/system.j2",
    "app/prompts/estimation/v1/user.j2",
    "app/prompts/estimation/v1/examples.j2",
    "app/prompts/estimation/v2/system.j2",
    "app/prompts/estimation/v2/user.j2",
    "app/prompts/estimation/v2/examples.j2",
    "app/context/__init__.py",
    "app/context/examples.py",
    "tests/conftest.py",
    "pyproject.toml",
    ".env.example",
    "Dockerfile",
    ".dockerignore",
    "docker-compose.yml",
    "README.md",
]


def test_required_project_structure_exists():
    root = Path(__file__).resolve().parent.parent
    missing = [p for p in REQUIRED_PATHS if not (root / p).exists()]
    assert not missing, f"Faltan archivos/carpetas esperados: {missing}"


def test_app_package_is_importable():
    # Si algún __init__.py falta o hay un error de sintaxis en el paquete,
    # esto falla con un mensaje claro en vez de un ImportError confuso más
    # adelante en la suite.
    import app  # noqa: F401
    import app.main  # noqa: F401
    import app.config  # noqa: F401
    import app.routers.estimations  # noqa: F401
    import app.routers.project_estimations  # noqa: F401
    import app.prompts.loader  # noqa: F401
    import app.services.llm_service  # noqa: F401
    import app.services.evaluation  # noqa: F401
    import app.schemas.estimation  # noqa: F401
    import app.context.examples  # noqa: F401


def test_container_files_follow_the_security_baseline():
    root = Path(__file__).resolve().parent.parent
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.count("\nFROM ") + dockerfile.startswith("FROM ") >= 2  # multietapa
    assert "\nUSER app" in dockerfile  # sin root
    assert "HEALTHCHECK" in dockerfile
    assert "--no-dev" in dockerfile
    ignore = (root / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignore and ".venv" in ignore  # secretos y entornos fuera de la imagen
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert "env_file" in compose and "healthcheck" in compose


# --- Compose raíz (API + web + Redis Stack + PostgreSQL) ----------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _root_compose() -> dict:
    import yaml

    path = REPO_ROOT / "docker-compose.yml"
    if not path.exists():  # p. ej. ejecutando solo estimador-cag/ en un contenedor aislado
        pytest.skip("Compose raíz no disponible")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_root_compose_defines_all_services_on_a_shared_network():
    compose = _root_compose()

    assert set(compose["services"]) == {
        "estimador-cag", "estimador-cag-chat", "estimator-web", "estimator-web-react",
        "redis", "postgres"}
    assert "estimator-net" in compose["networks"]
    for name, service in compose["services"].items():
        assert service["networks"] == ["estimator-net"], name


def test_root_compose_has_named_volumes_and_healthchecks():
    compose = _root_compose()

    assert {"redis_data", "postgres_data"} <= set(compose["volumes"])
    assert any(v.startswith("postgres_data:") for v in compose["services"]["postgres"]["volumes"])
    assert any(v.startswith("redis_data:") for v in compose["services"]["redis"]["volumes"])
    for name, service in compose["services"].items():
        assert "healthcheck" in service, f"{name} sin healthcheck"
    assert "pg_isready" in str(compose["services"]["postgres"]["healthcheck"]["test"])
    assert "redis-cli" in str(compose["services"]["redis"]["healthcheck"]["test"])
    assert "/health" in str(compose["services"]["estimador-cag"]["healthcheck"]["test"])
    assert "/up" in str(compose["services"]["estimator-web"]["healthcheck"]["test"])
    assert "/healthz" in str(compose["services"]["estimator-web-react"]["healthcheck"]["test"])


def test_root_compose_waits_for_healthy_dependencies():
    services = _root_compose()["services"]

    assert {k: v["condition"] for k, v in services["estimador-cag"]["depends_on"].items()} == {
        "redis": "service_healthy", "postgres": "service_healthy"}
    assert services["estimator-web"]["depends_on"]["estimador-cag"]["condition"] == "service_healthy"


def test_root_compose_wires_services_and_keeps_keys_out_of_the_web():
    services = _root_compose()["services"]
    api_env, web_env = services["estimador-cag"]["environment"], services["estimator-web"]["environment"]

    assert api_env["REDIS_URL"].startswith("redis://redis:")
    assert api_env["DATABASE_URL"].startswith("postgresql+asyncpg://") and "@postgres:5432/" in api_env["DATABASE_URL"]
    assert web_env["ESTIMATOR_API_URL"] == "http://estimador-cag:8000"
    assert not any("API_KEY" in key for key in web_env)
    assert "env_file" not in services["estimator-web"]


def test_root_compose_publishes_only_api_chat_and_web_ports():
    services = _root_compose()["services"]

    assert services["estimador-cag"]["ports"] == ["8000:8000"]
    assert services["estimator-web"]["ports"] == ["3000:3000"]
    assert services["estimador-cag-chat"]["ports"] == ["8501:8501"]
    assert services["estimador-cag-chat"]["environment"] == {
        "ESTIMATOR_API_BASE_URL": "http://estimador-cag:8000"}
    assert "ports" not in services["redis"] and "ports" not in services["postgres"]


def test_web_app_files_exist():
    web = REPO_ROOT / "estimator-web"
    if not web.exists():
        pytest.skip("estimator-web no disponible")
    for relative in ["Dockerfile", "Gemfile", "Gemfile.lock", "app/services/estimator_api.rb",
                     "app/controllers/estimations_controller.rb", "test/services/estimator_api_test.rb"]:
        assert (web / relative).exists(), relative
    assert "USER rails" in (web / "Dockerfile").read_text(encoding="utf-8")
