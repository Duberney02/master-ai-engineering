"""Contratos HTTP de las sesiones conversacionales (`/api/v1/sessions`).

El resultado reutiliza `EstimationResult`; `ProjectMetadata` vive en `app.services.sessions`
porque forma parte del estado de la sesión.
"""

from pydantic import BaseModel, Field

from app.schemas.project_estimation import EstimationResponse
from app.services.audience import Audience
from app.services.sessions import ProjectMetadata


class SessionCreated(BaseModel):
    session_id: str = Field(description="UUID v4 de la sesión.")


class SessionEstimationResponse(EstimationResponse):
    """Respuesta de `POST /sessions/{id}/estimate`: la estimación y el estado de la conversación."""

    session_id: str
    project_metadata: ProjectMetadata
    turn_count: int = Field(ge=1, description="Turnos de la conversación, contando este.")
    max_turns: int = Field(ge=1, description="Turnos que conserva la ventana de la sesión.")
    # Opcionales para que el cliente Streamlit, que valida con esta misma clase, siga aceptando
    # respuestas de servidores anteriores; el servidor siempre las rellena.
    audience: Audience | None = Field(default=None, description="Audiencia aplicada al prompt de este turno.")
    audience_rule: str | None = Field(
        default=None,
        description="Regla que decidió la audiencia: explicit, confidentiality_or_regulatory, "
        "technical_terms, small_team o no_match.",
    )


class SessionState(BaseModel):
    """Estado de una sesión (`GET /sessions/{id}`), sin ejecutar ninguna estimación."""

    session_id: str
    recent_message_count: int = Field(ge=0, description="Mensajes de la ventana reciente (2 por turno).")
    max_turns: int = Field(ge=1)
    project_metadata: ProjectMetadata
    anchored_message_count: int = Field(ge=0, description="Mensajes conservados como anclas (2 por ancla).")
    summary_length: int = Field(ge=0, description="Caracteres del resumen acumulativo.")
    last_audience: Audience | None = None
    last_audience_rule: str | None = None
