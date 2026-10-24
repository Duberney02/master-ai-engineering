"""Reglas de dependencias entre capas de `app/` (ver `ARCHITECTURE.md`, §3).

Se analiza el AST de cada módulo (sin importarlo) y se comprueba que solo importa de las capas permitidas.
Las aristas que hoy incumplen la regla están en `KNOWN_VIOLATIONS`: es deuda documentada, no una excepción
aceptada. La lista solo puede encogerse: una violación nueva falla el test y una resuelta que siga en la
lista también lo hace, para obligar a retirarla.
"""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

# Capa -> prefijos de módulo que PUEDE importar (además de sí misma y de la biblioteca estándar/externa).
ALLOWED: dict[str, tuple[str, ...]] = {
    "foundation": ("app.config",),
    "domain.schemas": ("app.config", "app.foundation"),
    "domain": ("app.config", "app.foundation", "app.domain", "app.generation"),
    "generation.agentic": ("app.config", "app.foundation", "app.domain.schemas", "app.generation.conversation"),
    "generation.cag": ("app.config", "app.foundation", "app.domain.schemas"),
    "generation.conversation": ("app.config", "app.foundation", "app.domain.schemas"),
    "generation.rag": ("app.config", "app.foundation", "app.domain.schemas"),
    "ingestion": ("app.config", "app.foundation", "app.domain.schemas", "app.generation.rag"),
    "api": ("app.config", "app.dependencies", "app.domain", "app.foundation", "app.generation", "app.ingestion"),
}

# (módulo, módulo importado): violaciones existentes, a resolver por separado. Cada una se explica.
KNOWN_VIOLATIONS: dict[tuple[str, str], str] = {
    ("app.domain.schemas.sessions", "app.domain.audience"): "el contrato de sesión expone el enum de audiencia, que vive en el servicio",
    ("app.domain.schemas.sessions", "app.generation.conversation.sessions"): "el contrato reutiliza los modelos de la sesión en memoria",
    ("app.foundation.guardrails.input", "app.domain.schemas"): "el guardrail valida EstimationRequest; los contratos deberían quedar bajo foundation",
    ("app.foundation.llm.service", "app.domain.schemas.estimation"): "el servicio de transcripción construye EstimationResponse de dominio",
    ("app.foundation.llm.structured", "app.domain.validation"): "el bucle de re-prompt aplica las reglas de negocio de EstimationResult",
    ("app.foundation.prompts.loader", "app.domain.schemas"): "el loader renderiza a partir de EstimationRequest",
    ("app.foundation.prompts.loader", "app.generation.conversation.sessions"): "el loader renderiza el historial de la sesión",
}


def _layer(module: str) -> str | None:
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != "app":
        return None
    if parts[1] == "domain":
        return "domain.schemas" if len(parts) > 2 and parts[2] == "schemas" else "domain"
    if parts[1] == "generation" and len(parts) > 2:
        return f"generation.{parts[2]}"
    if parts[1] in {"foundation", "ingestion", "api"}:
        return parts[1]
    return None


def _module_name(path: Path) -> str:
    rel = path.relative_to(APP.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app"):
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.startswith("app"))
    return found


def _violations() -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for path in APP.rglob("*.py"):
        module = _module_name(path)
        layer = _layer(module)
        if layer is None:
            continue
        allowed = ALLOWED[layer]
        for imported in _imports(path):
            if imported == "app" or imported.startswith(("app.dependencies", "app.main")):
                if imported.startswith("app.dependencies") and layer == "api":
                    continue
                result.add((module, imported))
                continue
            same_layer = _layer(imported) == layer
            if same_layer or imported.startswith(allowed):
                continue
            result.add((module, imported))
    # `from app.x import y` genera también `app.x.y`: se queda con el módulo más corto de cada arista.
    return {(m, i) for m, i in result if not any(o != i and i.startswith(o + ".") and (m, o) in result for _, o in result)}


def test_no_new_layer_violations():
    new = _violations() - set(KNOWN_VIOLATIONS)
    assert not new, "Importaciones que rompen las reglas de capas:\n" + "\n".join(f"  {m} -> {i}" for m, i in sorted(new))


def test_known_violations_are_still_violations():
    stale = set(KNOWN_VIOLATIONS) - _violations()
    assert not stale, "Ya no son violaciones, quítalas de KNOWN_VIOLATIONS:\n" + "\n".join(f"  {m} -> {i}" for m, i in sorted(stale))
