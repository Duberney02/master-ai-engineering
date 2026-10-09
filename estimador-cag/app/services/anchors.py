"""Detección de anclas de memoria: turnos con compromisos que no deben perderse al salir de la ventana.

Un `AnchorDetector` decide si un par usuario/asistente es un ancla y devuelve los nombres de las
reglas que lo identificaron. Hay dos implementaciones intercambiables (`ANCHOR_DETECTION_MODE`):

- `HeuristicAnchorDetector`: expresiones regulares con nombre sobre el mensaje del usuario. Sin coste
  ni latencia. Se evalúa solo el mensaje del usuario porque la respuesta del asistente es una
  estimación que siempre habla de costes y plazos y marcaría casi todos los turnos.
- `LLMAnchorDetector`: una llamada estructurada al LLM; ante cualquier fallo recurre al heurístico.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, Protocol

import structlog
from pydantic import BaseModel, Field

from app.config import Settings
from app.prompts.loader import render_auxiliary_prompt
from app.services.llm_service import generate_from_messages
from app.services.structured import Generator, generate_structured

logger = structlog.get_logger(__name__)

AnchorRule = Literal["contract", "closed_scope", "agreed_budget", "deadline", "legal_regulatory"]
# Texto de cada mensaje que ve el detector LLM.
_DETECTOR_USER_CHARS = 6000
_DETECTOR_ASSISTANT_CHARS = 3000
_DETECTOR_MAX_TOKENS = 300


@dataclass(frozen=True)
class AnchorMatch:
    """Resultado positivo de la detección: reglas coincidentes y quién las identificó."""

    rules: tuple[str, ...]
    source: Literal["heuristic", "llm"]


class AnchorDetector(Protocol):
    async def detect(self, user: str, assistant: str) -> AnchorMatch | None:
        """`AnchorMatch` si el par contiene un compromiso relevante; `None` si no."""
        ...


def fold(text: str) -> str:
    """Minúsculas y sin acentos, para que «Fecha límite» y «fecha limite» coincidan."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _rule(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# (nombre, patrón) sobre texto ya plegado (sin acentos, en minúsculas). El orden fija el de las reglas devueltas.
HEURISTIC_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "contract",
        _rule(
            r"\b(contrato|contratad[oa]s?|contratamos|firmad[oa]s?|firmamos|orden de compra|"
            r"propuesta (aceptada|aprobada)|aceptamos la propuesta|acuerdo (marco|firmado|cerrado)|signed|contract)\b"
        ),
    ),
    (
        "closed_scope",
        _rule(
            r"\b(alcance (cerrado|congelado|acordado|final|definido|fijo)|alcance ya (esta )?(cerrado|definido)|"
            r"congelamos el alcance|el alcance (esta|queda) (cerrado|definido|congelado)|sin cambios de alcance|"
            r"no se (anadira|incluira)n? (mas )?(funcionalidades|requisitos)|scope (is )?(frozen|closed|fixed))\b"
        ),
    ),
    (
        "agreed_budget",
        _rule(
            r"(presupuesto (acordado|aprobado|cerrado|maximo|fijo|limite|tope|disponible)|"
            r"(tope|limite|maximo) de (presupuesto|\d)|presupuesto de \d|"
            r"(acordamos|aprobamos|tenemos aprobado|disponemos de)\b[^.\n]{0,40}"
            r"\d[\d.,]*\s*(k|mil|m)?\s*(€|eur|euros|usd|\$)|"
            r"no (podemos|vamos a poder) (pasar|superar|gastar mas)[^.\n]{0,25}\d)"
        ),
    ),
    (
        "deadline",
        _rule(
            r"\b(fecha limite|fecha tope|deadline|plazo (maximo|limite|fijo|inamovible|de entrega)|a mas tardar|"
            r"go[- ]?live|fecha de (lanzamiento|entrega|salida)|"
            r"(entregar|lanzar|salir|publicar)\w* (antes|para)( el| del| de)?|"
            r"antes del? \d{1,2}|hasta el \d{1,2}|para el \d{1,2} de \w+|en \d+ (semanas|meses) como maximo)\b"
        ),
    ),
    (
        "legal_regulatory",
        _rule(
            r"\b(rgpd|gdpr|lopd|hipaa|pci[- ]?dss|psd2|dora|sox|iso ?27001|nda|"
            r"regulat\w+|normativ\w+|legal(es|mente)?|cumplimiento (normativo|legal)|compliance|"
            r"proteccion de datos|confidencial\w*|acuerdo de confidencialidad|auditoria obligatoria|licencia obligatoria)\b"
        ),
    ),
)


class HeuristicAnchorDetector:
    """Reglas con nombre sobre el mensaje del usuario; no hace E/S."""

    def __init__(self, rules: tuple[tuple[str, re.Pattern[str]], ...] = HEURISTIC_RULES):
        self._rules = rules

    def match_rules(self, text: str) -> tuple[str, ...]:
        folded = fold(text)
        return tuple(name for name, pattern in self._rules if pattern.search(folded))

    async def detect(self, user: str, assistant: str) -> AnchorMatch | None:
        rules = self.match_rules(user)
        return AnchorMatch(rules=rules, source="heuristic") if rules else None


class AnchorVerdict(BaseModel):
    """Salida estructurada del detector LLM."""

    is_anchor: bool
    rules: list[AnchorRule] = Field(default_factory=list, max_length=len(HEURISTIC_RULES))


class LLMAnchorDetector:
    """Clasifica el par con una llamada estructurada; ante un fallo usa el detector heurístico."""

    def __init__(
        self,
        settings: Settings,
        *,
        generate: Generator = generate_from_messages,
        fallback: AnchorDetector | None = None,
    ):
        self.settings = settings
        self._generate = generate
        self._fallback = fallback or HeuristicAnchorDetector()

    async def detect(self, user: str, assistant: str) -> AnchorMatch | None:
        system, prompt = render_auxiliary_prompt(
            "anchors",
            {
                "user_message": user[:_DETECTOR_USER_CHARS],
                "assistant_message": assistant[:_DETECTOR_ASSISTANT_CHARS],
            },
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        options: dict = {"max_tokens": _DETECTOR_MAX_TOKENS}
        if self.settings.summary_model:
            options["model"] = self.settings.summary_model
        try:
            verdict, _ = await generate_structured(self._generate, messages, AnchorVerdict, **options)
        except Exception as exc:
            logger.warning("anchor_detector_failed", error_type=type(exc).__name__)
            return await self._fallback.detect(user, assistant)
        if not verdict.is_anchor:
            return None
        return AnchorMatch(rules=tuple(verdict.rules) or ("llm_unspecified",), source="llm")


def build_anchor_detector(settings: Settings, generate: Generator = generate_from_messages) -> AnchorDetector:
    if settings.anchor_detection_mode == "llm":
        return LLMAnchorDetector(settings, generate=generate)
    return HeuristicAnchorDetector()
