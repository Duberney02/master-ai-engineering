"""Configuración de modelos de LLM en tiempo de ejecución (pantalla de Ajustes de los clientes).

Router fino: la validación de la actualización parcial es la única lógica; el almacén de overrides vive en
`app/foundation/llm/runtime_config.py`. Un cambio aplica a partir de la siguiente solicitud, sin reconstruir clientes
ni reiniciar.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config import Settings
from app.dependencies import get_runtime_config
from app.foundation.llm.runtime_config import (
    MODEL_KNOBS,
    PROVIDER_KEY_FIELDS,
    RuntimeConfigUnavailable,
    RuntimeModelConfig,
    provider_for_model,
    provider_key_configured,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/config", tags=["config"])

EMBEDDING_MODEL_NOTE = "Solo lectura: cambiarlo invalidaría todos los vectores guardados."

# Proveedor que exige cada chunker con LLM (el proposicional usa la API de OpenAI y el contextual la de Anthropic).
CHUNKER_PROVIDERS = {"propositional_chunker_model": "openai", "contextual_chunker_model": "anthropic"}


class ModelUpdateRequest(BaseModel):
    """Actualización parcial: solo se tocan los knobs presentes; `null` restablece el valor por defecto."""

    models: dict[str, str | None] = Field(min_length=1)


def available_models(settings: Settings) -> list[str]:
    """Catálogo filtrado por las claves de proveedor realmente configuradas."""
    return [
        model
        for model in settings.available_models_list()
        if provider_key_configured(settings, provider_for_model(model, settings.llm_provider))
    ]


async def _payload(config: RuntimeModelConfig) -> dict:
    settings = config.settings
    return {
        "models": await config.snapshot(),
        "available_models": available_models(settings),
        "embedding_model": settings.embedding_model,
        "embedding_model_note": EMBEDDING_MODEL_NOTE,
    }


def _validate(knob: str, model: str | None, settings: Settings) -> None:
    if knob not in MODEL_KNOBS:
        raise HTTPException(status_code=422, detail=f"Knob desconocido: {knob}")
    if model is None:
        return  # restablecer siempre es válido
    if model not in settings.available_models_list():
        raise HTTPException(status_code=422, detail=f"El modelo '{model}' no está en el catálogo")
    provider = provider_for_model(model, settings.llm_provider)
    if not provider_key_configured(settings, provider):
        key = PROVIDER_KEY_FIELDS[provider].upper()
        raise HTTPException(status_code=400, detail=f"El modelo '{model}' requiere {key}, que no está configurada")
    required = CHUNKER_PROVIDERS.get(knob)
    if required and provider != required:
        raise HTTPException(status_code=422, detail=f"{knob} requiere un modelo de {required}, no '{model}'")


@router.get("/models")
async def get_models(config: RuntimeModelConfig = Depends(get_runtime_config)) -> dict:
    """Configuración actual: valor efectivo, valor por defecto y si hay override, por knob."""
    return await _payload(config)


@router.put("/models")
async def update_models(
    request: ModelUpdateRequest, config: RuntimeModelConfig = Depends(get_runtime_config)
) -> dict:
    """Aplica una actualización parcial, todo o nada: se valida cada entrada ANTES de escribir ninguna."""
    for knob, model in request.models.items():
        _validate(knob, model, config.settings)

    previous = {knob: item["effective"] for knob, item in (await config.snapshot()).items()}
    try:
        await config.set_many(request.models)
    except RuntimeConfigUnavailable as exc:
        logger.error("runtime_config_write_failed", error_type=str(exc))
        raise HTTPException(status_code=503, detail="El almacén de configuración no está disponible") from exc

    for knob, model in request.models.items():
        logger.info(
            "runtime_config_changed", key=knob, old_effective=previous[knob], new_value=model, reset=model is None
        )
    return await _payload(config)
