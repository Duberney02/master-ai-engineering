"""`GET /api/v1/prompts/estimation`: prompt de sistema renderizado y ejemplos few-shot.

Permite a clientes que no tienen las plantillas Jinja2 (p. ej. la web Rails) mostrar el contexto
del prompt, igual que la barra lateral de Streamlit.
"""

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.prompts.loader import DEFAULT_PROMPT_VERSION, few_shot_examples, render_estimation_prompt
from app.schemas import DetailLevel, EstimationRequest, OutputFormat, ProjectType
from app.services.pipeline import EstimationPipeline

router = APIRouter()

# Solo sirve para renderizar las plantillas: el prompt de sistema no incluye la descripción.
_PREVIEW_DESCRIPTION = "Vista previa del prompt con los valores elegidos en el formulario."


class FewShotExample(BaseModel):
    title: str
    description: str


class PromptPreview(BaseModel):
    prompt_version: str
    system_prompt: str
    examples: list[FewShotExample]


@router.get(
    "/prompts/estimation",
    response_model=PromptPreview,
    responses={422: {"description": "Versión de prompt o valores no válidos."}},
)
async def estimation_prompt(
    prompt_version: str = Query(DEFAULT_PROMPT_VERSION, max_length=10),
    project_type: ProjectType = ProjectType.MOBILE_APP,
    detail_level: DetailLevel = DetailLevel.MEDIUM,
    output_format: OutputFormat = OutputFormat.PHASES_TABLE,
) -> PromptPreview:
    EstimationPipeline.validate_version(prompt_version)
    request = EstimationRequest(
        description=_PREVIEW_DESCRIPTION,
        project_type=project_type,
        detail_level=detail_level,
        output_format=output_format,
    )
    system_prompt, _ = render_estimation_prompt(request, version=prompt_version)
    return PromptPreview(
        prompt_version=prompt_version,
        system_prompt=system_prompt,
        examples=[FewShotExample(title=t, description=d) for t, d in few_shot_examples(system_prompt)],
    )
