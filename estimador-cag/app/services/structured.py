"""Generación estructurada: respuesta del LLM validada con un modelo Pydantic.

Es la primitiva común de las tareas auxiliares que devuelven JSON (detector de anclas con LLM,
crítico). Reutiliza el generador del proyecto (`generate_from_messages`: caché, reintentos, fallback,
costes) y `extract_json`, y ante una respuesta inválida pide una corrección en la misma llamada de
conversación, igual que la estimación. No añade dependencias; ver `docs/evaluacion-instructor-litellm.md`
para la comparación con Instructor.
"""

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel, ValidationError

from app.services.llm_wrapper import Completion
from app.services.validation import ResultValidationError, correction_message, extract_json

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)
Generator = Callable[..., Awaitable[Completion]]

_PREVIOUS_ANSWER_LIMIT = 6000


class StructuredOutputError(ValueError):
    """El modelo no devolvió un objeto válido tras los intentos permitidos."""


def _parse(text: str, schema: type[T]) -> T:
    try:
        return schema.model_validate(extract_json(text))
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
        raise ResultValidationError(f"El JSON no cumple el esquema ({details}).") from None


async def generate_structured(
    generate: Generator,
    messages: list[dict[str, str]],
    schema: type[T],
    *,
    attempts: int = 2,
    **options: Any,
) -> tuple[T, list[Completion]]:
    """Genera y valida un `schema`; devuelve el objeto y las completions consumidas.

    `options` se pasa tal cual a `generate` (por ejemplo `max_tokens` o `model`). Lanza
    `StructuredOutputError` si ninguno de los `attempts` produce un objeto válido; los errores del
    proveedor (`HTTPException`) se propagan sin reintentos adicionales aquí.
    """

    def accepted(text: str) -> bool:
        try:
            _parse(text, schema)
        except ResultValidationError:
            return False
        return True

    completions: list[Completion] = []
    current = messages
    last_error = "respuesta inválida"
    for attempt in range(1, attempts + 1):
        completion = await generate(current, accept=accepted, **options)
        completions.append(completion)
        try:
            return _parse(completion.text, schema), completions
        except ResultValidationError as exc:
            last_error = str(exc)
            logger.warning("structured_output_invalid", attempt=attempt, max_attempts=attempts)
            # La corrección va solo en esta llamada: no se arrastra a la conversación original.
            current = [
                *messages,
                {"role": "assistant", "content": completion.text[:_PREVIOUS_ANSWER_LIMIT]},
                {"role": "user", "content": correction_message(last_error)},
            ]
    raise StructuredOutputError(last_error)
