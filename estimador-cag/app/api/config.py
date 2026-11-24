"""Configuración en tiempo de ejecución (Ajustes de los clientes): modelos de LLM y recuperación (Sesión 10).

Router fino: la validación de la actualización parcial es la única lógica; el almacén de overrides vive en
`app/foundation/llm/runtime_config.py`. Un cambio aplica a partir de la siguiente solicitud, sin reconstruir clientes
ni reiniciar.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.config import Settings
from app.dependencies import get_runtime_config, get_runtime_retrieval_config
from app.foundation.llm.runtime_config import (
    MODEL_KNOBS,
    PROVIDER_KEY_FIELDS,
    RuntimeConfigUnavailable,
    RuntimeModelConfig,
    RuntimeRetrievalConfig,
    provider_for_model,
    provider_key_configured,
)
from app.generation.rag.schemas import SearchMode

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


# --- Recuperación (Sesión 10) ------------------------------------------------------------------------------------


class RetrievalUpdateRequest(BaseModel):
    """Actualización parcial de los parámetros de recuperación.

    Solo se tocan las claves presentes; `null` restablece el valor por defecto de `Settings`. Una clave ausente no
    cambia. Un modo desconocido, un valor fuera de rango o una clave que no existe es `422`.
    """

    model_config = ConfigDict(extra="forbid")

    search_mode: SearchMode | None = Field(default=None, description="`vector` o `hybrid`.")
    rerank: bool | None = Field(default=None, description="Reordenar con el cross-encoder.")
    routing_enabled: bool | None = Field(default=None, description="Routing multi-índice en la búsqueda avanzada.")
    query_transform_enabled: bool | None = Field(default=None, description="Expansión/descomposición de consulta.")
    temporal_decay_enabled: bool | None = Field(default=None, description="Decay temporal de los finalistas.")
    task_hours_top_k: int | None = Field(default=None, ge=1, le=30, description="Vecinos por tarea (horas).")
    task_hours_distance_threshold: float | None = Field(
        default=None, ge=0, le=2, allow_inf_nan=False, description="Distancia máxima: más allá, sin horas."
    )
    hallucination_gate_enabled: bool | None = Field(default=None, description="Gate de alucinaciones (ancla + juez).")
    hallucination_numeric_tolerance: float | None = Field(
        default=None, ge=0, le=10, allow_inf_nan=False, description="Tolerancia relativa sobre el ancla numérica."
    )
    augmentation_enabled: bool | None = Field(default=None, description="Aumentación del contexto recuperado.")
    augmentation_compress: bool | None = Field(default=None, description="Compresión extractiva del contexto.")
    augmentation_reorder: bool | None = Field(default=None, description="Reordenación de bordes del contexto.")
    synthesis_enabled: bool | None = Field(default=None, description="Rango de horas ante vecinos contradictorios.")
    synthesis_contradiction_threshold: float | None = Field(
        default=None, ge=0, le=5, allow_inf_nan=False, description="Dispersión a partir de la cual hay rango."
    )


async def _retrieval_payload(config: RuntimeRetrievalConfig) -> dict:
    return {"retrieval": await config.snapshot(), "reranker_model": config.settings.reranker_model}


@router.get("/retrieval")
async def get_retrieval(config: RuntimeRetrievalConfig = Depends(get_runtime_retrieval_config)) -> dict:
    """Parámetros de recuperación: valor efectivo, valor por defecto y si hay override, más el modelo del reranker."""
    return await _retrieval_payload(config)


@router.put("/retrieval")
async def update_retrieval(
    request: RetrievalUpdateRequest, config: RuntimeRetrievalConfig = Depends(get_runtime_retrieval_config)
) -> dict:
    """Aplica una actualización parcial, todo o nada; el cambio vale desde la siguiente recuperación, sin reiniciar."""
    changes = {name: getattr(request, name) for name in request.model_fields_set}
    previous = {name: item["effective"] for name, item in (await config.snapshot()).items()}
    try:
        await config.set_many(changes)
    except RuntimeConfigUnavailable as exc:
        logger.error("runtime_retrieval_write_failed", error_type=str(exc))
        raise HTTPException(status_code=503, detail="El almacén de configuración no está disponible") from exc

    for name, value in changes.items():
        logger.info(
            "runtime_retrieval_changed", key=name, old_effective=previous[name], new_value=value, reset=value is None
        )
    return await _retrieval_payload(config)
