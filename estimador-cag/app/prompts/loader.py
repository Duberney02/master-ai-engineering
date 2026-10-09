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
from app.services.sessions import ProjectMetadata

logger = structlog.get_logger(__name__)

ESTIMATION_PROMPTS_DIR = Path(__file__).parent / "estimation"
# Plantillas de las llamadas auxiliares de las sesiones (no son versiones de la estimación).
SESSION_PROMPTS_DIR = Path(__file__).parent / "sessions"
# Plantillas versionadas de las tareas auxiliares: `auxiliary/<tarea>/<vN>/{system,user}.j2`.
AUXILIARY_PROMPTS_DIR = Path(__file__).parent / "auxiliary"
AUXILIARY_TASKS = ("summary", "anchors", "critic")
DEFAULT_AUXILIARY_VERSION = "v1"
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
        path.name for path in ESTIMATION_PROMPTS_DIR.iterdir() if path.is_dir() and _VERSION_PATTERN.match(path.name)
    ]
    return sorted(versions, key=lambda v: int(v[1:]))


@lru_cache
def _environment(version: str) -> Environment:
    # Un loader por versión: `{% include "examples.j2" %}` resuelve dentro de la misma versión
    # y, si no existe allí, en el directorio común.
    return Environment(
        loader=ChoiceLoader(
            [
                FileSystemLoader(ESTIMATION_PROMPTS_DIR / version),
                FileSystemLoader(ESTIMATION_PROMPTS_DIR),  # parciales compartidos entre versiones
            ]
        ),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,  # el destino es texto para el LLM, no HTML
        keep_trailing_newline=False,
    )


@lru_cache
def _session_environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(SESSION_PROMPTS_DIR),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        keep_trailing_newline=False,
    )


@lru_cache
def _auxiliary_environment(task: str, version: str) -> Environment:
    return Environment(
        loader=FileSystemLoader(AUXILIARY_PROMPTS_DIR / task / version),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        keep_trailing_newline=False,
    )


def available_auxiliary_versions(task: str) -> list[str]:
    """Versiones de la plantilla auxiliar `task`, ordenadas numéricamente."""
    if task not in AUXILIARY_TASKS:
        raise UnknownPromptVersionError(f"Unknown auxiliary prompt task: {task!r}")
    directory = AUXILIARY_PROMPTS_DIR / task
    versions = [p.name for p in directory.iterdir() if p.is_dir() and _VERSION_PATTERN.match(p.name)]
    return sorted(versions, key=lambda v: int(v[1:]))


def render_auxiliary_template(task: str, name: str, context: dict, version: str = DEFAULT_AUXILIARY_VERSION) -> str:
    """Renderiza `auxiliary/<task>/<version>/<name>.j2`; tarea o versión inexistentes lanzan
    `UnknownPromptVersionError` y una variable ausente del contexto falla (StrictUndefined)."""
    if not _VERSION_PATTERN.match(version) or version not in available_auxiliary_versions(task):
        raise UnknownPromptVersionError(f"Unknown {task} prompt version: {version!r}")
    return _render(_auxiliary_environment(task, version), f"{name}.j2", context)


def render_auxiliary_prompt(task: str, context: dict, version: str = DEFAULT_AUXILIARY_VERSION) -> tuple[str, str]:
    """`(system, user)` de una tarea auxiliar (resumen, anclas, crítico)."""
    return (
        render_auxiliary_template(task, "system", context, version),
        render_auxiliary_template(task, "user", context, version),
    )


def _validated(version: str) -> str:
    # Comprobar el formato antes de tocar el disco impide rutas como "../v1".
    if not _VERSION_PATTERN.match(version) or version not in available_versions():
        raise UnknownPromptVersionError(f"Unknown prompt version: {version!r}")
    return version


def _render(env: Environment, name: str, context: dict) -> str:
    # Los bloques condicionales dejan huecos variables; basta una línea en blanco entre párrafos.
    return re.sub(r"\n{3,}", "\n\n", env.get_template(name).render(**context)).strip()


_EXAMPLE = re.compile(
    r"^### Ejemplo \d+: (?P<title>.+?)\n.*?<project_description>\n(?P<description>.*?)\n</project_description>",
    re.S | re.M,
)


def few_shot_examples(system_prompt: str) -> list[tuple[str, str]]:
    """(título, descripción) de cada ejemplo few-shot incluido en un prompt de sistema renderizado."""
    return [(m["title"], m["description"]) for m in _EXAMPLE.finditer(system_prompt)]


def prompt_hash(system: str, user: str) -> str:
    return hashlib.sha256(f"{system}\0{user}".encode("utf-8")).hexdigest()


def render_system_prompt(
    request: EstimationRequest,
    version: str = DEFAULT_PROMPT_VERSION,
    project_metadata: ProjectMetadata | None = None,
    audience: str = "default",
) -> str:
    """Prompt de sistema. Con `project_metadata` (aunque esté vacío) incluye el bloque
    `<project_metadata>` de las sesiones; sin él, el prompt es el de siempre. `audience` solo lo
    usan las versiones adaptadas a la audiencia (`v4` y posteriores)."""
    env = _environment(_validated(version))
    context = request.model_dump(mode="json")
    context["project_metadata"] = project_metadata.model_dump(mode="json") if project_metadata else None
    context["audience"] = audience
    system = _render(env, "system.j2", context)
    if OUTPUT_CONTRACT_MARKER not in system:
        contract = _render(env, "output_contract.j2", context)
        system = system + "\n\n" + contract
    return system


def render_user_prompt(request: EstimationRequest, version: str = DEFAULT_PROMPT_VERSION) -> str:
    env = _environment(_validated(version))
    context = request.model_dump(mode="json")
    context["project_metadata"] = None
    return _render(env, "user.j2", context)


def render_metadata_extraction_prompt(
    current: ProjectMetadata, user_message: str, estimation_summary: str
) -> tuple[str, str]:
    """`(system, user)` de la llamada adicional que actualiza los metadatos del proyecto."""
    env = _session_environment()
    context = {
        "current_metadata": current.model_dump(mode="json"),
        "user_message": user_message,
        "estimation_summary": estimation_summary,
    }
    return _render(env, "metadata_system.j2", context), _render(env, "metadata_user.j2", context)


def render_estimation_prompt(request: EstimationRequest, version: str = DEFAULT_PROMPT_VERSION) -> tuple[str, str]:
    """Devuelve `(system, user)` listos para enviar al modelo como mensajes separados."""
    context = request.model_dump(mode="json")
    system = render_system_prompt(request, version)
    user = render_user_prompt(request, version)
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
