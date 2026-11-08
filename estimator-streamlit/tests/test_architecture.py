"""Regla central de las tres capas: este cliente solo habla HTTP con el backend y no depende del servicio de IA."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [ROOT / "streamlit_app.py", *sorted((ROOT / "estimator_chat").glob("*.py"))]
FORBIDDEN_TEXT = ("estimador-cag", "estimador_cag", "ESTIMATOR_API_BASE_URL", "/api/v1", ":8000")


def test_no_module_imports_the_ai_service():
    for source in SOURCES:
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                modules = [node.module]
            for module in modules:
                assert module.split(".")[0] != "app", f"{source.name} importa {module}, del servicio de IA"


def test_sources_have_no_network_reference_to_the_ai_service():
    for source in [*SOURCES, ROOT / "Dockerfile"]:
        text = source.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_TEXT:
            assert forbidden not in text, f"{source.name} menciona {forbidden!r}"
