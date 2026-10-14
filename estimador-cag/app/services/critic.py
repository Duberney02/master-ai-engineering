"""Crítico independiente: revisa una estimación y devuelve feedback estructurado.

Recibe solo datos (transcripción, metadatos, audiencia y estimación): no conoce la sesión y por tanto no
puede modificarla. Usa `CRITIC_MODEL` si está configurado y la primitiva de generación estructurada.
"""

import json
from dataclasses import dataclass, field

from app.config import Settings
from app.prompts.loader import render_auxiliary_prompt, render_auxiliary_template
from app.schemas import EstimationResult
from app.schemas.critic import CriticFeedback
from app.services.llm_service import generate_from_messages
from app.services.llm_wrapper import Completion
from app.services.sessions import ProjectMetadata
from app.services.structured import Generator, generate_structured

# La transcripción puede ocupar hasta 80 000 caracteres: el crítico solo necesita el contexto principal.
_TRANSCRIPT_CHARS = 20_000
_CRITIC_MAX_TOKENS = 1500


@dataclass
class CriticReview:
    feedback: CriticFeedback
    completions: list[Completion] = field(default_factory=list)


def _data_json(data: dict) -> str:
    """JSON legible (UTF-8) para un bloque de datos; `<` y `>` escapados para que no cierren el bloque."""
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")


def render_feedback_message(feedback: CriticFeedback) -> str:
    """Mensaje que incorpora los defectos del crítico al prompt de la siguiente generación."""
    return render_auxiliary_template(
        "critic",
        "feedback",
        {
            "verdict": feedback.verdict.value,
            "explanation": feedback.explanation,
            "issues": [issue.model_dump(mode="json") for issue in feedback.issues],
        },
    )


class CriticService:
    def __init__(self, settings: Settings, *, generate: Generator = generate_from_messages):
        self.settings = settings
        self._generate = generate

    async def review(
        self,
        transcript: str,
        metadata: ProjectMetadata,
        audience: str,
        estimation: EstimationResult,
    ) -> CriticReview:
        """Feedback validado sobre `estimation`. Lanza `StructuredOutputError` si el modelo no cumple el
        contrato tras el reintento y propaga los errores del proveedor."""
        system, user = render_auxiliary_prompt(
            "critic",
            {
                "transcript": transcript[:_TRANSCRIPT_CHARS],
                "metadata": _data_json(metadata.model_dump(mode="json")),
                "audience": getattr(audience, "value", audience),
                "estimation": _data_json(estimation.model_dump(mode="json")),
            },
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        options: dict = {"max_tokens": _CRITIC_MAX_TOKENS}
        if self.settings.critic_model:
            options["model"] = self.settings.critic_model
        feedback, completions = await generate_structured(self._generate, messages, CriticFeedback, **options)
        return CriticReview(feedback=feedback, completions=completions)
