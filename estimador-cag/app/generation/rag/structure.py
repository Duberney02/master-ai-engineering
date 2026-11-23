"""Estructura de la estimación sin horas (Sesión 10): módulos → tareas como descomposición LIBRE del brief.

Esta etapa NO recupera ni cita fuentes: fundamentar la estructura en presupuestos recuperados empobrece el árbol (copia
la forma de proyectos ajenos). El modelo propone módulos y tareas con nombre y descripción; las horas se derivan después
por búsqueda sobre las tareas históricas (`task_hours.py`). La salida del modelo (`StructureDraft`) no tiene campo de
horas; la respuesta pública (`StructureResult`) devuelve `engineer_days=null` en cada tarea de forma explícita, para que
los clientes tengan una única forma tanto para la estructura como para la estimación completa.
"""

from pydantic import BaseModel, Field

from app.foundation.llm.structured import Generator, generate_structured
from app.foundation.prompts.loader import render_rag_template
from app.generation.rag.errors import GenerationError
from app.generation.rag.schemas import EstimationQuery, StructureModule, StructureResult, StructureTask

_STRUCTURE_MAX_TOKENS = 8000


class _DraftTask(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)


class _DraftModule(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    tasks: list[_DraftTask] = Field(min_length=1, max_length=50)


class StructureDraft(BaseModel):
    """Salida estructurada del modelo: sin horas ni fuentes (los campos extra que añada se descartan)."""

    modules: list[_DraftModule] = Field(min_length=1, max_length=30)
    assumptions: list[str] = Field(default_factory=list, max_length=30)


def build_structure_messages(query: EstimationQuery) -> list[dict[str, str]]:
    system = render_rag_template("structure", "system", {})
    user = render_rag_template("structure", "user", {"query": query.model_dump(mode="json")})
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def generate_structure(
    query: EstimationQuery, *, generate: Generator, model: str | None = None
) -> StructureResult:
    """Módulos y tareas del brief, sin horas. Cualquier fallo (proveedor o salida inválida) es `GenerationError`."""
    options: dict = {"max_tokens": _STRUCTURE_MAX_TOKENS}
    if model:
        options["model"] = model
    try:
        draft, _ = await generate_structured(generate, build_structure_messages(query), StructureDraft, **options)
    except Exception as exc:
        raise GenerationError("structure generation failed") from exc
    return StructureResult(
        modules=[
            StructureModule(
                name=module.name,
                description=module.description,
                tasks=[StructureTask(name=task.name, description=task.description) for task in module.tasks],
            )
            for module in draft.modules
        ],
        assumptions=draft.assumptions,
    )
