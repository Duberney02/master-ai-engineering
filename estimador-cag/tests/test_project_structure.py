"""Valida que la estructura de carpetas y archivos del proyecto es la esperada.

Si alguien borra o mueve un módulo clave (por ejemplo al refactorizar), este
test falla de inmediato en local y en CI, antes de que el resto de la suite
intente importar algo que ya no existe.
"""

from pathlib import Path

# Rutas relativas a la raíz de estimador-cag/ que deben existir siempre.
REQUIRED_PATHS = [
    "app/__init__.py",
    "app/main.py",
    "app/config.py",
    "app/routers/__init__.py",
    "app/routers/estimations.py",
    "app/services/__init__.py",
    "app/dependencies.py",
    "app/observability.py",
    "app/services/estimation_service.py",
    "app/services/prompts.py",
    "app/services/reporting.py",
    "app/services/evaluation.py",
    "app/llm/client.py",
    "app/llm/routing.py",
    "app/llm/errors.py",
    "app/llm/pricing.py",
    "app/llm/providers/openai_provider.py",
    "app/llm/providers/anthropic_provider.py",
    "app/cache/result_cache.py",
    "app/transport/sse.py",
    "app/transport/errors.py",
    "estimator_client/__init__.py",
    "estimator_client/api.py",
    "estimator_client/sse.py",
    "estimator_client/config.py",
    "streamlit_app.py",
    "app/schemas/estimation.py",
    "app/context/__init__.py",
    "app/context/examples.py",
    "tests/conftest.py",
    "pyproject.toml",
    ".env.example",
    ".env.client.example",
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
    import app.cache.result_cache  # noqa: F401
    import app.config  # noqa: F401
    import app.context.examples  # noqa: F401
    import app.llm.client  # noqa: F401
    import app.main  # noqa: F401
    import app.routers.estimations  # noqa: F401
    import app.schemas.estimation  # noqa: F401
    import app.services.estimation_service  # noqa: F401
    import app.services.evaluation  # noqa: F401
    import estimator_client.api  # noqa: F401


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


def test_compose_separates_client_and_server():
    import yaml

    root = Path(__file__).resolve().parent.parent
    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    api, chat, redis = services["api"], services["chat"], services["redis"]
    # Solo el backend recibe el .env con credenciales.
    assert "env_file" in api and "env_file" not in chat
    assert chat["environment"]["ESTIMATOR_API_BASE_URL"] == "http://api:8000"
    assert not any("KEY" in k or "REDIS" in k for k in chat["environment"])
    assert api["environment"]["REDIS_URL"].startswith("redis://redis:")
    # Redis no se publica en el host y persiste en un volumen con nombre.
    assert "ports" not in redis
    assert any(str(v).startswith("redis-data:") for v in redis["volumes"])
    for svc in (api, chat, redis):
        assert "healthcheck" in svc
    assert api["build"]["target"] == "api" and chat["build"]["target"] == "ui"
    assert all(str(v).endswith(":ro") for v in api.get("volumes", []) + chat.get("volumes", []))
