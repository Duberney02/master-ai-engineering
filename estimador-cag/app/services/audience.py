"""Resolución de la audiencia de una estimación mediante reglas ordenadas y deterministas.

Perfiles: `executive` (dirección), `pm` (gestión), `developer` (ingeniería) y `default`. Las reglas se
evalúan en orden sobre la transcripción y los metadatos del proyecto y gana la primera que coincide;
el resultado incluye el nombre de la regla para que la decisión sea explicable. Una audiencia
explícita (`tier`) prevalece sobre todas.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from app.services.anchors import HEURISTIC_RULES, fold
from app.services.sessions import ProjectMetadata


class Audience(str, Enum):
    EXECUTIVE = "executive"
    PM = "pm"
    DEVELOPER = "developer"
    DEFAULT = "default"


EXPLICIT_RULE = "explicit"
NO_MATCH_RULE = "no_match"
# Términos técnicos distintos necesarios para considerar una audiencia de ingeniería.
TECH_TERMS_THRESHOLD = 3
# Equipo (personas) a partir del cual deja de considerarse «pequeño».
SMALL_TEAM_MAX = 5

_LEGAL_REGULATORY = dict(HEURISTIC_RULES)["legal_regulatory"]
_TECH_TERMS = re.compile(
    r"\b(api|apis|rest|restful|graphql|grpc|websocket|webhook|sdk|microservicios?|kubernetes|docker|"
    r"ci/cd|devops|terraform|aws|azure|gcp|postgres(?:ql)?|mysql|mongodb|redis|kafka|rabbitmq|elasticsearch|"
    r"react|angular|vue|django|fastapi|flask|spring|node(?:\.?js)?|typescript|python|java|golang|kotlin|swift|"
    r"flutter|oauth2?|jwt|sso|saml|orm|etl|airflow|spark|dbt|snowflake|bigquery|latencia|"
    r"arquitectura de software|base de datos|backend|frontend|endpoint)\b"
)


@dataclass(frozen=True)
class AudienceContext:
    transcript: str
    metadata: ProjectMetadata


@dataclass(frozen=True)
class AudienceRule:
    name: str
    audience: Audience
    matches: Callable[[AudienceContext], bool]


@dataclass(frozen=True)
class AudienceResolution:
    audience: Audience
    rule: str


def technical_terms(context: AudienceContext) -> set[str]:
    """Términos técnicos distintos del texto y de las tecnologías ya conocidas del proyecto."""
    found = set(_TECH_TERMS.findall(fold(context.transcript)))
    found.update(fold(technology) for technology in context.metadata.mentioned_technologies)
    return found


def _confidentiality_or_regulatory(context: AudienceContext) -> bool:
    return bool(_LEGAL_REGULATORY.search(fold(context.transcript)))


def _many_technical_terms(context: AudienceContext) -> bool:
    return len(technical_terms(context)) >= TECH_TERMS_THRESHOLD


def _small_team(context: AudienceContext) -> bool:
    size = context.metadata.assumed_team_size
    return size is not None and size <= SMALL_TEAM_MAX


# El orden fija la prioridad: un contexto confidencial o regulatorio manda sobre el perfil técnico.
AUDIENCE_RULES: tuple[AudienceRule, ...] = (
    AudienceRule("confidentiality_or_regulatory", Audience.EXECUTIVE, _confidentiality_or_regulatory),
    AudienceRule("technical_terms", Audience.DEVELOPER, _many_technical_terms),
    AudienceRule("small_team", Audience.PM, _small_team),
)


def resolve_audience(
    transcript: str,
    metadata: ProjectMetadata,
    explicit: Audience | str | None = None,
    rules: tuple[AudienceRule, ...] = AUDIENCE_RULES,
) -> AudienceResolution:
    """Audiencia y regla aplicada. `explicit` (el `tier` de la solicitud) prevalece sobre las reglas."""
    if explicit is not None:
        return AudienceResolution(Audience(explicit), EXPLICIT_RULE)
    context = AudienceContext(transcript, metadata)
    for rule in rules:
        if rule.matches(context):
            return AudienceResolution(rule.audience, rule.name)
    return AudienceResolution(Audience.DEFAULT, NO_MATCH_RULE)
