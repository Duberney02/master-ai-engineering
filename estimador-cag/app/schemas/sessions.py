"""Contratos HTTP de las sesiones conversacionales (`/api/v1/sessions`).

El resultado reutiliza `EstimationResult`; `ProjectMetadata` vive en `app.services.sessions`
porque forma parte del estado de la sesión.
"""

from pydantic import BaseModel, Field

from app.schemas.project_estimation import EstimationResponse
from app.services.sessions import ProjectMetadata


class SessionCreated(BaseModel):
    session_id: str = Field(description="UUID v4 de la sesión.")


class SessionEstimationResponse(EstimationResponse):
    """Respuesta de `POST /sessions/{id}/estimate`: la estimación y el estado de la conversación."""

    session_id: str
    project_metadata: ProjectMetadata
    turn_count: int = Field(ge=1, description="Turnos de la conversación, contando este.")
    max_turns: int = Field(ge=1, description="Turnos que conserva la ventana de la sesión.")
