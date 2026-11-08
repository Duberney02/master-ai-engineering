"""Cliente HTTP síncrono del backend `estimator-web` (API JSON bajo `/api/`).

Es lo único que habla con la red. Traduce cualquier fallo a `EstimationError` con un mensaje en español apto para el
usuario: nunca cuerpos crudos, trazas ni URLs internas. No necesita claves de proveedores.
"""

from collections.abc import Iterable

import httpx
from pydantic import ValidationError

from .models import EstimationResponse, PromptPreview

_TIMEOUT = httpx.Timeout(600, connect=10)
_PREVIEW_TIMEOUT = httpx.Timeout(30, connect=10)
CONNECTION_MESSAGE = "No se pudo conectar con el backend del estimador."
INVALID_MESSAGE = "El backend devolvió datos inválidos."
DETAIL_LIMIT = 300


class EstimationError(Exception):
    """Fallo saneado: su mensaje se puede mostrar tal cual."""


class ConversationExpiredError(EstimationError):
    """El backend ya no conoce la conversación (reinicio del servicio de IA o caducidad): hay que abrir otra."""


def _detail(response: httpx.Response) -> str | None:
    """`detail` de texto del backend; lo redacta el servidor sin datos del usuario."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return None
    return detail[:DETAIL_LIMIT] if isinstance(detail, str) and detail.strip() else None


def _rejection(response: httpx.Response) -> EstimationError:
    return EstimationError(_detail(response) or f"El backend rechazó la solicitud (HTTP {response.status_code}).")


def create_conversation(base_url: str) -> str:
    """Abre una conversación vacía y devuelve su `conversation_id`."""
    try:
        response = httpx.post(f"{base_url.rstrip('/')}/api/conversations", timeout=_TIMEOUT)
    except httpx.HTTPError:
        raise EstimationError(CONNECTION_MESSAGE) from None
    if response.status_code != 201:
        raise _rejection(response)
    try:
        conversation_id = response.json()["conversation_id"]
    except (ValueError, KeyError, TypeError):
        raise EstimationError(INVALID_MESSAGE) from None
    if not isinstance(conversation_id, str) or not conversation_id:
        raise EstimationError(INVALID_MESSAGE)
    return conversation_id


def request_estimation(
    base_url: str,
    conversation_id: str,
    *,
    description: str,
    attachments: Iterable[tuple[str, bytes]] = (),
    project_type: str,
    detail_level: str,
    output_format: str,
    prompt_version: str,
) -> EstimationResponse:
    """Una estimación dentro de la conversación: descripción, adjuntos PDF/Word y opciones tipadas.

    Ante cualquier fallo lanza `EstimationError` con un mensaje saneado; `ConversationExpiredError` si el backend ya no
    conoce la conversación.
    """
    files = [("attachments", (name, content)) for name, content in attachments]
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/api/conversations/{conversation_id}/estimations",
            data={
                "description": description,
                "project_type": project_type,
                "detail_level": detail_level,
                "output_format": output_format,
                "prompt_version": prompt_version,
            },
            files=files or None,
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError:
        raise EstimationError(CONNECTION_MESSAGE) from None
    if response.status_code == 404:
        raise ConversationExpiredError("La conversación anterior expiró.")
    if response.status_code != 200:
        raise _rejection(response)
    try:
        return EstimationResponse.model_validate(response.json())
    except (ValueError, ValidationError):
        raise EstimationError(INVALID_MESSAGE) from None


def fetch_prompt_preview(
    base_url: str, *, prompt_version: str, project_type: str, detail_level: str, output_format: str
) -> PromptPreview:
    """Prompt de sistema renderizado y ejemplos few-shot para unas opciones (barra lateral)."""
    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/api/prompt-preview",
            params={
                "prompt_version": prompt_version,
                "project_type": project_type,
                "detail_level": detail_level,
                "output_format": output_format,
            },
            timeout=_PREVIEW_TIMEOUT,
        )
    except httpx.HTTPError:
        raise EstimationError(CONNECTION_MESSAGE) from None
    if response.status_code != 200:
        raise _rejection(response)
    try:
        return PromptPreview.model_validate(response.json())
    except (ValueError, ValidationError):
        raise EstimationError(INVALID_MESSAGE) from None
