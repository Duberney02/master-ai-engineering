"""Guardrails de entrada: datos personales, prompt injection y moderación.

Se ejecutan antes de consultar cachés o llamar al proveedor. Los detectores locales
(baratos y deterministas) van primero; la moderación, que hace una llamada de red, al final.
Los mensajes nunca reproducen el valor detectado.
"""

import inspect
import re
import unicodedata

import structlog
from fastapi import HTTPException
from openai import AsyncOpenAI

from app.config import Settings
from app.schemas import EstimationRequest

logger = structlog.get_logger(__name__)

# Tamaño máximo de cada tramo enviado a moderación (una llamada, varios tramos).
MODERATION_CHUNK_CHARS = 30_000

REASON_MODERATION = "moderation"
REASON_INJECTION = "prompt_injection"
REASON_EMAIL = "pii_email"
REASON_PHONE = "pii_phone"
REASON_IBAN = "pii_iban"

_MESSAGES = {
    REASON_MODERATION: "El contenido no es apropiado para una estimación. Reformula la descripción.",
    REASON_INJECTION: (
        "La descripción parece contener instrucciones dirigidas al modelo. "
        "Describe solo el proyecto que quieres estimar."
    ),
    REASON_EMAIL: "La descripción contiene una dirección de correo electrónico. Elimínala.",
    REASON_PHONE: "La descripción contiene un número de teléfono. Elimínalo.",
    REASON_IBAN: "La descripción contiene un IBAN. Elimínalo.",
}


class GuardrailViolation(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
        self.message = _MESSAGES[reason]


_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_IBAN = re.compile(r"\b[A-Za-z]{2}\d{2}(?:[ -]?[A-Za-z0-9]){11,30}\b")
_PHONE = re.compile(r"(?<![\w.])\+?\d(?:[\d\s().-]{6,}\d)(?![\w])")

_INJECTION_PATTERNS = [
    r"\b(ignora|ignorad|ignore|omite|olvida|descarta)\w*\s+(todas?\s+)?(las\s+|tus\s+|mis\s+)?"
    r"(instrucciones|reglas|indicaciones|ordenes)",
    r"\b(ignore|disregard|forget|override)\s+(all\s+|any\s+|your\s+|the\s+)*"
    r"(previous|prior|above|earlier|system)?\s*(instructions|rules|prompts?|guidelines)",
    r"\bolvida\s+(todo|lo anterior)",
    r"\bforget\s+(everything|all)\b",
    r"\b(revela|muestra|imprime|repite|dime|reveal|show|print|repeat|leak)\w*\s+"
    r"(me\s+)?(tu|el|your|the)\s+(system\s+)?(prompt|instrucciones|instructions)",
    r"\bsystem\s+prompt\b",
    r"\bprompt\s+de\s+sistema\b",
    r"\b(ahora eres|a partir de ahora eres|you are now|from now on you)\b",
    r"\bjailbreak\b",
    r"\b(dan|developer)\s+mode\b",
    r"</?\s*(system|project_description|reference_projects)\s*>",
]
_INJECTION = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS))


def _normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped)


# Longitud del IBAN por país (el candidato puede arrastrar palabras detrás del número).
_IBAN_LENGTHS = {
    "AD": 24,
    "AT": 20,
    "BE": 16,
    "BG": 22,
    "CH": 21,
    "CY": 28,
    "CZ": 24,
    "DE": 22,
    "DK": 18,
    "EE": 20,
    "ES": 24,
    "FI": 18,
    "FR": 27,
    "GB": 22,
    "GR": 27,
    "HR": 21,
    "HU": 28,
    "IE": 22,
    "IS": 26,
    "IT": 27,
    "LI": 21,
    "LT": 20,
    "LU": 20,
    "LV": 21,
    "MC": 27,
    "MT": 31,
    "NL": 18,
    "NO": 15,
    "PL": 28,
    "PT": 25,
    "RO": 24,
    "SE": 24,
    "SI": 19,
    "SK": 24,
    "SM": 27,
}


def _iban_is_valid(candidate: str) -> bool:
    compact = re.sub(r"[ -]", "", candidate).upper()
    length = _IBAN_LENGTHS.get(compact[:2])
    if length is None or len(compact) < length:
        return False
    iban = compact[:length]
    rearranged = iban[4:] + iban[:4]
    return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1


def detect_pii(text: str) -> str | None:
    """Devuelve la razón del primer dato personal encontrado, o None."""
    if _EMAIL.search(text):
        return REASON_EMAIL
    for match in _IBAN.finditer(text):
        if _iban_is_valid(match.group()):
            return REASON_IBAN
    for match in _PHONE.finditer(text):
        if 9 <= sum(c.isdigit() for c in match.group()) <= 15:
            return REASON_PHONE
    return None


def detect_prompt_injection(text: str) -> bool:
    return bool(_INJECTION.search(_normalize(text)))


def _chunks(text: str, size: int = MODERATION_CHUNK_CHARS) -> list[str]:
    return [text[start : start + size] for start in range(0, len(text), size)] or [""]


def request_texts(request: EstimationRequest) -> list[str]:
    texts = [request.description]
    for project in request.reference_projects or []:
        texts += [project.name, project.description]
    return texts


class InputGuardrails:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def check(self, request: EstimationRequest) -> None:
        """Lanza `GuardrailViolation` si la entrada no es aceptable."""
        texts = request_texts(request)
        for text in texts:
            reason = detect_pii(text)
            if reason:
                self._reject(reason)
        for text in texts:
            if detect_prompt_injection(text):
                self._reject(REASON_INJECTION)
        if await self._flagged("\n".join(texts)):
            self._reject(REASON_MODERATION)

    @staticmethod
    def _reject(reason: str) -> None:
        logger.warning("guardrail_rejected", reason=reason)
        raise GuardrailViolation(reason)

    async def _flagged(self, text: str) -> bool:
        settings = self.settings
        if not settings.moderation_enabled:
            return False
        if not settings.openai_api_key:
            logger.warning("moderation_skipped", reason="no_openai_key")
            return False
        client = AsyncOpenAI(
            api_key=settings.openai_api_key, timeout=settings.llm_timeout, max_retries=settings.llm_retries
        )
        try:
            response = await client.moderations.create(model=settings.moderation_model, input=_chunks(text))
            return any(result.flagged for result in response.results)
        except Exception as exc:
            logger.error("moderation_failed", error_type=type(exc).__name__)
            if settings.moderation_fail_open:
                return False
            raise HTTPException(503, "Content moderation unavailable") from None
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                result = close()
                if inspect.isawaitable(result):
                    await result
