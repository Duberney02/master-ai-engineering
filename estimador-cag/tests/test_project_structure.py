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
    "app/services/llm_service.py",
    "app/services/evaluation.py",
    "app/schemas/estimation.py",
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
