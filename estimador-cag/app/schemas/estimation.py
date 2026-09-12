"""Contratos (Pydantic) del endpoint de estimación.

Define explícitamente la forma de los datos que intercambian el servidor y
sus consumidores para `/api/v1/estimate`, separada de la lógica del router.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class EstimationRequest(BaseModel):
    transcription: str = Field(
        min_length=20,
        max_length=50_000,
        description="Transcripción de la reunión con el cliente.",
    )


class UsageInfo(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class EstimationResponse(BaseModel):
    estimation: str
    model: str
    provider: str
    usage: UsageInfo
    estimated_cost_usd: float | None
    latency_ms: int
    generated_at: datetime
