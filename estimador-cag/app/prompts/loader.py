"""Renderiza los prompts de estimación desde plantillas Jinja2 versionadas.

Cada versión es un directorio `estimation/<vN>/` con `system.j2`, `user.j2` y
`examples.j2`. Para añadir una versión basta con crear el directorio: el resto
del código solo pasa el nombre.
"""

import hashlib
import re
from functools import lru_cache
from pathlib import Path

import structlog
from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined

from app.schemas import EstimationRequest

logger = structlog.get_logger(__name__)

ESTIMATION_PROMPTS_DIR = Path(__file__).parent / "estimation"
DEFAULT_PROMPT_VERSION = "v3"
# Contrato de salida JSON compartido (`estimation/output_contract.j2`). Las versiones que no lo
# incluyen en su `system.j2` lo reciben al final del prompt de sistema.
OUTPUT_CONTRACT_MARKER = "## Contrato de salida (JSON)"
_VERSION_PATTERN = re.compile(r"^v\d+$")


class UnknownPromptVersionError(ValueError):
    """La versión pedida no existe (o no tiene un nombre válido)."""


def available_versions() -> list[str]:
    """Versiones presentes en disco, ordenadas numéricamente (v1, v2, …, v10)."""
    versions = [
        path.name
        for path in ESTIMATION_PROMPTS_DIR.iterdir()
        if path.is_dir() and _VERSION_PATTERN.match(path.name)
    ]
    return sorted(versions, key=lambda v: int(v[1:]))


@lru_cache
def _environment(version: str) -> Environment:
    # Un loader por versión: `{% include "examples.j2" %}` resuelve dentro de la misma versión
    # y, si no existe allí, en el directorio común.
    return Environment(
        loader=ChoiceLoader([
            FileSystemLoader(ESTIMATION_PROMPTS_DIR / version),
            FileSystemLoader(ESTIMATION_PROMPTS_DIR),  # parciales compartidos entre versiones
        ]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,  # el destino es texto para el LLM, no HTML
        keep_trailing_newline=False,
    )


def _validated(version: str) -> str:
    # Comprobar el formato antes de tocar el disco impide rutas como "../v1".
    if not _VERSION_PATTERN.match(version) or version not in available_versions():
        raise UnknownPromptVersionError(f"Unknown prompt version: {version!r}")
    return version


def _render(env: Environment, name: str, context: dict) -> str:
    # Los bloques condicionales dejan huecos variables; basta una línea en blanco entre párrafos.
    return re.sub(r"\n{3,}", "\n\n", env.get_template(name).render(**context)).strip()


def prompt_hash(system: str, user: str) -> str:
    return hashlib.sha256(f"{system}\0{user}".encode("utf-8")).hexdigest()


def render_estimation_prompt(
    request: EstimationRequest, version: str = DEFAULT_PROMPT_VERSION
) -> tuple[str, str]:
    """Devuelve `(system, user)` listos para enviar al modelo como mensajes separados."""
    env = _environment(_validated(version))
    context = request.model_dump(mode="json")
    system = _render(env, "system.j2", context)
    if OUTPUT_CONTRACT_MARKER not in system:
        contract = _render(env, "output_contract.j2", context)
        system = system + "\n\n" + contract
    user = _render(env, "user.j2", context)
    logger.info(
        "prompt_rendered",
        prompt_version=version,
        prompt_hash=prompt_hash(system, user),
        project_type=context["project_type"],
        detail_level=context["detail_level"],
        output_format=context["output_format"],
        reference_projects=len(request.reference_projects or []),
        system_chars=len(system),
        user_chars=len(user),
    )
    return system, user
